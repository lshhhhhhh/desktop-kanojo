"""Gemini native backend.

Talks to Google's generativelanguage.googleapis.com:generateContent
directly (not via the OpenAI-compat shim) so we can enable Google Search
grounding, which the openai-compat endpoint refuses to pass through for
chat models.

The OpenAI-style ChatRequest is translated into Gemini's contents-array
schema; the Gemini response is parsed back into a sequence of ChatChunk.
Streaming uses :streamGenerateContent which returns SSE-ish JSON lines.

Same sync-httpx-in-a-thread pattern as openai_compat.py — under qasync,
nested async httpx + async generators trigger anyio cancel-scope crashes
when GC runs across tasks.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue as thread_queue
import threading
from collections.abc import AsyncIterator

import httpx
from loguru import logger

from .base import ChatChunk, ChatRequest, LLMBackend

_END = object()


class GeminiNativeBackend(LLMBackend):
    """Gemini via the native REST API. Supports Google Search grounding."""

    def __init__(
        self,
        name: str,
        model: str,
        api_key: str | None = None,
        api_key_env: str | None = None,
        vision: bool = True,
        search: bool = False,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout_s: float = 300.0,
    ) -> None:
        self.name = name
        self.model = model
        self.api_key_env = api_key_env
        self._literal_api_key = api_key or ""
        self._vision = vision
        self.search = search
        self.base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    @property
    def api_key(self) -> str:
        if self.api_key_env:
            from_env = os.environ.get(self.api_key_env)
            if from_env:
                return from_env
        return self._literal_api_key

    def supports_vision(self) -> bool:
        return self._vision

    def _to_gemini_contents(self, req: ChatRequest) -> tuple[list[dict], str | None]:
        """Convert OpenAI-style messages -> Gemini contents + system instruction.

        Gemini separates system_instruction from the conversation. Multiple
        system messages get concatenated. user/assistant become role=user/model
        with parts=[{text|inlineData}, ...]."""
        system_text_parts: list[str] = []
        contents: list[dict] = []
        for m in req.messages:
            if m.role == "system":
                # Flatten text parts into the system instruction.
                for p in m.content:
                    if p.type == "text" and p.text:
                        system_text_parts.append(p.text)
                continue
            role = "model" if m.role == "assistant" else "user"
            parts: list[dict] = []
            for p in m.content:
                if p.type == "text":
                    if p.text:
                        parts.append({"text": p.text})
                elif p.type == "image" and p.image_b64:
                    parts.append({
                        "inlineData": {
                            "mimeType": p.image_mime or "image/png",
                            "data": p.image_b64,
                        }
                    })
            if parts:
                contents.append({"role": role, "parts": parts})

        system_instruction = "\n\n".join(system_text_parts) if system_text_parts else None
        return contents, system_instruction

    def _build_payload(self, req: ChatRequest) -> dict:
        contents, system_instruction = self._to_gemini_contents(req)
        payload: dict = {"contents": contents}
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        generation_config: dict = {}
        if req.max_tokens is not None:
            generation_config["maxOutputTokens"] = req.max_tokens
        # Gemini's generateContent accepts temperature but we mostly leave it
        # to defaults; uncomment if we want explicit control.
        # generation_config["temperature"] = req.temperature
        if generation_config:
            payload["generationConfig"] = generation_config

        if self.search:
            payload["tools"] = [{"googleSearch": {}}]
        return payload

    async def chat(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        if not self.api_key:
            raise RuntimeError(
                f"Gemini API key missing (env var {self.api_key_env})"
            )
        payload = self._build_payload(req)
        url = (
            f"{self.base_url}/models/{self.model}:"
            f"{'streamGenerateContent' if req.stream else 'generateContent'}"
            f"?alt=sse&key={self.api_key}" if req.stream
            else f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
        )

        q: thread_queue.Queue = thread_queue.Queue(maxsize=64)
        stop = threading.Event()
        loop = asyncio.get_running_loop()
        thread = threading.Thread(
            target=self._produce_sync,
            args=(url, payload, req.stream, q, stop),
            daemon=True,
        )
        thread.start()
        try:
            while True:
                item = await loop.run_in_executor(None, q.get)
                if item is _END:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            stop.set()
            try:
                while True:
                    q.get_nowait()
            except thread_queue.Empty:
                pass

    def _produce_sync(
        self,
        url: str,
        payload: dict,
        stream: bool,
        q: thread_queue.Queue,
        stop: threading.Event,
    ) -> None:
        def put(item) -> bool:
            while not stop.is_set():
                try:
                    q.put(item, timeout=0.1)
                    return True
                except thread_queue.Full:
                    continue
            return False

        try:
            with httpx.Client(timeout=httpx.Timeout(self._timeout_s)) as client:
                if not stream:
                    resp = client.post(
                        url,
                        headers={"Content-Type": "application/json"},
                        json=payload,
                    )
                    if resp.status_code >= 400:
                        logger.error(
                            "gemini-native {} {}",
                            resp.status_code,
                            resp.text[:400],
                        )
                        resp.raise_for_status()
                    data = resp.json()
                    text = _extract_text(data)
                    finish = _extract_finish_reason(data)
                    put(ChatChunk(delta=text, finish_reason=finish))
                    return

                with client.stream(
                    "POST",
                    url,
                    headers={"Content-Type": "application/json"},
                    json=payload,
                ) as resp:
                    if resp.status_code >= 400:
                        body = resp.read().decode("utf-8", errors="replace")
                        logger.error("gemini-native stream {} {}", resp.status_code, body[:400])
                        resp.raise_for_status()
                    for line in resp.iter_lines():
                        if stop.is_set():
                            return
                        if not line:
                            continue
                        # SSE: lines look like "data: {json}"
                        if line.startswith("data: "):
                            line = line[len("data: "):]
                        if not line or line == "[DONE]":
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            logger.warning("gemini-native bad SSE line: {}", line[:200])
                            continue
                        text = _extract_text(data)
                        finish = _extract_finish_reason(data)
                        if text or finish:
                            if not put(ChatChunk(delta=text, finish_reason=finish)):
                                return
        except Exception as e:
            put(e)
        finally:
            try:
                q.put(_END, timeout=1.0)
            except thread_queue.Full:
                pass


def _extract_text(data: dict) -> str:
    """Walk a Gemini response (full or one streamed delta) and pull all text
    parts out, joined with no separator. Tolerates missing fields -- search
    grounding responses sometimes omit text on the first chunk."""
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    content = candidates[0].get("content") or {}
    out: list[str] = []
    for p in content.get("parts") or []:
        t = p.get("text")
        if t:
            out.append(t)
    return "".join(out)


def _extract_finish_reason(data: dict) -> str | None:
    candidates = data.get("candidates") or []
    if not candidates:
        return None
    return candidates[0].get("finishReason")
