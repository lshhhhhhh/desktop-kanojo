# desktop-kanojo

[![CI](https://github.com/lshhhhhhh/desktop-kanojo/actions/workflows/ci.yml/badge.svg)](https://github.com/lshhhhhhh/desktop-kanojo/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

An open-source desktop AI companion: a transparent, always-on-top Live2D
avatar that you can chat with via LLMs (cloud or local), remembers what you
told her across sessions, optionally watches your screen to talk
proactively, and speaks back with a cloned voice.

![desktop-kanojo screenshot — Live2D avatar overlaid on a CS2 game, proactively commenting on what's on screen](screenshot/1.jpg)

> Originally built around an "imouto" (younger-sister) persona, but the
> persona is fully editable — it's just a YAML file.

## Features

- **Live2D avatar** — drop in any Cubism 4 model; auto-detected mouth/expression params, decay-based emotion display.
- **Layered memory** — working window (L1) → episodic store with vector recall (L2) → LLM-distilled facts with contradiction chains (L3). Persists in SQLite via [`sqlite-vec`](https://github.com/asg017/sqlite-vec).
- **Any OpenAI-compatible backend** — OpenAI, Gemini (OpenAI-compat endpoint), DeepSeek, LM Studio, Ollama, vLLM, llama.cpp server. Route different tasks (chat / reflection / vision) to different backends.
- **Voice** — Microsoft [edge-tts](https://github.com/rany2/edge-tts) out of the box; switch to local [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) for cloned voices. Streaming low-latency PCM playback via `QAudioSink` (zero PortAudio conflicts with the embedded Chromium).
- **Proactive mode** — periodic screen-aware checks. She decides whether to speak up, biased toward silence unless something's actually worth saying.
- **Frameless transparent window** — drag-handle title bar, settings dialog, per-device audio output routing.

## Quickstart

Three steps. The app guides you through API key + Live2D model on first run.

### 1. Install

Requires **Python 3.11+** on Windows / macOS / Linux. PySide6 needs a desktop session.

```powershell
git clone https://github.com/lshhhhhhh/desktop-kanojo.git
cd desktop-kanojo
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[voice]"
```

### 2. Configure

```powershell
copy .env.example .env
copy config.example.yaml config.yaml
```

### 3. Run

```powershell
desktop-kanojo
# or:  python -m app.main
```

On first launch you'll see two prompts:

- **Missing API key** → click "打开设置", paste your key in the model tab.
  Gemini has a generous free tier — get one in 30 s at
  [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
- **Missing Live2D model** → click "打开 Live2D 下载页", pick any sample
  from [Live2D's official page](https://www.live2d.com/en/learn/sample/),
  download the zip, then come back and click "选择已下载的 zip". The app
  unpacks it, generates the imouto.yaml sidecar, and restarts so she
  appears.

After that, just `desktop-kanojo` to launch normally.

CLI-only mode (no GUI, no voice) for headless testing:
```powershell
desktop-kanojo-repl
```

Commands inside the REPL: `/facts` `/recent` `/search <q>` `/reflect` `/clear`.

### Live2D licensing

Sample models on Live2D's site are free for personal use and for
commercial use by individuals and small businesses (annual revenue
< 10 million JPY / ~$70K USD) under the
[Live2D Free Material License Agreement](https://www.live2d.com/eula/live2d-free-material-license-agreement_en.html).
The app neither bundles nor auto-downloads any model — you download from
Live2D's site yourself, and the app just unpacks the zip you provide.
For commercial use beyond that revenue threshold, see
[Live2D's commercial licensing](https://www.live2d.com/en/sdk/license/).

## Voice cloning (optional)

Out of the box she uses edge-tts. For a custom cloned voice, install
[GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) separately, train a
voice on ~30 min of clean audio, and switch the `voice.backend` to
`gpt-sovits`. End-to-end walkthrough in [docs/sovits-training.md](docs/sovits-training.md).

## Architecture

```
app/                  Qt window, settings dialog, lifecycle
  ├── main.py
  ├── window.py
  └── settings_dialog.py

core/
  ├── brain/          LLM backends (openai_compat) + Router (per-task routing)
  ├── memory/         L1/L2/L3 + reflection + retrieval composer
  ├── voice/          TTS backends (edge-tts, gpt-sovits) + QAudioSink playback
  ├── perception/     screen capture + proactive observer
  ├── persona.py      persona load/save + prompt assembly
  ├── live2d_config.py  model-folder sidecar (imouto.yaml) loader
  ├── preferences.py  per-user runtime prefs (audio device, etc.)
  └── session.py      ChatSession glue (brain × memory × persona)

live2d/               WebView + Cubism JS libs; models/ is user-supplied
personas/             persona YAML files
tools/                training, REPL, model import, smoke tests
docs/                 long-form guides
```

The brain dispatches per-task: chat / reflection / vision / privacy_strict
each routes to a configurable backend, so you can use a cheap free-tier
model for fact extraction and a premium one for chat without changing code.

## Platform support

- **Windows 11** — primary development target, all features tested here.
- **macOS / Linux** — the Python codebase is portable (PySide6,
  qasync, sqlite-vec, httpx all support all three), but screen capture
  (`core/perception/win32.py`) and the GPT-SoVITS training pipeline
  contain Windows-specific bits. The chat + memory + Live2D + voice
  *playback* path should work cross-platform; we just haven't verified
  it end-to-end. Reports welcome via issues.

## Status

Early. Things move; not yet 1.0. The core loop (chat + memory + voice +
Live2D + screen-aware proactive) works end-to-end.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports and PRs welcome.

## License

Apache-2.0. See `LICENSE`.
