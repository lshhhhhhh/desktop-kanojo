"""Read / write the emotion → expression+motion bindings in imouto.yaml.

Replaces the heuristic auto-binding done at install time with explicit
user-driven choices made via the settings dialog. Heuristic stays as the
initial defaults; this module lets the user override them and saves the
result back to the per-model sidecar so the choice persists.

The sidecar is rewritten in a stable, predictable shape (see _format_yaml).
Pre-existing user comments are not preserved — the trade-off is that the
saved file is deterministic and easy to diff.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

# The canonical emotion vocabulary the persona prompt asks the LLM to use.
# Other emotions can still be added by hand-editing imouto.yaml; the binding
# UI just exposes this default set.
STANDARD_EMOTIONS = [
    "开心", "害羞", "无语", "难过", "慌张",
    "震惊", "尴尬", "生气", "得意",
]


@dataclass
class MotionRef:
    group: str
    index: int

    def as_dict(self) -> dict[str, Any]:
        return {"group": self.group, "index": self.index}

    def label(self) -> str:
        return f"[动作] {self.group}#{self.index}"


@dataclass
class ModelBindings:
    """Everything the settings UI needs about a model's available reactions
    + the current emotion→reaction wiring."""

    model_dir: Path
    expressions: list[str]                          # expression names
    motions: list[MotionRef]                        # available (group, index)
    emotion_to_expression: dict[str, str]           # current mapping
    emotion_to_motion: dict[str, MotionRef]         # current mapping (fallback)
    raw_sidecar: dict[str, Any]                     # everything else, preserved

    @property
    def sidecar_path(self) -> Path:
        return self.model_dir / "imouto.yaml"


def load_bindings(model_dir: Path) -> ModelBindings:
    """Inspect the model directory + sidecar, return the merged view.

    `expressions` comes from the model3.json's FileReferences.Expressions,
    so the dropdown only ever shows names the engine actually knows about.
    Same for `motions` (FileReferences.Motions).
    """
    sidecar_path = model_dir / "imouto.yaml"
    raw: dict[str, Any] = {}
    if sidecar_path.exists():
        try:
            with sidecar_path.open("r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning("failed to parse {}: {}", sidecar_path, e)

    model3_name = raw.get("model_file") or _find_model3_name(model_dir) or ""
    expressions: list[str] = []
    motions: list[MotionRef] = []
    model3_path = model_dir / model3_name
    if model3_path.is_file():
        try:
            with model3_path.open("r", encoding="utf-8") as f:
                model3 = json.load(f)
            fr = model3.get("FileReferences") or {}
            for e in fr.get("Expressions") or []:
                name = e.get("Name")
                if name:
                    expressions.append(name)
            for group, entries in (fr.get("Motions") or {}).items():
                for i in range(len(entries)):
                    motions.append(MotionRef(group=group, index=i))
        except Exception as e:
            logger.warning("failed to parse {}: {}", model3_path, e)

    emo_expr = dict(raw.get("emotion_mapping") or {})
    emo_motion: dict[str, MotionRef] = {}
    for emo, m in (raw.get("motion_mapping") or {}).items():
        if isinstance(m, dict) and "group" in m:
            emo_motion[emo] = MotionRef(group=str(m["group"]), index=int(m.get("index", 0)))

    return ModelBindings(
        model_dir=model_dir,
        expressions=expressions,
        motions=motions,
        emotion_to_expression=emo_expr,
        emotion_to_motion=emo_motion,
        raw_sidecar=raw,
    )


def save_bindings(b: ModelBindings) -> None:
    """Write the updated sidecar. Keeps all other top-level fields
    (model_file, fit_mode, lip_sync_param, expression_decay_seconds) as
    they were."""
    out = dict(b.raw_sidecar)
    out["emotion_mapping"] = dict(b.emotion_to_expression)
    out["motion_mapping"] = {
        emo: m.as_dict() for emo, m in b.emotion_to_motion.items()
    }
    text = _format_yaml(out)
    b.sidecar_path.write_text(text, encoding="utf-8")
    logger.info("live2d_binding: saved {}", b.sidecar_path)


def _format_yaml(data: dict[str, Any]) -> str:
    """Emit a predictable shape: scalar fields first, then mappings, with
    one blank line between sections. Avoids yaml.dump's anchors / flow
    style surprises and is round-trip-safe with safe_load."""
    scalar_keys = ["model_file", "fit_mode", "lip_sync_param",
                   "expression_decay_seconds"]
    lines = ["# Edited by the settings dialog — feel free to hand-tune."]
    for k in scalar_keys:
        if k in data:
            lines.append(f"{k}: {_yaml_scalar(data[k])}")
    if any(k in data for k in scalar_keys):
        lines.append("")

    lines.append("emotion_mapping:")
    emap = data.get("emotion_mapping") or {}
    if emap:
        for k, v in emap.items():
            lines.append(f"  {_yaml_scalar(k)}: {_yaml_scalar(v)}")
    else:
        lines.append("  {}")
    lines.append("")

    lines.append("motion_mapping:")
    mmap = data.get("motion_mapping") or {}
    if mmap:
        for k, v in mmap.items():
            grp = _yaml_scalar(v.get("group", ""))
            idx = int(v.get("index", 0))
            lines.append(f"  {_yaml_scalar(k)}: {{ group: {grp}, index: {idx} }}")
    else:
        lines.append("  {}")
    return "\n".join(lines) + "\n"


def _yaml_scalar(value: Any) -> str:
    """Quote strings that need it (contain : / # / leading-whitespace / etc.),
    pass numbers/bools as-is, and avoid yaml.dump pulling in flow style."""
    if isinstance(value, str):
        # Always quote — keeps Chinese keys + reserved-character values safe.
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _find_model3_name(model_dir: Path) -> str | None:
    for p in model_dir.glob("*.model3.json"):
        return p.name
    return None
