"""Inspect a Live2D model directory and generate the imouto wiring.

Usage:
    python tools/import_live2d.py [--dry-run] [--force] <model_dir>

What it does:
    1. Locates *.model3.json, *.vtube.json, *.cdi3.json in the directory.
    2. If model3.json is missing the Expressions block, populates it from
       *.exp3.json files in the directory + subdirs. Names come from
       vtube.json's Hotkeys when available, else from the filename.
    3. If LipSync ids are empty, fills with ParamMouthOpenY (or whatever
       mouth-open param is found in cdi3.json).
    4. Writes a stub imouto.yaml (skips if one already exists, unless --force).
       Heuristic emotion_mapping based on Chinese keyword matching against
       expression names.

The original model3.json is backed up to model3.json.bak before any change.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

# Keyword → canonical emotion. The expression name is matched against these
# substrings to suggest a stub emotion_mapping entry.
KEYWORD_TO_EMOTION = [
    (re.compile(r"开心|笑|喜|乐|蹦|嬉|高兴|得意|兴奋|得意|比耶"), "开心"),
    (re.compile(r"害羞|羞|脸红|腼腆|不好意思"), "害羞"),
    (re.compile(r"无语|翻白眼|冷漠|淡定|嫌|黑脸|不耐|暗"), "无语"),
    (re.compile(r"难过|哭|泣|伤心|沮丧|郁闷"), "难过"),
    (re.compile(r"慌|急|汗|尬笑|心虚|窘"), "慌张"),
    (re.compile(r"震惊|惊讶|吃惊|星星|星|惊|愣"), "震惊"),
    (re.compile(r"尴尬|捂脸|捂|糟"), "尴尬"),
    (re.compile(r"生气|怒|愤|气"), "生气"),
]

# Expression names that look like NON-emotion (props, outfits, hair, etc.)
NON_EMOTION_PATTERN = re.compile(
    r"发型|衣服|外套|帽子|眼镜|话筒|麦克风|枕头|包|相机|套|配饰|装备"
)


def _find_one(folder: Path, suffix: str) -> Path | None:
    matches = list(folder.glob(f"*{suffix}"))
    if not matches:
        return None
    if len(matches) > 1:
        print(f"  multiple {suffix} candidates, using first: {matches[0].name}")
    return matches[0]


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _extract_vtube_hotkeys(vtube: dict | None) -> dict[str, str]:
    """Map exp3.json filename → user-facing Name from vtube.json Hotkeys."""
    out: dict[str, str] = {}
    if not vtube:
        return out
    for h in vtube.get("Hotkeys", []) or []:
        if h.get("Action") != "ToggleExpression":
            continue
        fname = h.get("File")
        name = (h.get("Name") or "").strip()
        if fname and name:
            out[fname] = name
    return out


def _detect_mouth_param(cdi: dict | None) -> str:
    """Inspect cdi3.json and pick the best mouth-open parameter id."""
    if not cdi:
        return "ParamMouthOpenY"
    candidates = []
    for p in cdi.get("Parameters", []) or []:
        pid = p.get("Id", "")
        if "MouthOpen" in pid or pid in ("ParamMouth", "PARAM_MOUTH_OPEN_Y"):
            candidates.append(pid)
    # Prefer the canonical ParamMouthOpenY, else first match, else default.
    if "ParamMouthOpenY" in candidates:
        return "ParamMouthOpenY"
    if candidates:
        return candidates[0]
    return "ParamMouthOpenY"


def _natural_sort_key(p: Path) -> list:
    """Natural sort so expression2 < expression10."""
    parts = re.split(r"(\d+)", p.name)
    return [int(s) if s.isdigit() else s.lower() for s in parts]


def _list_expression_files(folder: Path) -> list[Path]:
    return sorted(folder.rglob("*.exp3.json"), key=_natural_sort_key)


def _suggest_emotion(expr_name: str) -> str | None:
    if NON_EMOTION_PATTERN.search(expr_name):
        return None
    for rx, emo in KEYWORD_TO_EMOTION:
        if rx.search(expr_name):
            return emo
    return None


def _patch_model3(
    model3_path: Path,
    expression_entries: list[dict],
    mouth_param: str,
    dry_run: bool,
) -> bool:
    data = _read_json(model3_path) or {}
    fr = data.setdefault("FileReferences", {})
    groups = data.setdefault("Groups", [])
    changed = False

    if "Expressions" not in fr and expression_entries:
        fr["Expressions"] = expression_entries
        print(f"  + add Expressions: {len(expression_entries)} entries")
        changed = True

    # Ensure a LipSync group with at least one id
    lipsync = next(
        (g for g in groups if g.get("Name") == "LipSync"), None
    )
    if lipsync is None:
        groups.append({
            "Target": "Parameter",
            "Name": "LipSync",
            "Ids": [mouth_param],
        })
        print(f"  + add LipSync Ids: [{mouth_param}]")
        changed = True
    elif not lipsync.get("Ids"):
        lipsync["Ids"] = [mouth_param]
        print(f"  + fill LipSync Ids: [{mouth_param}]")
        changed = True

    if not changed:
        print("  - model3.json already has Expressions + LipSync (no change)")
        return False

    if dry_run:
        print("  [dry-run] would write:")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:800])
        return False

    backup = model3_path.with_suffix(model3_path.suffix + ".bak")
    if not backup.exists():
        shutil.copy2(model3_path, backup)
        print(f"  ↳ backup: {backup.name}")
    with model3_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"  ✓ wrote {model3_path.name}")
    return True


def _write_sidecar(
    folder: Path,
    model3_path: Path,
    mouth_param: str,
    expression_entries: list[dict],
    dry_run: bool,
    force: bool,
) -> bool:
    sidecar = folder / "imouto.yaml"
    if sidecar.exists() and not force:
        print("  - imouto.yaml already exists; pass --force to overwrite")
        return False

    # Build heuristic emotion_mapping
    suggestions: dict[str, str] = {}
    unmapped: list[str] = []
    for e in expression_entries:
        name = e["Name"]
        emo = _suggest_emotion(name)
        if emo:
            suggestions.setdefault(emo, name)
        else:
            unmapped.append(name)

    # Compose YAML by hand to keep ordering + comments readable
    lines = [
        "# Auto-generated by tools/import_live2d.py — review and tune.",
        "",
        f'model_file: "{model3_path.name}"',
        "fit_mode: portrait",
        f"lip_sync_param: {mouth_param}",
        "",
        "emotion_mapping:",
    ]
    if suggestions:
        for emo, expr in suggestions.items():
            lines.append(f"  {emo}: {expr}")
    else:
        lines.append("  # (no obvious matches — add manually)")

    if unmapped:
        lines.append("")
        lines.append("# Unmapped expressions (likely props / outfit toggles —")
        lines.append("# trigger explicitly via window.imouto.setExpression(...)):")
        for n in unmapped:
            lines.append(f"#   {n}")

    body = "\n".join(lines) + "\n"

    if dry_run:
        print("  [dry-run] would write imouto.yaml:")
        print("---")
        print(body)
        print("---")
        return False

    sidecar.write_text(body, encoding="utf-8")
    print(f"  ✓ wrote {sidecar.name}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("model_dir", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite existing imouto.yaml")
    args = ap.parse_args()

    folder: Path = args.model_dir
    if not folder.is_dir():
        print(f"error: {folder} is not a directory", file=sys.stderr)
        return 2

    print(f"== inspecting {folder} ==")

    model3 = _find_one(folder, ".model3.json")
    if model3 is None:
        print("error: no *.model3.json found", file=sys.stderr)
        return 2
    print(f"  model3:   {model3.name}")

    vtube = _read_json(_find_one(folder, ".vtube.json") or Path("/nonexistent"))
    cdi = _read_json(_find_one(folder, ".cdi3.json") or Path("/nonexistent"))
    name_map = _extract_vtube_hotkeys(vtube)
    mouth_param = _detect_mouth_param(cdi)
    print(f"  mouth:    {mouth_param}{' (from cdi3.json)' if cdi else ' (default)'}")
    print(f"  vtube:    {'found' if vtube else 'not found'}"
          f"{' — ' + str(len(name_map)) + ' named expressions' if name_map else ''}")

    exp_files = _list_expression_files(folder)
    print(f"  exp files: {len(exp_files)}")
    expression_entries: list[dict[str, Any]] = []
    for p in exp_files:
        rel = p.relative_to(folder).as_posix()
        # Some VTS exports list expressions by basename only;
        # match either form when looking up names.
        name = name_map.get(rel) or name_map.get(p.name) or p.stem
        expression_entries.append({"Name": name, "File": rel})

    print()
    _patch_model3(model3, expression_entries, mouth_param, args.dry_run)
    print()
    _write_sidecar(folder, model3, mouth_param, expression_entries,
                   args.dry_run, args.force)
    print()
    print("== done ==")
    if args.dry_run:
        print("(dry-run: nothing was written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
