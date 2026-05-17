# GPT-SoVITS Training & desktop-kanojo Integration

End-to-end walkthrough: prepare audio data → train a custom voice → expose it
as an HTTP API → switch the app's TTS backend to use it.

> **Prereqs.** Clone [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)
> *outside* this repo, follow its installer to set up a dedicated Python
> env, and download its base pretrained models (the installer prompts for
> them). Then export two env vars so this repo's helper scripts know where
> to find that install:
>
> ```powershell
> $env:GPT_SOVITS_DIR    = "C:\path\to\GPT-SoVITS"
> $env:GPT_SOVITS_PYTHON = "C:\path\to\GPT-SoVITS\env\python.exe"
> ```

---

## 1. Prepare your audio data

### Format 1: WAV + LAB pairs (game extracts typically look like this)

```
my_voice/
├── voice_001.wav    voice_001.lab    (contains: "今天天气真好")
├── voice_002.wav    voice_002.lab    (contains: "你又不来找我玩")
└── ...
```

Use `tools/prep_voice_dataset.py` to copy + generate a `.list` manifest from
this layout + report stats in one go:

```powershell
python tools\prep_voice_dataset.py `
  --src path\to\raw_clips `
  --dst path\to\voices\myvoice `
  --speaker myvoice `
  --lang zh
```

Outputs:
- `<dst>\` — copied wavs + labs
- `<dst>\data.list` — manifest ready for training
- printed stats: pair count, total/avg/median duration, distribution

### Format 2: hand-built `.list` manifest

If you have the data already, just write a manifest by hand:
```
path/to/voices/x/clip01.wav|speaker_name|zh|今天天气真好
path/to/voices/x/clip02.wav|speaker_name|zh|你又不来找我玩
...
```
Format: `<audio_path>|<speaker>|<lang>|<text>` per line, pipe-separated. Lang
codes: `zh` / `en` / `ja` / `ko` / `yue` (Cantonese). Absolute paths are
safest; relative paths are resolved against `--wav-dir` passed to training.

### Quality requirements

- **Total length**: 30 minutes is sweet spot. 5 min minimum, 2 h+ doesn't add much.
- **Audio**: 16 kHz–48 kHz mono WAV, no music/SFX overlap, no significant
  reverb. Game voice lines are usually perfect.
- **Clips**: 3–15 s each. Longer clips hurt training; shorter waste epochs.
- **Transcripts**: must match audio exactly. Punctuation matters
  (the model learns prosody from `。`/`，`/`！`).

---

## 2. Train: CLI (recommended) or webui

### CLI — one command, no clicking

`tools/sovits_train.py` replicates the entire webui pipeline as a single
Python script. It sets the same env vars and calls the same underlying
prepare + train scripts as Gradio would, but it's scriptable, reproducible,
and works headless.

```powershell
python tools\sovits_train.py `
  --name myvoice `
  --list-file path\to\voices\myvoice\data.list `
  --wav-dir   path\to\voices\myvoice
```

What it does end-to-end:
1. `1-get-text.py` — text → phonemes + BERT features
2. `2-get-hubert-wav32k.py` — audio → Hubert SSL features
3. `3-get-semantic.py` — SSL → semantic tokens
4. `s2_train_v3_lora.py` — SoVITS LoRA fine-tune
5. `s1_train.py` — GPT fine-tune

Defaults are tuned for a high-end GPU + ~30 min of data:
`--batch-size 12 --epochs-s2 8 --epochs-s1 15 --save-every 4`.
Lower `--batch-size` if you hit CUDA OOM.

Re-run safely with `--skip-prepare` if you only want to re-train, or with
`--skip-s2` / `--skip-s1` to redo just one half.

### Webui — alternative for visual tweaking

```powershell
Set-Location $env:GPT_SOVITS_DIR
.\go-webui.ps1
```

Opens a Gradio interface (usually http://127.0.0.1:9874). Useful for
tweaking hyperparameters live or inspecting intermediate features. The CLI
does the same job faster for the common case.

When training finishes you'll have two files under your GPT-SoVITS install:
- `SoVITS_weights_v4/<name>_eN_sM.pth`
- `GPT_weights_v4/<name>-eN.ckpt`

---

## 3. Launch the API server

```powershell
powershell -ExecutionPolicy Bypass -File tools\start_sovits_server.ps1
```

The launcher reads `$env:GPT_SOVITS_DIR` / `$env:GPT_SOVITS_PYTHON` /
`$env:GPT_SOVITS_CONFIG` (or pass `-Repo` / `-Python` / `-Config`). It binds
`http://127.0.0.1:9880`.

Health check:
```powershell
Invoke-RestMethod http://127.0.0.1:9880/
```

You can also bypass the launcher and call api_v2 directly with explicit
weights:

```powershell
& $env:GPT_SOVITS_PYTHON api_v2.py -a 127.0.0.1 -p 9880 `
  -s SoVITS_weights_v4\myvoice_e8_s256.pth `
  -g GPT_weights_v4\myvoice-e15.ckpt
```

Or swap models mid-session via the `/set_sovits_weights` and
`/set_gpt_weights` endpoints — useful for switching characters without
restarting.

---

## 4. Connect the app

Copy `config.example.yaml` → `config.yaml` and edit the `voice` block:

```yaml
voice:
  enabled: true
  backend: gpt-sovits
  sovits:
    base_url: http://127.0.0.1:9880
    ref_audio: "path/to/clean/reference.wav"   # 3–10 s clean clip
    ref_text: "对应的台词原文"                  # MUST match the audio exactly
    ref_lang: zh
    text_lang: zh
    sample_rate: 48000
    media_type: raw                            # streaming PCM, lowest latency
    streaming_mode: 3
    speed_factor: 1.0
    temperature: 1.0
    top_k: 5
```

Then launch the app:
```powershell
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe -m app.main
```

She should now speak in your trained voice. Live2D mouth sync is driven by
the RMS envelope of the PCM stream.

---

## 5. Troubleshooting

### `ref_audio_path doesn't exist`
The path in config must be readable by the SoVITS process. Absolute paths
with forward slashes are safest.

### Voice sounds robotic / static
- Reference audio has noise → pick a cleaner clip.
- Reference text doesn't match audio → fix the transcript.
- Try lower `temperature` (e.g. 0.7).

### Voice sounds nothing like the target
- Undertrained — run more epochs.
- Training data too varied (mixed speakers/styles got mixed in).

### CUDA OOM during training
- Lower `--batch-size` (try 4).
- Close other GPU-heavy apps while training.

### App is silent / laggy
- Hit `http://127.0.0.1:9880/tts` directly with curl to see if SoVITS itself
  is the bottleneck.
- Check `core/voice/sovits_backend.py` logs for HTTP errors.

### Re-train from scratch
```powershell
Remove-Item -Recurse -Force "$env:GPT_SOVITS_DIR\logs\<model_name>"
```
