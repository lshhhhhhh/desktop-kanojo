# Contributing to desktop-kanojo

Thanks for considering a contribution. This is an early-stage hobby
project — issues, PRs, and design suggestions are all welcome.

## Quickstart

```bash
git clone https://github.com/lshhhhhhh/desktop-kanojo.git
cd desktop-kanojo
python -m venv .venv
# Windows
.\.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev,voice]"
cp .env.example .env          # then add at least one API key
cp config.example.yaml config.yaml
```

Run the app:
```bash
python -m app.main
```

Run the CLI REPL (no GUI, faster iteration on memory/persona):
```bash
python -m tools.repl
```

## Before opening a PR

```bash
ruff check .
pytest -v
```

Both should pass. Tests that hit live LLM APIs (`tests/test_e2e.py`)
self-skip when `GEMINI_API_KEY` is not set, so you can iterate without
network or API keys for the unit suite.

## Code style

- Python 3.11+; type hints on new code (we don't enforce mypy yet but
  prefer typed signatures).
- `ruff` config in `pyproject.toml` is authoritative.
- Comments only when the *why* is non-obvious. Don't restate what the
  code does — name things well instead.
- No emojis in code unless the user-facing string already uses them.

## Project layout

See `README.md` for a top-level diagram. Key entry points:

- `app/window.py` — the Qt window, settings dialog wiring, lifecycle.
- `core/session.py` — `ChatSession` glues brain + memory + persona.
- `core/brain/router.py` — per-intent backend routing.
- `core/memory/store.py` — the `MemoryStore` façade over L1/L2/L3.
- `core/voice/speaker.py` — sentence-queued playback driving Live2D
  mouth via the envelope callback.

## Adding an LLM backend

Implement `core.brain.base.LLMBackend` and register a provider name in
`core.brain.router.Router.from_config`. Most providers are
OpenAI-compatible — try the existing `openai_compat` first.

## Adding a TTS backend

Implement `core.voice.base.TTSBackend` and register in
`core.voice.base.TTSBackend.from_config`. PCM must be int16 mono; the
sample rate can vary per chunk (the player reconfigures per sentence).

## Reporting bugs

Please include:
- Your OS + Python version.
- The exact traceback (or the log lines around the failure).
- Whether it reproduces with the example config + a fresh `data/` dir
  (delete `data/*.sqlite` to reset memory).

## License

By contributing you agree that your contribution will be licensed under
Apache-2.0, the same license as the rest of the project.
