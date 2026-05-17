"""End-to-end GPT-SoVITS v4 training, no Gradio.

Replicates what the webui's Tab 1 (preprocess) + Tab 2 (train) do, by setting
the same env vars and calling the same underlying scripts. Lets you train a
voice as a single command — automatable, reproducible, no clicking.

Required env vars (or pass via flags):
    GPT_SOVITS_DIR     — path to a cloned GPT-SoVITS repo (with pretrained
                         models already downloaded into GPT_SoVITS/pretrained_models/).
    GPT_SOVITS_PYTHON  — python.exe of a GPT-SoVITS-compatible env
                         (the GPT-SoVITS docs recommend a dedicated conda env).

Usage:
    python tools/sovits_train.py ^
        --name myvoice ^
        --list-file path/to/data.list ^
        --wav-dir   path/to/wavs

Optional flags (sensible defaults for a high-end GPU + 30 min data):
    --batch-size 12 --epochs-s2 8 --epochs-s1 15 --save-every 4

Outputs land under:
    <GPT_SOVITS_DIR>/SoVITS_weights_v4/<name>_eN_sM.pth
    <GPT_SOVITS_DIR>/GPT_weights_v4/<name>-eN.ckpt
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


# -------------------------------------------------------------- environment


# Defaults come from the env so this script stays portable.
DEFAULT_GPT_SOVITS_DIR = Path(os.environ.get("GPT_SOVITS_DIR", "")) if os.environ.get("GPT_SOVITS_DIR") else None
DEFAULT_PYTHON = Path(os.environ.get("GPT_SOVITS_PYTHON", "")) if os.environ.get("GPT_SOVITS_PYTHON") else None
DEFAULT_VERSION = "v4"

# Paths inside GPT-SoVITS that hold the base/pretrained models. Resolved
# relative to --gpt-sovits-dir.
BERT_DIR = "GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large"
HUBERT_DIR = "GPT_SoVITS/pretrained_models/chinese-hubert-base"
SV_PATH = "GPT_SoVITS/pretrained_models/sv/pretrained_eres2netv2w24s4ep4.ckpt"

# Per-version pretrained checkpoints
PRETRAINED_S2G = {
    "v2": "GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/s2G2333k.pth",
    "v3": "GPT_SoVITS/pretrained_models/s2Gv3.pth",
    "v4": "GPT_SoVITS/pretrained_models/gsv-v4-pretrained/s2Gv4.pth",
    "v2Pro": "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2Pro.pth",
    "v2ProPlus": "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth",
}
PRETRAINED_S1 = {
    "v2": "GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt",
    "v3": "GPT_SoVITS/pretrained_models/s1v3.ckpt",
    "v4": "GPT_SoVITS/pretrained_models/s1v3.ckpt",  # v4 reuses v3 GPT base
    "v2Pro": "GPT_SoVITS/pretrained_models/s1v3.ckpt",
    "v2ProPlus": "GPT_SoVITS/pretrained_models/s1v3.ckpt",
}

# Which s2 training script to use per version
S2_TRAIN_SCRIPT = {
    "v1": "GPT_SoVITS/s2_train.py",
    "v2": "GPT_SoVITS/s2_train.py",
    "v2Pro": "GPT_SoVITS/s2_train.py",
    "v2ProPlus": "GPT_SoVITS/s2_train.py",
    "v3": "GPT_SoVITS/s2_train_v3_lora.py",
    "v4": "GPT_SoVITS/s2_train_v3_lora.py",
}

# Which s2 config template to use per version
S2_CONFIG_TEMPLATE = {
    "v1": "GPT_SoVITS/configs/s2.json",
    "v2": "GPT_SoVITS/configs/s2.json",
    "v3": "GPT_SoVITS/configs/s2.json",
    "v4": "GPT_SoVITS/configs/s2.json",
    "v2Pro": "GPT_SoVITS/configs/s2v2Pro.json",
    "v2ProPlus": "GPT_SoVITS/configs/s2v2ProPlus.json",
}

S1_CONFIG_TEMPLATE_V2_PLUS = "GPT_SoVITS/configs/s1longer-v2.yaml"

SOVITS_WEIGHTS_ROOT = {
    "v1": "SoVITS_weights",
    "v2": "SoVITS_weights_v2",
    "v3": "SoVITS_weights_v3",
    "v4": "SoVITS_weights_v4",
    "v2Pro": "SoVITS_weights_v2Pro",
    "v2ProPlus": "SoVITS_weights_v2ProPlus",
}
GPT_WEIGHTS_ROOT = {
    "v1": "GPT_weights",
    "v2": "GPT_weights_v2",
    "v3": "GPT_weights_v3",
    "v4": "GPT_weights_v4",
    "v2Pro": "GPT_weights_v2Pro",
    "v2ProPlus": "GPT_weights_v2ProPlus",
}


# -------------------------------------------------------------- helpers


def _make_pythonpath(gpt_sovits_dir: Path) -> str:
    """Ensure GPT-SoVITS root + GPT_SoVITS package dir are importable.
    Prepare scripts import `text` / `tools` (top-level in repo); training
    scripts import `module.*` (inside GPT_SoVITS/)."""
    repo_root = str(gpt_sovits_dir.resolve())
    inner = str((gpt_sovits_dir / "GPT_SoVITS").resolve())
    existing = os.environ.get("PYTHONPATH", "")
    return os.pathsep.join(p for p in [repo_root, inner, existing] if p)


def run_cmd(
    cmd: list[str],
    env_extra: dict[str, str] | None = None,
    cwd: Path | None = None,
    gpt_sovits_dir: Path | None = None,
) -> None:
    """Run a subprocess, inheriting env + overrides, fail fast on non-zero.
    Always injects PYTHONPATH for the GPT-SoVITS repo."""
    env = os.environ.copy()
    # Auto-inject PYTHONPATH if we know the repo root
    if gpt_sovits_dir is not None:
        env["PYTHONPATH"] = _make_pythonpath(gpt_sovits_dir)
    # PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True works on Linux but
    # the Windows allocator logs a "not supported" warning and may misbehave.
    # Leave it unset on Windows.
    if sys.platform != "win32":
        env.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    if env_extra:
        env.update(env_extra)
    print(f"\n$ {' '.join(cmd)}", flush=True)
    if env_extra:
        for k, v in env_extra.items():
            if k == "PYTHONPATH":
                continue
            print(f"    env: {k}={v}", flush=True)
    res = subprocess.run(cmd, env=env, cwd=str(cwd) if cwd else None)
    if res.returncode != 0:
        raise RuntimeError(f"command failed (exit {res.returncode}): {' '.join(cmd)}")


def base_env(args, opt_dir: str) -> dict[str, str]:
    return {
        "inp_text": args.list_file,
        "inp_wav_dir": args.wav_dir,
        "exp_name": args.name,
        "opt_dir": opt_dir,
        "i_part": "0",
        "all_parts": "1",
        "_CUDA_VISIBLE_DEVICES": str(args.gpu),
        "is_half": "True" if not args.no_half else "False",
        "version": args.version,
    }


# -------------------------------------------------------------- preprocess


def _merge_parts(opt_abs: Path, basename_no_part: str, ext: str) -> None:
    """Concatenate '<basename>-{i}.<ext>' parts into '<basename>.<ext>'.
    The training scripts expect the merged file. Mirrors what webui does
    after each prepare step."""
    final = opt_abs / f"{basename_no_part}.{ext}"
    parts = sorted(opt_abs.glob(f"{basename_no_part}-*.{ext}"))
    if not parts:
        return
    contents = []
    for p in parts:
        contents.append(p.read_text(encoding="utf-8").rstrip("\n"))
    final.write_text("\n".join(contents) + "\n", encoding="utf-8")


def step_1a_text(args, opt_dir: str) -> None:
    """Text → phonemes + BERT features."""
    env = base_env(args, opt_dir)
    env["bert_pretrained_dir"] = BERT_DIR
    run_cmd(
        [str(args.python), "-s", "GPT_SoVITS/prepare_datasets/1-get-text.py"],
        env_extra=env,
        cwd=args.gpt_sovits_dir,
        gpt_sovits_dir=args.gpt_sovits_dir,
    )
    _merge_parts(args.gpt_sovits_dir / opt_dir, "2-name2text", "txt")


def step_1b_hubert(args, opt_dir: str) -> None:
    """Audio → SSL (Hubert) features."""
    env = base_env(args, opt_dir)
    env["cnhubert_base_dir"] = HUBERT_DIR
    env["sv_path"] = SV_PATH
    run_cmd(
        [str(args.python), "-s", "GPT_SoVITS/prepare_datasets/2-get-hubert-wav32k.py"],
        env_extra=env,
        cwd=args.gpt_sovits_dir,
        gpt_sovits_dir=args.gpt_sovits_dir,
    )
    # 2-get-sv.py only needed for v2Pro / v2ProPlus
    if "Pro" in args.version:
        run_cmd(
            [str(args.python), "-s", "GPT_SoVITS/prepare_datasets/2-get-sv.py"],
            env_extra=env,
            cwd=args.gpt_sovits_dir,
        )


def step_1c_semantic(args, opt_dir: str) -> None:
    """SSL features → semantic tokens."""
    env = base_env(args, opt_dir)
    env["pretrained_s2G"] = PRETRAINED_S2G[args.version]
    env["s2config_path"] = S2_CONFIG_TEMPLATE[args.version]
    run_cmd(
        [str(args.python), "-s", "GPT_SoVITS/prepare_datasets/3-get-semantic.py"],
        env_extra=env,
        cwd=args.gpt_sovits_dir,
        gpt_sovits_dir=args.gpt_sovits_dir,
    )
    _merge_parts(args.gpt_sovits_dir / opt_dir, "6-name2semantic", "tsv")


# -------------------------------------------------------------- training


def step_s2_train(args, opt_dir: str) -> Path:
    """SoVITS / decoder training. Returns path to the final .pth weight."""
    template = args.gpt_sovits_dir / S2_CONFIG_TEMPLATE[args.version]
    with template.open("r", encoding="utf-8") as f:
        data = json.load(f)

    s2_logs_dir = Path(opt_dir) / f"logs_s2_{args.version}"
    s2_logs_dir.mkdir(parents=True, exist_ok=True)

    # CRITICAL: GPT-SoVITS's savee() doesn't mkdir the output dir, just opens
    # a file inside it. Pre-create or the every-N-epoch weight save silently
    # fails and only the rolling G_<step>.pth checkpoint survives.
    (args.gpt_sovits_dir / SOVITS_WEIGHTS_ROOT[args.version]).mkdir(parents=True, exist_ok=True)

    pretrained_s2G = PRETRAINED_S2G[args.version]
    pretrained_s2D = pretrained_s2G.replace("s2G", "s2D")

    data["train"]["batch_size"] = args.batch_size
    data["train"]["epochs"] = args.epochs_s2
    data["train"]["text_low_lr_rate"] = 0.4
    data["train"]["pretrained_s2G"] = pretrained_s2G
    data["train"]["pretrained_s2D"] = pretrained_s2D
    data["train"]["if_save_latest"] = True
    data["train"]["if_save_every_weights"] = True
    data["train"]["save_every_epoch"] = args.save_every
    data["train"]["gpu_numbers"] = str(args.gpu)
    data["train"]["grad_ckpt"] = args.grad_ckpt
    data["train"]["lora_rank"] = args.lora_rank
    if args.no_half:
        data["train"]["fp16_run"] = False
    data["model"]["version"] = args.version
    data["data"]["exp_dir"] = opt_dir
    data["s2_ckpt_dir"] = opt_dir
    data["save_weight_dir"] = SOVITS_WEIGHTS_ROOT[args.version]
    data["name"] = args.name
    data["version"] = args.version

    tmp_cfg = args.gpt_sovits_dir / "TEMP" / "tmp_s2.json"
    tmp_cfg.parent.mkdir(parents=True, exist_ok=True)
    with tmp_cfg.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[s2] config written to {tmp_cfg}")

    run_cmd(
        [str(args.python), "-s", S2_TRAIN_SCRIPT[args.version], "--config", str(tmp_cfg)],
        cwd=args.gpt_sovits_dir,
        gpt_sovits_dir=args.gpt_sovits_dir,
    )

    weights_dir = args.gpt_sovits_dir / SOVITS_WEIGHTS_ROOT[args.version]
    candidates = sorted(weights_dir.glob(f"{args.name}_*.pth"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise RuntimeError(f"no SoVITS weight found in {weights_dir} after training")
    final = candidates[-1]
    print(f"[s2] DONE → {final}")
    return final


def step_s1_train(args, opt_dir: str) -> Path:
    """GPT training. Returns path to the final .ckpt weight."""
    template = args.gpt_sovits_dir / S1_CONFIG_TEMPLATE_V2_PLUS
    with template.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    s1_logs_dir = Path(opt_dir) / "logs_s1"
    s1_logs_dir.mkdir(parents=True, exist_ok=True)
    (args.gpt_sovits_dir / GPT_WEIGHTS_ROOT[args.version]).mkdir(parents=True, exist_ok=True)

    # Windows + multi-worker DataLoader = native crash on sm_120 / CUDA 12.8.
    # Single worker is safe (prefetch_factor needs num_workers > 0).
    data.setdefault("data", {})
    data["data"]["num_workers"] = 1

    data.setdefault("train", {})
    data["train"]["batch_size"] = args.batch_size
    data["train"]["epochs"] = args.epochs_s1
    data["train"]["save_every_n_epoch"] = args.save_every
    data["train"]["if_save_every_weights"] = True
    data["train"]["if_save_latest"] = True
    data["train"]["if_dpo"] = False
    data["train"]["half_weights_save_dir"] = GPT_WEIGHTS_ROOT[args.version]
    data["train"]["exp_name"] = args.name
    # bf16-mixed is more stable than 16-mixed (fp16) on Blackwell sm_120
    # and avoids the Windows DDP + autocast access-violation we hit.
    if args.no_half:
        data["train"]["precision"] = "32"
    elif args.s1_precision:
        data["train"]["precision"] = args.s1_precision
    else:
        data["train"]["precision"] = "bf16-mixed"
    data["pretrained_s1"] = PRETRAINED_S1[args.version]
    data["train_semantic_path"] = f"{opt_dir}/6-name2semantic.tsv"
    data["train_phoneme_path"] = f"{opt_dir}/2-name2text.txt"
    data["output_dir"] = f"{opt_dir}/logs_s1_{args.version}"

    tmp_cfg = args.gpt_sovits_dir / "TEMP" / "tmp_s1.yaml"
    tmp_cfg.parent.mkdir(parents=True, exist_ok=True)
    with tmp_cfg.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False)
    print(f"[s1] config written to {tmp_cfg}")

    run_cmd(
        [str(args.python), "-s", "GPT_SoVITS/s1_train.py", "--config_file", str(tmp_cfg)],
        env_extra={
            "_CUDA_VISIBLE_DEVICES": str(args.gpu),
            "hz": "25hz",
        },
        cwd=args.gpt_sovits_dir,
        gpt_sovits_dir=args.gpt_sovits_dir,
    )

    weights_dir = args.gpt_sovits_dir / GPT_WEIGHTS_ROOT[args.version]
    candidates = sorted(weights_dir.glob(f"{args.name}-*.ckpt"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise RuntimeError(f"no GPT weight found in {weights_dir} after training")
    final = candidates[-1]
    print(f"[s1] DONE → {final}")
    return final


# -------------------------------------------------------------- entry


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="experiment / model name (e.g. march7th)")
    ap.add_argument("--list-file", required=True, help="path to the .list manifest")
    ap.add_argument("--wav-dir", required=True, help="folder of WAVs referenced by the .list")
    ap.add_argument("--gpt-sovits-dir", type=Path, default=DEFAULT_GPT_SOVITS_DIR)
    ap.add_argument("--python", type=Path, default=DEFAULT_PYTHON,
                    help="Python from the GPTSoVits conda env")
    ap.add_argument("--version", default=DEFAULT_VERSION,
                    choices=["v2", "v3", "v4", "v2Pro", "v2ProPlus"])
    ap.add_argument("--batch-size", type=int, default=12)
    ap.add_argument("--epochs-s2", type=int, default=8, help="SoVITS epochs")
    ap.add_argument("--epochs-s1", type=int, default=15, help="GPT epochs")
    ap.add_argument("--save-every", type=int, default=4)
    ap.add_argument("--gpu", type=int, default=0)
    ap.add_argument("--lora-rank", type=int, default=32, help="for v3/v4 LoRA (32=lean, 128=full)")
    ap.add_argument("--s1-precision", default=None,
                    help="override s1 precision: 32 / bf16-mixed / 16-mixed (default bf16-mixed)")
    ap.add_argument("--grad-ckpt", action="store_true", default=True,
                    help="gradient checkpointing (slower but ~half activation memory)")
    ap.add_argument("--no-grad-ckpt", dest="grad_ckpt", action="store_false",
                    help="disable gradient checkpointing")
    ap.add_argument("--no-half", action="store_true", help="disable fp16")
    ap.add_argument("--skip-prepare", action="store_true",
                    help="skip 1a/1b/1c (data already preprocessed)")
    ap.add_argument("--skip-s2", action="store_true")
    ap.add_argument("--skip-s1", action="store_true")
    args = ap.parse_args()

    # validate inputs
    if args.gpt_sovits_dir is None or not args.gpt_sovits_dir.is_dir():
        print(
            "error: GPT-SoVITS directory not set. Set env var GPT_SOVITS_DIR "
            "or pass --gpt-sovits-dir.",
            file=sys.stderr,
        )
        return 2
    if args.python is None or not args.python.is_file():
        print(
            "error: GPT-SoVITS python interpreter not set. Set env var "
            "GPT_SOVITS_PYTHON or pass --python (point at the python.exe of "
            "a conda env that meets GPT-SoVITS's requirements).",
            file=sys.stderr,
        )
        return 2
    if not Path(args.list_file).is_file():
        print(f"error: list file not found: {args.list_file}", file=sys.stderr)
        return 2
    if not Path(args.wav_dir).is_dir():
        print(f"error: wav dir not found: {args.wav_dir}", file=sys.stderr)
        return 2

    opt_dir = f"logs/{args.name}"  # relative to gpt-sovits-dir
    (args.gpt_sovits_dir / opt_dir).mkdir(parents=True, exist_ok=True)

    print(f"=== sovits-train ===")
    print(f"  name       : {args.name}")
    print(f"  version    : {args.version}")
    print(f"  list       : {args.list_file}")
    print(f"  wav-dir    : {args.wav_dir}")
    print(f"  exp_dir    : {args.gpt_sovits_dir}/{opt_dir}")
    print(f"  python     : {args.python}")
    print(f"  batch_size : {args.batch_size}")
    print(f"  epochs_s2  : {args.epochs_s2}  epochs_s1: {args.epochs_s1}")

    if not args.skip_prepare:
        print("\n=== step 1a: text → phonemes + BERT ===")
        step_1a_text(args, opt_dir)
        print("\n=== step 1b: audio → SSL features ===")
        step_1b_hubert(args, opt_dir)
        print("\n=== step 1c: semantic tokens ===")
        step_1c_semantic(args, opt_dir)

    final_s2 = None
    if not args.skip_s2:
        print("\n=== step 2: SoVITS training ===")
        final_s2 = step_s2_train(args, opt_dir)

    final_s1 = None
    if not args.skip_s1:
        print("\n=== step 3: GPT training ===")
        final_s1 = step_s1_train(args, opt_dir)

    print("\n=== ALL DONE ===")
    if final_s2:
        print(f"  SoVITS weight: {final_s2}")
    if final_s1:
        print(f"  GPT weight   : {final_s1}")
    print("\nConfigure imouto:")
    print("  voice.backend: gpt-sovits")
    print(f"  voice.sovits.ref_audio: <path to 5-10s clean clip>")
    print(f"  voice.sovits.ref_text: <its exact transcript>")
    print("Then start the API server in the GPTSoVits env:")
    print(f"  python api_v2.py -a 127.0.0.1 -p 9880 \\")
    if final_s2:
        print(f"    -s {final_s2.relative_to(args.gpt_sovits_dir)} \\")
    if final_s1:
        print(f"    -g {final_s1.relative_to(args.gpt_sovits_dir)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
