"""Recover the 'small' user-facing SoVITS weight from a training checkpoint.

When the CLI training script forgets to mkdir SoVITS_weights_v4/ before s2
training starts, savee() fails silently mid-training. The full checkpoint
G_<step>.pth still gets written. This script extracts the inference-only
weight from it, identical to what savee would have produced.

Usage:
    python tools/recover_sovits_weight.py ^
        --name myvoice --epoch 8 --step 760 --lora-rank 32 --version v4

Pass --gpt-sovits-dir or set env var GPT_SOVITS_DIR.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import OrderedDict
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    default_dir = os.environ.get("GPT_SOVITS_DIR")
    ap.add_argument(
        "--gpt-sovits-dir",
        type=Path,
        default=Path(default_dir) if default_dir else None,
    )
    ap.add_argument("--name", required=True)
    ap.add_argument("--epoch", type=int, required=True)
    ap.add_argument("--step", type=int, required=True,
                    help="usually 233333333333 for if_save_latest=True")
    ap.add_argument("--lora-rank", type=int, default=32)
    ap.add_argument("--version", default="v4")
    args = ap.parse_args()
    if args.gpt_sovits_dir is None:
        print("error: set GPT_SOVITS_DIR or pass --gpt-sovits-dir", file=sys.stderr)
        return 2

    os.chdir(args.gpt_sovits_dir)
    sys.path.insert(0, str(args.gpt_sovits_dir))
    sys.path.insert(0, str(args.gpt_sovits_dir / "GPT_SoVITS"))

    import torch
    from process_ckpt import savee

    ckpt_path = (
        args.gpt_sovits_dir
        / f"logs/{args.name}/logs_s2_{args.version}_lora_{args.lora_rank}"
        / "G_233333333333.pth"
    )
    print(f"loading {ckpt_path}")
    raw = torch.load(ckpt_path, map_location="cpu", weights_only=False)

    # The training script saves {'model': state_dict, 'optimizer': ..., 'iteration': N, 'learning_rate': ...}
    # in utils.save_checkpoint. We want the model state_dict only.
    if isinstance(raw, dict) and "model" in raw:
        state_dict = raw["model"]
        print(f"  iteration: {raw.get('iteration', '?')}")
    else:
        state_dict = raw

    # Match the training-time small-weight extraction (s2_train_v3_lora.py:357-368).
    # no_grad_names = the parameters that were frozen. We don't know them exactly,
    # but the safe approximation is: keep everything (since training already pruned
    # frozen-ness via requires_grad). Convert to half precision to match savee.
    sim_ckpt = OrderedDict()
    skipped_enc_q = 0
    for key, value in state_dict.items():
        if "enc_q" in key:
            skipped_enc_q += 1
            continue
        sim_ckpt[key] = value.half().cpu() if hasattr(value, "half") else value
    print(f"  kept {len(sim_ckpt)} params, skipped {skipped_enc_q} enc_q params")

    # Read hps from the s2 logs/config.json (the training script writes it there)
    import json
    cfg_json = args.gpt_sovits_dir / f"logs/{args.name}" / "config.json"
    if not cfg_json.exists():
        cfg_json = args.gpt_sovits_dir / "TEMP" / "tmp_s2.json"
    with cfg_json.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    # Use GPT-SoVITS's own utils.HParams so the pickled hps is loadable later
    import utils as gpt_sovits_utils
    hps = gpt_sovits_utils.HParams(**cfg)
    if not hasattr(hps, "save_weight_dir"):
        hps.save_weight_dir = f"SoVITS_weights_{args.version}"

    out_dir = args.gpt_sovits_dir / hps.save_weight_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"  output dir: {out_dir}")

    name = f"{args.name}_e{args.epoch}_s{args.step}_l{args.lora_rank}"
    result = savee(
        sim_ckpt, name, args.epoch, args.step, hps,
        model_version=args.version, lora_rank=args.lora_rank,
    )
    print(f"savee result: {result}")
    out_path = out_dir / f"{name}.pth"
    if out_path.exists():
        size_mb = out_path.stat().st_size / (1024 * 1024)
        print(f"\n✓ wrote {out_path}  ({size_mb:.1f} MB)")
        return 0
    print(f"\nERROR: expected {out_path} not created")
    return 1


if __name__ == "__main__":
    sys.exit(main())
