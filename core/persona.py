from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from loguru import logger


@dataclass
class Persona:
    """A character card: identity + system prompt + example dialogs."""

    name: str
    display_prefix: str
    system_prompt: str
    examples: list[tuple[str, str]] = field(default_factory=list)
    # What the AI should call the user. Empty = unspecified (the AI picks
    # something neutral like "你"). Common values: "哥哥", "主人",
    # the user's real name. Appended to the system prompt at session-bind
    # time, not baked into system_prompt so users can swap addresses
    # without re-editing the whole persona.
    user_address: str = ""

    @classmethod
    def from_file(cls, path: str | Path) -> Persona:
        path = Path(path)
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls(
            name=str(data.get("name", "小妹")),
            display_prefix=str(data.get("display_prefix", "妹")),
            system_prompt=str(data.get("system_prompt", "")).strip(),
            examples=[
                (str(e.get("user", "")), str(e.get("assistant", "")))
                for e in data.get("examples", [])
                if isinstance(e, dict)
            ],
            user_address=str(data.get("user_address", "")).strip(),
        )

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> Persona:
        p = cfg.get("persona", {}) or {}
        active = p.get("active", "default")
        base = Path(p.get("path", "./personas"))
        target = base / f"{active}.yaml"
        if not target.exists():
            logger.warning("persona file {} not found, using built-in default", target)
            from core.session import DEFAULT_EXAMPLE_DIALOGS, DEFAULT_PERSONA

            return cls(
                name="小妹",
                display_prefix="妹",
                system_prompt=DEFAULT_PERSONA,
                examples=list(DEFAULT_EXAMPLE_DIALOGS),
            )
        return cls.from_file(target)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "name": self.name,
            "display_prefix": self.display_prefix,
            "system_prompt": self.system_prompt,
            "user_address": self.user_address,
            "examples": [
                {"user": u, "assistant": a} for u, a in self.examples
            ],
        }
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    @staticmethod
    def list_available(personas_dir: str | Path) -> list[str]:
        d = Path(personas_dir)
        if not d.exists():
            return []
        return sorted(p.stem for p in d.glob("*.yaml"))
