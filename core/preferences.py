"""User preferences persisted across runs.

Lives at `./data/preferences.yaml` next to the SQLite memory DB. Keeps small
UI/runtime choices that don't belong in the read-only `config.yaml`:
currently the audio output device. Missing file or missing keys are OK — we
just fall back to defaults.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from loguru import logger

DEFAULT_PATH = Path("./data/preferences.yaml")


def load(path: Path = DEFAULT_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning("preferences: failed to load {}: {}", path, e)
        return {}


def save(prefs: dict[str, Any], path: Path = DEFAULT_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(prefs, f, allow_unicode=True, sort_keys=False)
    except Exception as e:
        logger.warning("preferences: failed to save {}: {}", path, e)


def get_audio_output_id(path: Path = DEFAULT_PATH) -> str | None:
    """Returns the saved Qt audio device id (as a base64 string) or None."""
    return load(path).get("audio_output_id")


def set_audio_output_id(device_id: str | None, path: Path = DEFAULT_PATH) -> None:
    prefs = load(path)
    if device_id is None:
        prefs.pop("audio_output_id", None)
    else:
        prefs["audio_output_id"] = device_id
    save(prefs, path)
