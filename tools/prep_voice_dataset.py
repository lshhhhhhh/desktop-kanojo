"""Prepare a wav+lab folder for GPT-SoVITS training.

Given a folder of paired `<name>.wav` + `<name>.lab` files (the typical
game-extracted layout), this script:

1. Copies all wav+lab files to a clean ASCII destination
2. Generates a `data.list` manifest in the format GPT-SoVITS expects:
       <wav_path>|<speaker>|<lang>|<text>
3. Reports total clip count, total duration, and duration distribution

Usage:
    python tools/prep_voice_dataset.py ^
        --src path/to/raw_clips ^
        --dst path/to/voices/myvoice ^
        --speaker myvoice ^
        --lang zh
"""

from __future__ import annotations

import argparse
import shutil
import sys
import wave
from pathlib import Path


def wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except (wave.Error, EOFError, FileNotFoundError):
        return 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", type=Path, required=True, help="source folder of *.wav + *.lab")
    ap.add_argument("--dst", type=Path, required=True, help="destination folder (will be created)")
    ap.add_argument("--speaker", default="speaker0", help="speaker tag in .list")
    ap.add_argument("--lang", default="zh", choices=["zh", "en", "ja", "ko", "yue"])
    ap.add_argument("--no-copy", action="store_true",
                    help="don't copy files, just generate .list pointing at src paths")
    ap.add_argument("--strip-empty-labs", action="store_true", default=True,
                    help="drop pairs whose .lab is empty (default on)")
    args = ap.parse_args()

    if not args.src.is_dir():
        print(f"error: src dir not found: {args.src}", file=sys.stderr)
        return 2

    wavs = sorted(args.src.glob("*.wav"))
    if not wavs:
        print(f"error: no *.wav under {args.src}", file=sys.stderr)
        return 2

    if not args.no_copy:
        args.dst.mkdir(parents=True, exist_ok=True)

    pairs = []  # (wav_path_after_copy, transcript, duration_s)
    skipped_no_lab = 0
    skipped_empty = 0
    skipped_short = 0
    total_dur = 0.0

    for wav in wavs:
        lab = wav.with_suffix(".lab")
        if not lab.exists():
            skipped_no_lab += 1
            continue
        text = lab.read_text(encoding="utf-8", errors="replace").strip()
        if args.strip_empty_labs and not text:
            skipped_empty += 1
            continue
        dur = wav_duration(wav)
        if dur < 0.3:
            skipped_short += 1
            continue

        if args.no_copy:
            target_wav = wav
        else:
            target_wav = args.dst / wav.name
            if not target_wav.exists():
                shutil.copy2(wav, target_wav)
            target_lab = args.dst / lab.name
            if not target_lab.exists():
                shutil.copy2(lab, target_lab)

        pairs.append((target_wav, text, dur))
        total_dur += dur

    if not pairs:
        print("error: no valid wav+lab pairs found", file=sys.stderr)
        return 2

    # Write manifest
    list_dir = args.src if args.no_copy else args.dst
    list_path = list_dir / "data.list"
    with list_path.open("w", encoding="utf-8") as f:
        for wav_path, text, _ in pairs:
            # use absolute path with forward slashes for cross-platform safety
            f.write(f"{wav_path.resolve().as_posix()}|{args.speaker}|{args.lang}|{text}\n")

    # Stats
    durations = [d for _, _, d in pairs]
    durations.sort()
    print()
    print("=" * 56)
    print(f"Manifest written: {list_path}")
    print(f"  pairs:                {len(pairs)}")
    print(f"  total duration:       {total_dur:.1f} s   ({total_dur/60:.1f} min)")
    print(f"  avg duration:         {total_dur/len(pairs):.2f} s")
    print(f"  shortest 5%:          {durations[int(len(durations)*0.05)]:.2f} s")
    print(f"  median:               {durations[len(durations)//2]:.2f} s")
    print(f"  longest 5%:           {durations[int(len(durations)*0.95)]:.2f} s")
    print(f"  longest:              {durations[-1]:.2f} s")
    print()
    print(f"  skipped: no .lab     : {skipped_no_lab}")
    print(f"  skipped: empty .lab  : {skipped_empty}")
    print(f"  skipped: too short   : {skipped_short}  (< 0.3s)")
    print("=" * 56)
    print()
    if total_dur < 5 * 60:
        print("WARN: total duration < 5 min — training quality will suffer.")
    elif total_dur > 2 * 3600:
        print("NOTE: > 2 hr is overkill; 30-60 min usually plenty for one voice.")

    print(f"\nNext: run training with this manifest:")
    print(f"  python tools/sovits_train.py \\")
    print(f"    --name {args.speaker} \\")
    print(f"    --list-file {list_path.resolve().as_posix()} \\")
    print(f"    --wav-dir   {list_dir.resolve().as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
