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


def get_chat_backend(path: Path = DEFAULT_PATH) -> str | None:
    """Returns the user-overridden default chat backend name, or None."""
    return load(path).get("chat_backend")


def set_chat_backend(backend_name: str | None, path: Path = DEFAULT_PATH) -> None:
    prefs = load(path)
    if backend_name is None:
        prefs.pop("chat_backend", None)
    else:
        prefs["chat_backend"] = backend_name
    save(prefs, path)


def get_live2d_active_model(path: Path = DEFAULT_PATH) -> str | None:
    """Returns the user-overridden active Live2D model folder name, or None.
    Set by the first-run wizard when the user installs a model via zip."""
    return load(path).get("live2d_active_model")


def set_live2d_active_model(
    model_name: str | None, path: Path = DEFAULT_PATH
) -> None:
    prefs = load(path)
    if model_name is None:
        prefs.pop("live2d_active_model", None)
    else:
        prefs["live2d_active_model"] = model_name
    save(prefs, path)


def get_local_backend(path: Path = DEFAULT_PATH) -> dict[str, str]:
    """Returns the user's local-backend overrides (LM Studio / Ollama /
    llama.cpp server endpoint). Schema: {base_url, model, api_key}.
    Empty dict = use config.yaml defaults."""
    val = load(path).get("local_backend") or {}
    return val if isinstance(val, dict) else {}


def set_local_backend(
    base_url: str = "",
    model: str = "",
    api_key: str = "",
    path: Path = DEFAULT_PATH,
) -> None:
    """Persist local-backend endpoint settings. Pass empty strings to clear
    individual fields (the example fallback will then apply)."""
    prefs = load(path)
    overrides: dict[str, str] = {}
    if base_url:
        overrides["base_url"] = base_url
    if model:
        overrides["model"] = model
    if api_key:
        overrides["api_key"] = api_key
    if overrides:
        prefs["local_backend"] = overrides
    else:
        prefs.pop("local_backend", None)
    save(prefs, path)


def get_voice_overrides(path: Path = DEFAULT_PATH) -> dict[str, Any]:
    """User edits to the voice section (backend selection + edge-tts /
    gpt-sovits parameters). Returned dict is shallow-merged into
    cfg['voice'] at startup so the user's UI choices win over
    config.example.yaml defaults without touching config.yaml comments.

    Schema (all keys optional):
      backend: 'edge-tts' | 'gpt-sovits'
      edge_tts: { voice, rate, pitch, volume }
      sovits: { base_url, ref_audio, ref_text, ref_lang, text_lang, ... }
    """
    val = load(path).get("voice_overrides") or {}
    return val if isinstance(val, dict) else {}


def set_voice_overrides(overrides: dict[str, Any], path: Path = DEFAULT_PATH) -> None:
    prefs = load(path)
    if not overrides:
        prefs.pop("voice_overrides", None)
    else:
        prefs["voice_overrides"] = overrides
    save(prefs, path)
