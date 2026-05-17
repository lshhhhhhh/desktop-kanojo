"""Per-model Live2D sidecar config loader.

Each Live2D model directory under `live2d/models/<name>/` contains an
`imouto.yaml` sidecar describing how to render and animate that specific model
(model file, fit mode, lip-sync parameter, emotion→expression mapping).

This module is intentionally minimal so the rest of the app can stay agnostic
to which model is loaded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

# Used when a model has no sidecar — only meaningful as a last-resort fallback
# (most models should ship their own emotion_mapping).
DEFAULT_EMOTION_MAPPING: dict[str, str] = {
    "开心": "比耶",
    "兴奋": "比耶",
    "得意": "比耶",
    "高兴": "比耶",
    "笑": "比耶",
    "害羞": "脸红",
    "脸红": "脸红",
    "尴尬": "捂脸",
    "捂脸": "捂脸",
    "想躲": "捂脸",
    "无语": "黑脸",
    "翻白眼": "黑脸",
    "冷漠": "黑脸",
    "毒舌": "黑脸",
    "难过": "哭",
    "哭": "哭",
    "伤心": "哭",
    "沮丧": "哭",
    "震惊": "星星",
    "惊讶": "星星",
    "吃惊": "星星",
    "慌张": "流汗",
    "紧张": "流汗",
    "心虚": "流汗",
    "尬笑": "流汗",
}


@dataclass
class Live2DConfig:
    """Resolved per-model config plus the absolute path to its directory."""

    model_dir: Path                       # absolute path to live2d/models/<name>/
    model_file: str                       # e.g. "march 7th.model3.json"
    fit_mode: str = "portrait"            # "portrait" | "fit"
    lip_sync_param: str = "ParamMouthOpenY"
    emotion_mapping: dict[str, str] = field(default_factory=dict)
    expression_decay_seconds: float = 8.0  # 0 disables decay

    @property
    def model_url_path(self) -> str:
        """The model path relative to `live2d/index.html` for fetch()."""
        return f"models/{self.model_dir.name}/{self.model_file}"

    @classmethod
    def from_app_config(cls, app_cfg: dict[str, Any]) -> Live2DConfig:
        live2d_cfg = app_cfg.get("live2d") or {}
        active = live2d_cfg.get("active_model", "March_7th")
        base = Path("live2d/models") / active
        sidecar = base / "imouto.yaml"

        if not sidecar.exists():
            logger.warning(
                "live2d sidecar {} not found; using built-in defaults",
                sidecar,
            )
            data: dict[str, Any] = {}
        else:
            with sidecar.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

        return cls(
            model_dir=base.resolve(),
            model_file=str(data.get("model_file", "model.model3.json")),
            fit_mode=str(data.get("fit_mode", "portrait")),
            lip_sync_param=str(data.get("lip_sync_param", "ParamMouthOpenY")),
            emotion_mapping=dict(
                data.get("emotion_mapping") or DEFAULT_EMOTION_MAPPING
            ),
            expression_decay_seconds=float(
                live2d_cfg.get("expression_decay_seconds", 8.0)
            ),
        )
