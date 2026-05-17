# Live2D Model Integration Guide

This doc explains how to add or swap a Live2D model in imouto, and where the
model-specific assumptions live in the codebase. It's written for both future
contributors and the LLM agent that maintains this project.

---

## TL;DR — swap in a new model

```powershell
# 1. drop the model folder in
mv ~/Downloads/MyModelVTS  live2d/models/MyModel

# 2. let the import tool figure out the wiring
python tools/import_live2d.py live2d/models/MyModel

# 3. (optional) tweak the generated imouto.yaml — review the emotion_mapping
#    suggestions and add any extras your model has

# 4. point config at it
#    edit config.yaml:   live2d.active_model: MyModel

# 5. verify it loads (uses the active_model from config.example.yaml)
python tools/probe_live2d.py
```

`import_live2d.py` handles the boring parts:
- patches `model3.json` if `Expressions` / `LipSync.Ids` are missing
- pulls semantic expression names from `*.vtube.json` Hotkeys
- detects the mouth-open parameter from `*.cdi3.json`
- generates a stub `imouto.yaml` with heuristic emotion mapping

If the heuristic doesn't catch all your expressions, edit `imouto.yaml` by
hand using the reference below. **No Python edits required** to swap models.

---

## Architecture in one diagram

```
config.yaml
  └── live2d.active_model: "March_7th"
                │
                ▼
core/live2d_config.py  ──reads──▶  live2d/models/<active>/imouto.yaml
        │                                 ├── model_file
        │                                 ├── fit_mode
        │                                 ├── lip_sync_param
        │                                 └── emotion_mapping
        │
        ▼
app/window.py
  ├── live2d_cfg = Live2DConfig.from_app_config(cfg)
  ├── ─loads index.html with ?model=...&fit=...&mouth=...
  └── _trigger_emotion(emo) → emotion_mapping[emo] → JS setExpression()
                │
                ▼
live2d/index.html (QWebEngine)
  ├── reads URL query: modelPath, fitMode, mouthParamId
  ├── PIXI.live2d.Live2DModel.from(modelPath)
  ├── exposes window.imouto.{setExpression, setMouthOpen, ...}
  └── runs eye-tracking, hover-aware drag, fit/portrait layout
```

Three coupling points to a specific model:
1. **The model files themselves** under `live2d/models/<name>/`
2. **The sidecar** `imouto.yaml` next to those files
3. **Nothing else** — everything else is generic

---

## Required model3.json fields

The standard Cubism 4/5 model3.json must have:

| Field | Purpose | imouto requirement |
|---|---|---|
| `FileReferences.Moc` | core .moc3 file | required |
| `FileReferences.Textures` | texture PNGs | required |
| `FileReferences.Physics` | hair/cloth sway | optional but recommended |
| `FileReferences.Motions` | motion groups | needs at least one group (commonly "Idle") |
| `FileReferences.Expressions` | named expression list | needed if you want `emotion_mapping` to do anything |
| `Groups[].Name == "EyeBlink"` with `Ids` | auto blink | recommended for natural look |
| `Groups[].Name == "LipSync"` with `Ids: ["<MouthParam>"]` | TTS mouth sync | needed for future TTS, and the id must match `lip_sync_param` in sidecar |

If your model is missing Motions or LipSync ids, you'll have to edit the
model3.json by hand. See **Gotchas** below.

---

## Sidecar format: `imouto.yaml`

```yaml
# live2d/models/<name>/imouto.yaml

# Filename of the .model3.json inside this directory.
model_file: "march 7th.model3.json"

# How to scale the model in the window:
#   portrait — width-fill, top-anchored (for tall full-body VTS models)
#   fit     — contain entire model in canvas (for chibi / head-only models)
fit_mode: portrait

# Cubism parameter id that drives mouth-open for TTS lip sync.
# Look in your model's cdi3.json (DisplayInfo) or moc3 internals.
# Common ids: ParamMouthOpenY, ParamMouthOpen, PARAM_MOUTH_OPEN_Y
lip_sync_param: ParamMouthOpenY

# Emotion tag → expression Name. The Name on the right must exactly match an
# Expression's Name field in your model3.json. Multiple emotion tags may map
# to the same expression (synonyms). Tags absent from this map fall through
# to "clear expression" (return to neutral).
emotion_mapping:
  开心: 比耶
  害羞: 脸红
  无语: 黑脸
  难过: 哭
  慌张: 流汗
  震惊: 星星
  尴尬: 捂脸
  # ... add as many synonyms as you like
```

If `imouto.yaml` is missing, the loader logs a warning and falls back to a
built-in default mapping that happens to match March 7th's expression names.
You almost certainly want to write one rather than rely on that.

---

## Emotion tags the LLM emits

The LLM is prompted (via `_EMOTION_PROTOCOL` in `core/session.py`) to prefix
every reply with one of these 8 tags:

```
开心  害羞  无语  难过  慌张  震惊  尴尬  平静
```

Your `emotion_mapping` should cover all 8 if you want full emotional range.
`平静` is intentional default — leaving it unmapped clears the current
expression and returns the model to neutral.

You can also add synonyms (毒舌, 翻白眼, 兴奋…) — the LLM occasionally drifts
from the canonical 8. See `EMOTION_TAG_RE` in `app/window.py` for the parser.

---

## Common gotchas (from integrating real VTS models)

These bit us during integration of March 7th and 海兔. Check your model against
them — `tools/import_live2d.py` handles #1, #2, #3, #7 automatically.

### 1. model3.json is missing Expressions / Motions blocks entirely

Symptom: `info()` returns `expressions: []` and `motions: []` even though
the directory has `.exp3.json` and `.motion3.json` files.

A surprising number of VTS-exported model3.json files only have
`Moc / Textures / Physics / DisplayInfo` and no FileReferences for
expressions or motions. The runtime can only load what model3.json declares.

Fix: add the Expressions list (the import tool does this), or add manually:
```json
"FileReferences": {
  ...
  "Expressions": [
    { "Name": "happy", "File": "expressions/happy.exp3.json" },
    ...
  ],
  "Motions": {
    "Idle": [ { "File": "motions/idle1.motion3.json" } ]
  }
}
```

### 2. Expression file paths in model3.json don't match disk layout

Symptom: `[XHRLoader] Failed to load resource as json (Status 0)`.

Many VTS exports put expression files in `exp/` but reference them in
model3.json without the prefix:
```json
"File": "1.exp3.json"          // ← wrong: file is actually at exp/1.exp3.json
"File": "exp/1.exp3.json"      // ← fixed
```
The import tool resolves `.exp3.json` files relative to the model directory,
so generated entries always have correct relative paths.

### 3. Empty LipSync Ids

Symptom: TTS mouth sync silently does nothing.

```json
"Groups": [
  { "Target": "Parameter", "Name": "LipSync", "Ids": [] }   // ← bad
]
```

The import tool detects the right param from `*.cdi3.json` (typically
`ParamMouthOpenY`) and fills the Ids. Reflect the chosen id in
`imouto.yaml`'s `lip_sync_param`.

### 4. Most VTS "expressions" are not emotions

Many VTS models export 10+ expression files where only 2-4 are real
emotions. The rest are clothing toggles, hair styles, accessory shows,
prop holds, etc. Example from the 海兔 model — 11 expressions, of which
only 4 are emotional:

| Expression | Type | Map to emotion? |
|---|---|---|
| 星星眼 | emotion | 震惊 / 兴奋 |
| 尴尬 | emotion | 尴尬 |
| 暗牧 | emotion | 无语 / 毒舌 |
| 生气 | emotion | 生气 |
| 拿话筒, 拿枕头 | prop hold | — trigger explicitly via `setExpression(...)` |
| 第二套发型/衣服, 第三套发型/衣服 | outfit toggle | — UI customizer territory |

Don't try to force-map non-emotional expressions. Leave them out of
`emotion_mapping`. Drive them via `window.imouto.setExpression('拿话筒')`
on a keyword or event.

### 5. Expression names are in `*.vtube.json`, not in model3.json

If you patched model3.json yourself, you might have given expressions
generic names like `expression1.exp3` because the .exp3.json files have no
semantic info. The user-facing names live in VTube Studio's saved config
(`*.vtube.json`) under `Hotkeys[].Name` paired with `Hotkeys[].File`.

The import tool reads this automatically. If you're patching by hand:
```bash
grep -B 2 '"File": "expression' YourModel.vtube.json | grep '"Name":'
```

### 6. Preset expression conflicting with motion → "extra limbs"

If `index.html` preset an expression on load (e.g., `model.expression(0)`)
and that expression posed the model's hands, then a motion playing different
arm parameters could give the model 3 arms / hands in odd places.
**Expressions are additive parameter overrides, not replacements** — they
stack with motions.

Current behavior: imouto does NOT preset an expression on load. The model
stays neutral until the first `[心情:XX]` tag triggers one. If you
re-introduce a default expression, pick one with minimal limb-pose impact.

### 7. Tall full-body aspect ratio (e.g. 3503×7777)

Symptom: model renders tiny in the center of the window.

VTS full-body models are very tall. The default `fit_mode: portrait` scales
by width and anchors at the top, letting the lower body crop out the window
bottom. For a chibi or head-only model, switch to `fit_mode: fit`.

### 8. Spaces, case, and non-ASCII characters in filenames

QtWebEngine fetches case-sensitively in URLs even on Windows (where the
filesystem is case-insensitive). Whatever exact casing you put in
`imouto.yaml`'s `model_file` is what Python passes to JS via the URL.

Spaces and non-ASCII (e.g. `海兔1.model3.json`) are auto-encoded by
`fetch()` to `%20` / `%E6%B5%B7...`. No manual encoding needed.

What matters: the string in `model_file` must match the disk filename byte-
for-byte (modulo case on Windows). Folder names under `live2d/models/`
should stay ASCII for sanity, even when the model file inside is non-ASCII.

---

## Where each piece of model coupling lives

| Concern | File | Notes |
|---|---|---|
| Sidecar config schema | `core/live2d_config.py` | `Live2DConfig` dataclass; add fields here if extending |
| Model path → HTML | `app/window.py` (in `__init__`) | passes `?model=…&fit=…&mouth=…` via URL query |
| Emotion → expression dispatch | `app/window.py` (`_trigger_emotion`) | reads `self.live2d_cfg.emotion_mapping` |
| Emotion tag regex | `app/window.py` (`EMOTION_TAG_RE`) | parses `[心情:XX]` from streamed LLM output |
| Emotion prompt protocol | `core/session.py` (`_EMOTION_PROTOCOL`) | injected as system message into every chat |
| Live2D rendering | `live2d/index.html` | reads URL query, uses pixi-live2d-display |
| Bundled libs | `live2d/lib/` | pixi.js + pixi-live2d-display + Cubism Core, vendored offline |
| JS API surface | `live2d/index.html` (`window.imouto`) | `setExpression(name, {decay?}) / clearExpression / setExpressionDecayMs / playMotion / setMouthOpen / setFitMode / resetPosition / info` |
| Expression decay | `live2d/index.html` (`scheduleExpressionDecay`) | auto-clears expression after `live2d.expression_decay_seconds`; opt out per-call with `{decay:false}` (for prop/outfit holds) |
| Model import automation | `tools/import_live2d.py` | VTS → imouto wiring generator |
| Heuristic emotion keywords | `tools/import_live2d.py` (`KEYWORD_TO_EMOTION`) | regex list mapping Chinese expression-name fragments → canonical emotion |

If a future feature (e.g. TTS) needs to drive a model parameter, add it to
the JS API in `index.html` and call it from Python via
`self.view.page().runJavaScript("window.imouto.<method>(...)")`.

---

## Validation tools

- **`tools/import_live2d.py <model_dir>`** — generates wiring from a fresh
  VTS export. Patches `model3.json` (Expressions / LipSync), reads
  `vtube.json` for expression names, detects mouth param from `cdi3.json`,
  writes a stub `imouto.yaml` with heuristic emotion mapping. Pass
  `--dry-run` to preview, `--force` to overwrite an existing sidecar.
  Backs up the original `model3.json` to `*.bak`.

- **`tools/probe_live2d.py`** — loads `live2d/index.html` headlessly in
  QWebEngine using the currently-active model from `config.example.yaml`,
  captures JS console, and prints `window.imouto.info()` (model dimensions,
  motion groups, expression names). Run this whenever you swap models —
  load errors, missing expressions, wrong paths all show up here.

- **`tools/smoke_ui.py`** — full app launch, 3s window, exits cleanly.
  Verifies the integration boots end-to-end with the real session + memory.

---

## Known limitations (future work)

- **No model picker UI**: switching models requires editing config.yaml. A
  settings dropdown that auto-discovers `live2d/models/*/imouto.yaml` would
  be a small addition.
- **Motion ↔ emotion not wired**: only expressions react to emotion tags.
  Motions play on Idle. A `motion_mapping` field in the sidecar would add
  a "play a motion for this emotion" hook. Be careful — many VTS models
  have motion names that aren't emotion-coded (`zhaoxiang` = camera pose),
  so it's per-model whether mapping is useful.
- **HitAreas**: pixi-live2d-display can dispatch click events on named hit
  areas (head, body). Not used yet — could enable "click her head = motion".
- **Heuristic emotion mapping is rough**: `import_live2d.py` keyword
  matching catches common Chinese words but misses English-named models or
  unusual phrasings. Review the generated sidecar.
- **Models with no real emotional expressions**: if a model only ships
  prop/outfit toggles, mapping covers very little. Consider expanding the
  model in Cubism Editor or pairing the toggles with conversational cues
  (`window.imouto.setExpression('拿话筒')` when user says "唱首歌").
- **Multi-monitor canvas scaling**: the window uses
  `resolution: window.devicePixelRatio` which may stutter on monitors with
  different DPRs while dragging across them.
