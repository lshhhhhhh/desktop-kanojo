from __future__ import annotations

import asyncio
import json
import os
import queue as thread_queue
import threading
from typing import AsyncIterator

import httpx
from loguru import logger

from .base import ChatChunk, ChatRequest, ContentPart, LLMBackend


# Sentinel objects shared between the sync producer thread and the async
# consumer in `chat()`. Real chunks are ChatChunk; exceptions and end-of-stream
# are smuggled through the same queue.
_END = object()


class OpenAICompatBackend(LLMBackend):
    """Backend talking any OpenAI-compatible /v1/chat/completions endpoint.

    Works with: OpenAI, Ollama, vLLM, LM Studio, llama.cpp server, DeepSeek,
    Qwen DashScope (OpenAI mode), and most modern providers.
    """

    def __init__(
        self,
        name: str,
        base_url: str,
        model: str,
        api_key: str | None = None,
        api_key_env: str | None = None,
        vision: bool = True,
        timeout_s: float = 300.0,
        extra_body: dict | None = None,
        supports_temperature: bool = True,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._vision = vision
        self._timeout_s = timeout_s
        self._extra_body = extra_body or {}
        self._supports_temperature = supports_temperature

        key = api_key
        if api_key_env:
            key = os.environ.get(api_key_env) or key
        self.api_key = key or ""

    def supports_vision(self) -> bool:
        return self._vision

    @staticmethod
    def _serialize_content(parts: list[ContentPart]) -> str | list[dict]:
        if len(parts) == 1 and parts[0].type == "text":
            return parts[0].text or ""
        out: list[dict] = []
        for p in parts:
            if p.type == "text":
                out.append({"type": "text", "text": p.text or ""})
            elif p.type == "image":
                url = f"data:{p.image_mime};base64,{p.image_b64}"
                out.append({"type": "image_url", "image_url": {"url": url}})
        return out

    def _build_payload(self, req: ChatRequest) -> dict:
        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": m.role, "content": self._serialize_content(m.content)}
                for m in req.messages
            ],
            "stream": req.stream,
        }
        if self._supports_temperature:
            payload["temperature"] = req.temperature
        if req.max_tokens is not None:
            payload["max_tokens"] = req.max_tokens
        if self._extra_body:
            payload.update(self._extra_body)
        return payload

    async def chat(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        """Stream chat completions.

        Why sync httpx in a thread? Under qasync (PySide6 + asyncio bridge),
        yielding inside nested `async with httpx.AsyncClient/Client.stream`
        triggers "Attempted to exit cancel scope in a different task" errors
        from anyio's task-aware cancel scopes when the async generator's
        cleanup runs in a different task than its entry. A real OS thread
        owning the HTTP lifecycle sidesteps the entire anyio machinery while
        still streaming chunks back as they arrive.
        """
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = self._build_payload(req)
        url = f"{self.base_url}/chat/completions"

        q: thread_queue.Queue = thread_queue.Queue(maxsize=64)
        stop = threading.Event()
        loop = asyncio.get_running_loop()
        thread = threading.Thread(
            target=self._produce_sync,
            args=(url, headers, payload, req.stream, q, stop),
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
        headers: dict,
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
                    resp = client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    choice = data["choices"][0]
                    put(
                        ChatChunk(
                            delta=choice["message"]["content"] or "",
                            finish_reason=choice.get("finish_reason"),
                        )
                    )
                    return

                with client.stream("POST", url, headers=headers, json=payload) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if stop.is_set():
                            return
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[len("data: "):]
                        if data_str.strip() == "[DONE]":
                            return
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            logger.warning(
                                "Bad SSE line from {}: {}", self.name, data_str[:200]
                            )
                            continue
                        if not chunk.get("choices"):
                            continue
                        choice = chunk["choices"][0]
                        delta = (choice.get("delta") or {}).get("content") or ""
                        finish = choice.get("finish_reason")
                        if delta or finish:
                            if not put(ChatChunk(delta=delta, finish_reason=finish)):
                                return
        except Exception as e:
            put(e)
        finally:
            try:
                q.put(_END, timeout=1.0)
            except thread_queue.Full:
                pass
