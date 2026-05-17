# desktop-kanojo

[![CI](https://github.com/lshhhhhhh/desktop-kanojo/actions/workflows/ci.yml/badge.svg)](https://github.com/lshhhhhhh/desktop-kanojo/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/lshhhhhhh/desktop-kanojo?include_prereleases&sort=semver)](https://github.com/lshhhhhhh/desktop-kanojo/releases/latest)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

[English version below](#english) · [中文版本](#中文)

![desktop-kanojo screenshot — Live2D avatar overlaid on a CS2 game, proactively commenting on what's on screen](screenshot/1.jpg)

---

## 中文

一个开源的桌面 AI 伴侣：透明置顶的 Live2D 形象，用云端或本地 LLM 跟她聊天，
她记得你聊过的事；可以让她偷瞄屏幕在合适的时候主动开口；用克隆的声音说话。

> 默认人设是「妹妹」，但人设完全可改——就是一个 YAML 文件。

### 特性

- **Live2D 形象** —— 任意 Cubism 4 模型即插即用，自动识别嘴部/表情参数，情绪到表情有衰减映射。
- **分层记忆** —— 工作窗口 (L1) + 向量检索的对话片段 (L2) + LLM 提炼出的事实（带矛盾链, L3）。用 SQLite + [`sqlite-vec`](https://github.com/asg017/sqlite-vec) 持久化。
- **任意 OpenAI 兼容后端** —— 智谱 / OpenAI / Gemini / LM Studio / Ollama / vLLM / llama.cpp（全部 OpenAI 兼容端点） 都能直接接。不同任务（聊天 / 反思 / 视觉）可路由到不同后端。
- **语音** —— 默认 [edge-tts](https://github.com/rany2/edge-tts)（免费、即开即用），可切换到本地 [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) 跑克隆声音。流式 PCM 播放走 `QAudioSink`，与 WebView 的 Chromium 音频栈兼容。
- **主动模式** —— 定时偷瞄屏幕评估"现在值不值得开口"，默认偏静默。
- **无边框透明窗** —— 顶部拖拽栏、设置弹窗、按设备的音频输出路由、隐私拦截红字、闭眼按钮。

### 下载预编译版（推荐）

去 [Releases](https://github.com/lshhhhhhh/desktop-kanojo/releases/latest) 下载最新 zip → 解压到你可写的目录（桌面 / D 盘根目录 / 文档，**不要解压到 `C:\Program Files\`**）→ 双击 `desktop-kanojo.exe`。**无需装 Python**。

首次运行 Windows Defender 会弹"未识别的发布者"——hobby 项目没买代码签名证书。点 **更多信息** → **仍要运行** 即可。

### 从源码运行（开发者）

两步——零配置，国内可用。

#### 1. 安装并启动

```powershell
git clone https://github.com/lshhhhhhh/desktop-kanojo.git
cd desktop-kanojo
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[voice]"
python -m app.main
```

需要 **Python 3.11+**。不需要 `copy .env`、不需要 `copy config.yaml`——app 找不到这些文件时自动用内置默认配置。

#### 2. 跟着首启动向导走

第一次启动弹两个对话框：

- **缺 API key** → 默认后端是 [智谱 GLM-4V-Flash](https://www.bigmodel.cn/apikey/platform)（国内可访问、免费、多模态）。点「去注册页拿 key」→ 浏览器打开智谱开放平台 → 注册后复制 key 回到 app 的「设置 → 模型」tab 粘贴。**整套流程 2 分钟**。
- **缺 Live2D 模型** → 点「打开 Live2D 下载页」→ 在
  [Live2D 官方 sample 页](https://www.live2d.com/en/learn/sample/) 挑一个 sample 下载 zip（推荐带表情的 **Mark** 或 **Haru**），回到 app 点「选择已下载的 zip」→ app 自动解压、生成配置、提示重启。
- 装完模型后到「设置 → 形象」tab 把情绪绑到模型实际的表情/动作上。

之后再启动就直接 `python -m app.main`。

**声音**：默认 [edge-tts](https://github.com/rany2/edge-tts)（微软 Azure 的免费 TTS，无需 key、即开即用）。想用克隆声音见下方"声音克隆"。

**记忆 / 截屏感知**：聊天记忆默认就跑，会持久化到 `data/memory.sqlite`。截屏主动模式默认开着，10 分钟评估一次，跟聊天用同一个智谱 key。

无 GUI 命令行模式（适合调试记忆 / 人设）：
```powershell
desktop-kanojo-repl
```

REPL 内命令：`/facts` `/recent` `/search <q>` `/reflect` `/clear`。

### Live2D 模型授权

Live2D 官方 sample 模型在
[Live2D Free Material License Agreement](https://www.live2d.com/eula/live2d-free-material-license-agreement_en.html)
下提供，对个人和小型商业用户（年收入 < 1000 万日元 / ~$70K USD）免费可商用。
本仓库**不打包也不自动下载**任何 Live2D 模型——下载这一步你自己去官网做，
app 只负责解压你提供的 zip。如果你的商业规模超过上述阈值，需要购买
[Live2D 商业授权](https://www.live2d.com/en/sdk/license/)。

### 声音克隆（可选）

默认走 edge-tts。想用克隆声音，单独装
[GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)，用 ~30 分钟干净音频训一个声音，
把 `voice.backend` 切到 `gpt-sovits`。完整流程见
[docs/sovits-training.md](docs/sovits-training.md)。

### 平台支持

- **Windows 11** —— 主力开发平台，所有特性都在这里测过。
- **macOS / Linux** —— Python 代码本身是跨平台的（PySide6 / qasync / sqlite-vec / httpx 都支持），但截屏（`core/perception/win32.py`）和 GPT-SoVITS 训练流程含 Windows 特定代码。聊天 + 记忆 + Live2D + 语音播放这条链路理论可跨平台，没有端到端验证过。欢迎在 issues 反馈。

### 状态

早期项目。东西在动，还没有 1.0。聊天 + 记忆 + 语音 + Live2D + 屏幕感知主动模式
这条主路径已经端到端可用。

### 贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。bug 报告和 PR 都欢迎。

### 协议

Apache-2.0，详见 [LICENSE](LICENSE)。

---

## English

An open-source desktop AI companion: a transparent, always-on-top Live2D
avatar that you can chat with via LLMs (cloud or local), remembers what you
told her across sessions, optionally watches your screen to talk
proactively, and speaks back with a cloned voice.

> Originally built around an "imouto" (younger-sister) persona, but the
> persona is fully editable — it's just a YAML file.

### Features

- **Live2D avatar** — drop in any Cubism 4 model; auto-detected mouth/expression params, decay-based emotion display.
- **Layered memory** — working window (L1) → episodic store with vector recall (L2) → LLM-distilled facts with contradiction chains (L3). Persists in SQLite via [`sqlite-vec`](https://github.com/asg017/sqlite-vec).
- **Any OpenAI-compatible backend** — Zhipu, OpenAI, Gemini, LM Studio, Ollama, vLLM, llama.cpp (all OpenAI-compatible endpoints) server. Route different tasks (chat / reflection / vision) to different backends.
- **Voice** — Microsoft [edge-tts](https://github.com/rany2/edge-tts) out of the box; switch to local [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) for cloned voices. Streaming low-latency PCM playback via `QAudioSink` (zero PortAudio conflicts with the embedded Chromium).
- **Proactive mode** — periodic screen-aware checks. She decides whether to speak up, biased toward silence unless something's actually worth saying.
- **Frameless transparent window** — drag-handle title bar, settings dialog, per-device audio output routing, privacy blocklist with visible red indicator, manual "close her eyes" toggle.

### Prebuilt download (recommended)

Grab the latest zip from [Releases](https://github.com/lshhhhhhh/desktop-kanojo/releases/latest), unpack into a user-writable directory (Desktop / D:\ root / Documents — **not** `C:\Program Files\`), and double-click `desktop-kanojo.exe`. **No Python install needed.**

On first run Windows Defender will warn about an "unrecognized publisher" — this is a hobby project without a code-signing cert. Click **More info** → **Run anyway**.

### From source (developers)

Two steps — zero config required.

#### 1. Install and launch

```powershell
git clone https://github.com/lshhhhhhh/desktop-kanojo.git
cd desktop-kanojo
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[voice]"
python -m app.main
```

Requires **Python 3.11+**. No need to copy `.env` or `config.yaml` — when the
app doesn't find them it falls back to the built-in defaults.

#### 2. Follow the first-run wizard

Two prompts on first launch:

- **Missing API key** → the default backend is **Zhipu GLM-4V-Flash**
  ([bigmodel.cn](https://www.bigmodel.cn/apikey/platform) — free, multimodal,
  accessible from mainland China). Click "去注册页拿 key" to open the
  registration page in your browser, then paste the key into the model
  tab. International users can also use OpenAI or Gemini — see the
  model tab for all options.
- **Missing Live2D model** → click "打开 Live2D 下载页", pick a sample
  from [Live2D's official page](https://www.live2d.com/en/learn/sample/)
  (recommend **Mark** or **Haru** — they have expression data), download
  the zip, then come back and click "选择已下载的 zip". The app unpacks
  it, generates the imouto.yaml sidecar, and offers to restart.
- After install, go to **Settings → 形象** tab to bind the emotion
  vocabulary to your model's actual expressions / motions.

After that, just `python -m app.main` to launch normally.

**Voice** defaults to [edge-tts](https://github.com/rany2/edge-tts)
(Microsoft Azure free TTS, no key needed). For cloned voices see below.

**Vision / proactive screen-awareness**: GLM-4V-Flash handles both
chat and vision with the same key. International users can also point
the `vision` route at OpenAI / Gemini in `config.yaml`.

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

### Voice cloning (optional)

Out of the box she uses edge-tts. For a custom cloned voice, install
[GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) separately, train a
voice on ~30 min of clean audio, and switch the `voice.backend` to
`gpt-sovits`. End-to-end walkthrough in [docs/sovits-training.md](docs/sovits-training.md).

### Architecture

```
app/                  Qt window, settings dialog, lifecycle
  ├── main.py
  ├── window.py
  └── settings_dialog.py

core/
  ├── brain/          LLM backends (openai_compat) + Router (per-task routing)
  ├── memory/         L1/L2/L3 + reflection + retrieval composer
  ├── voice/          TTS backends (edge-tts, gpt-sovits) + QAudioSink playback
  ├── perception/     screen capture + proactive observer + privacy guard
  ├── persona.py      persona load/save + prompt assembly
  ├── live2d_config.py  model-folder sidecar (imouto.yaml) loader
  ├── live2d_installer.py  first-run zip → installed model
  ├── preferences.py  per-user runtime prefs (audio device, active model, etc.)
  └── session.py      ChatSession glue (brain × memory × persona)

live2d/               WebView + Cubism JS libs; models/ is user-supplied
personas/             persona YAML files
tools/                training, REPL, model import, smoke tests
docs/                 long-form guides
```

The brain dispatches per-task: chat / reflection / vision / privacy_strict
each routes to a configurable backend, so you can use a cheap free-tier
model for fact extraction and a premium one for chat without changing code.

### Platform support

- **Windows 11** — primary development target, all features tested here.
- **macOS / Linux** — the Python codebase is portable (PySide6,
  qasync, sqlite-vec, httpx all support all three), but screen capture
  (`core/perception/win32.py`) and the GPT-SoVITS training pipeline
  contain Windows-specific bits. The chat + memory + Live2D + voice
  *playback* path should work cross-platform; we just haven't verified
  it end-to-end. Reports welcome via issues.

### Status

Early. Things move; not yet 1.0. The core loop (chat + memory + voice +
Live2D + screen-aware proactive) works end-to-end.

### Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports and PRs welcome.

### License

Apache-2.0. See [LICENSE](LICENSE).
