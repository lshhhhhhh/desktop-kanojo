"""Safe in-place editor for `.env` files.

The UI lets users set API keys from inside the app. We need to write them to
`.env` without nuking the user's other lines (comments, unrelated keys, etc.).
`python-dotenv`'s built-in writer doesn't preserve formatting reliably, so we
roll a minimal upsert that touches only the target line.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

DEFAULT_ENV_PATH = Path(".env")

_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")


# Where each provider's API key console lives, with a short blurb for the UI.
# Used by both the first-run wizard and the model settings tab — single
# source of truth so we don't drift between the two surfaces.
KEY_SOURCES: dict[str, tuple[str, str]] = {
    "DEEPSEEK_API_KEY": (
        "https://platform.deepseek.com/api_keys",
        "DeepSeek 在中国可访问，注册送免费额度",
    ),
    "ZHIPU_API_KEY": (
        "https://www.bigmodel.cn/usercenter/proj-mgmt/apikeys",
        "智谱 GLM-4V-Flash 免费多模态，中国可访问",
    ),
    "DASHSCOPE_API_KEY": (
        "https://bailian.console.aliyun.com/",
        "阿里百炼（Qwen-VL），新用户送 quota，中国可访问",
    ),
    "OPENAI_API_KEY": (
        "https://platform.openai.com/api-keys",
        "OpenAI（需国际网络）",
    ),
    "GEMINI_API_KEY": (
        "https://aistudio.google.com/apikey",
        "Google AI Studio，免费额度充足（需国际网络）",
    ),
    "ANTHROPIC_API_KEY": (
        "https://console.anthropic.com/",
        "Anthropic Claude（需国际网络）",
    ),
}


def read_env_value(name: str, path: Path = DEFAULT_ENV_PATH) -> str | None:
    """Return the value for `name` from the .env file, or None if missing.
    Honors quoted values; does not consult os.environ."""
    if not path.exists():
        return None
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = _LINE_RE.match(raw)
        if not m or m.group(1) != name:
            continue
        val = raw.split("=", 1)[1].strip()
        # strip optional surrounding quotes
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        return val
    return None


def has_env_value(name: str, path: Path = DEFAULT_ENV_PATH) -> bool:
    """True if `name` is set either in the .env file or in os.environ."""
    if os.environ.get(name):
        return True
    val = read_env_value(name, path)
    return val is not None and val != ""


def upsert_env_value(
    name: str,
    value: str,
    path: Path = DEFAULT_ENV_PATH,
    *,
    also_set_process_env: bool = True,
) -> None:
    """Set `name=value` in the .env file, replacing the existing line if
    present or appending if not. Leaves every other line untouched.

    Values that contain whitespace or quotes are written with double-quote
    wrapping and minimal backslash escaping. Empty value clears the line
    contents but keeps the key (writing `KEY=`).

    If `also_set_process_env` is true (default), also updates os.environ so
    the change takes effect for any code that re-reads the env later in this
    process — though note that already-constructed backends will have cached
    the old key.
    """
    if not _LINE_RE.match(f"{name}="):
        raise ValueError(f"invalid env var name: {name!r}")

    if any(c in value for c in (" ", "\t", '"', "'", "#", "\\")):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        formatted = f'"{escaped}"'
    else:
        formatted = value
    new_line = f"{name}={formatted}"

    lines: list[str] = []
    replaced = False
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            m = _LINE_RE.match(raw)
            if m and m.group(1) == name:
                lines.append(new_line)
                replaced = True
            else:
                lines.append(raw)
    if not replaced:
        lines.append(new_line)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if also_set_process_env:
        os.environ[name] = value


def collect_required_env_keys(cfg: dict) -> list[str]:
    """Walk the config and return a de-duplicated, source-ordered list of
    every `api_key_env: NAME` mentioned. Used to drive the settings UI's
    "which keys does this config want" list."""
    seen: list[str] = []

    def visit(node) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "api_key_env" and isinstance(v, str) and v not in seen:
                    seen.append(v)
                visit(v)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(cfg)
    return seen
