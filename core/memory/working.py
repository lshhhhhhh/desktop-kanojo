from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass
class Turn:
    speaker: str
    text: str


class WorkingMemory:
    """L1: rolling window of recent conversation turns (in RAM)."""

    def __init__(self, max_turns: int = 10) -> None:
        self.max_turns = max_turns
        self._buf: deque[Turn] = deque(maxlen=max_turns)

    def append(self, speaker: str, text: str) -> None:
        self._buf.append(Turn(speaker=speaker, text=text))

    def turns(self) -> list[Turn]:
        return list(self._buf)

    def clear(self) -> None:
        self._buf.clear()

    def __len__(self) -> int:
        return len(self._buf)
