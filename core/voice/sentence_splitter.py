from __future__ import annotations


class SentenceBuffer:
    """Accumulates streamed text and emits complete sentences when punctuation
    arrives, so TTS can speak in coherent units rather than per-chunk fragments.

    "Sentence" here means: anything ending in . ! ? 。！？ or a newline, with
    a minimum length to avoid over-splitting (e.g., a stray '?' on its own).
    """

    DEFAULT_PUNCT = set("。！？!?\n")

    def __init__(
        self,
        min_chars: int = 2,
        punct: set[str] | None = None,
    ) -> None:
        self.buf = ""
        self.min_chars = min_chars
        self.punct = punct or self.DEFAULT_PUNCT

    def feed(self, text: str) -> list[str]:
        if not text:
            return []
        self.buf += text
        out: list[str] = []
        while True:
            split_at = -1
            for i, ch in enumerate(self.buf):
                if ch in self.punct and i + 1 >= self.min_chars:
                    split_at = i
                    break
            if split_at < 0:
                break
            sentence = self.buf[: split_at + 1].strip()
            self.buf = self.buf[split_at + 1 :]
            if sentence:
                out.append(sentence)
        return out

    def flush(self) -> str:
        s = self.buf.strip()
        self.buf = ""
        return s
