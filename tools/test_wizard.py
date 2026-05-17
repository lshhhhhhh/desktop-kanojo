"""Launch the app in pristine first-run state, then restore on exit.

One command, runs the wizard end-to-end, automatically reverts everything.

Usage:
    python tools/test_wizard.py

What it does:
1. Hides your real .env, data/preferences.yaml, and installed Live2D models
   (renames them to *.wizard_hidden / live2d/models/<name>.wizard_hidden).
2. Clears API-key env vars in this process so dotenv-less loading also looks
   like a fresh install.
3. Runs `app.main.main()` inline. You see the wizard exactly as a new user
   would, can click through it, install a model, set a key, even chat.
4. When you close the window (or hit Ctrl+C), restores everything:
     - wipes anything the wizard wrote (new .env, new preferences, new model)
     - moves the hidden originals back into place
5. You're back to where you started.

Safe to interrupt — the cleanup is in a `finally` block.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Env vars to clear so the wizard's "missing key" check fires even when the
# user's shell already has them exported.
KEY_VARS = [
    "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
    "ANTHROPIC_API_KEY", "ZHIPU_API_KEY", "DASHSCOPE_API_KEY",
]

HIDDEN_SUFFIX = ".wizard_hidden"


def hide(path: Path) -> Path | None:
    """Rename `path` out of the way. Returns the backup path, or None if
    nothing to hide."""
    if not path.exists():
        return None
    bak = path.with_suffix(path.suffix + HIDDEN_SUFFIX)
    if bak.exists():
        # Stale backup from a previous interrupted run — keep it, don't clobber.
        print(f"warning: {bak} already exists; not hiding {path}")
        return None
    shutil.move(str(path), str(bak))
    return bak


def unhide(orig: Path, bak: Path | None) -> None:
    if bak is None or not bak.exists():
        return
    # Wipe anything created during pristine mode that would block restore.
    if orig.exists():
        if orig.is_dir():
            shutil.rmtree(orig)
        else:
            orig.unlink()
    shutil.move(str(bak), str(orig))


def main() -> int:
    os.chdir(REPO)

    env_bak = hide(REPO / ".env")
    prefs_bak = hide(REPO / "data" / "preferences.yaml")

    # Hide every installed model.
    models_dir = REPO / "live2d" / "models"
    hidden_models: list[tuple[Path, Path]] = []
    pre_existing_names: set[str] = set()
    if models_dir.exists():
        for item in list(models_dir.iterdir()):
            if not item.is_dir() or item.name in ("__pycache__",):
                continue
            bak = item.with_name(item.name + HIDDEN_SUFFIX)
            if bak.exists():
                continue
            shutil.move(str(item), str(bak))
            hidden_models.append((item, bak))
            pre_existing_names.add(item.name)

    for var in KEY_VARS:
        os.environ.pop(var, None)

    print(f"hidden: .env={env_bak is not None}, "
          f"prefs={prefs_bak is not None}, "
          f"models={[m[0].name for m in hidden_models]}")
    print()
    print(">>> launching app in pristine first-run state — close the window to restore <<<")
    print()

    try:
        from app.main import main as app_main
        app_main()
    finally:
        # Wipe anything the wizard wrote during this run.
        new_env = REPO / ".env"
        if env_bak is not None and new_env.exists():
            new_env.unlink()
            print("cleaned up wizard-created .env")
        new_prefs = REPO / "data" / "preferences.yaml"
        if prefs_bak is not None and new_prefs.exists():
            new_prefs.unlink()
            print("cleaned up wizard-created preferences.yaml")
        if models_dir.exists():
            for item in list(models_dir.iterdir()):
                if not item.is_dir() or item.name in ("__pycache__",):
                    continue
                if item.name.endswith(HIDDEN_SUFFIX):
                    continue
                if item.name not in pre_existing_names:
                    shutil.rmtree(item)
                    print(f"cleaned up wizard-installed model {item.name}")

        # Restore hidden originals.
        unhide(REPO / ".env", env_bak)
        unhide(REPO / "data" / "preferences.yaml", prefs_bak)
        for orig, bak in hidden_models:
            unhide(orig, bak)

        print("\nrestored. you're back to your real state.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
