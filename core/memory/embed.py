from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
import numpy as np
from loguru import logger


class Embedder:
    """OpenAI-compatible /embeddings client.

    Works with: Gemini (`https://generativelanguage.googleapis.com/v1beta/openai`),
    OpenAI, Voyage, Mistral, and any provider exposing the OpenAI embeddings API.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        dim: int,
        api_key: str | None = None,
        api_key_env: str | None = None,
        timeout_s: float = 30.0,
        normalize: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dim = dim
        self._timeout_s = timeout_s
        self.normalize = normalize
        key = api_key
        if api_key_env:
            key = os.environ.get(api_key_env) or key
        if not key:
            raise ValueError(
                f"Embedding API key missing. Set env var '{api_key_env}' "
                f"or embedding.api_key in config."
            )
        self.api_key = key

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> Embedder:
        e = cfg["embedding"]
        return cls(
            base_url=e["base_url"],
            model=e["model"],
            dim=int(e["dim"]),
            api_key=e.get("api_key"),
            api_key_env=e.get("api_key_env"),
        )

    async def embed(self, texts: list[str]) -> list[np.ndarray]:
        if not texts:
            return []
        # Sync httpx in an executor thread; under qasync, async httpx.AsyncClient
        # cleanup hits anyio cancel-scope errors when run inside async generators.
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._embed_sync, texts)

    def _embed_sync(self, texts: list[str]) -> list[np.ndarray]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: dict[str, Any] = {
            "input": texts,
            "model": self.model,
            "dimensions": self.dim,
        }
        with httpx.Client(timeout=httpx.Timeout(self._timeout_s)) as client:
            resp = client.post(
                f"{self.base_url}/embeddings", headers=headers, json=payload
            )
            if resp.status_code >= 400:
                logger.error(
                    "embedding request failed: {} {}",
                    resp.status_code,
                    resp.text[:400],
                )
                resp.raise_for_status()
            data = resp.json()

        vecs: list[np.ndarray] = []
        for d in data["data"]:
            v = np.array(d["embedding"], dtype=np.float32)
            if self.normalize:
                n = np.linalg.norm(v)
                if n > 0:
                    v = v / n
            vecs.append(v)
        return vecs

    async def embed_one(self, text: str) -> np.ndarray:
        out = await self.embed([text])
        return out[0]
