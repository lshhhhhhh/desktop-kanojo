"""Install a Live2D model from a user-provided zip file.

Used by the first-run wizard: the user goes to the Live2D website, downloads
a sample model zip, then drops it into the app via a file picker. This module
unpacks the zip into `live2d/models/<derived_name>/`, generates the imouto.yaml
sidecar (reusing tools.import_live2d), and records the choice in preferences.

We never bundle, never auto-download. The user does the download themselves,
which keeps the Live2D Free Material License redistribution clause (4.1.1)
out of the picture entirely.
"""

from __future__ import annotations

import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

MODELS_ROOT = Path("live2d/models")


@dataclass
class InstallResult:
    name: str          # folder name under live2d/models/ (e.g. "Haru")
    model_dir: Path    # absolute path
    model_file: str    # *.model3.json basename
    expressions: int   # number of expressions detected


class InstallError(Exception):
    pass


def install_zip(zip_path: Path, models_root: Path = MODELS_ROOT) -> InstallResult:
    """Unpack a Live2D model zip, run the import_live2d pipeline on the
    resulting folder, and return where it landed.

    Behavior:
    - If the zip contains a single top-level directory, that directory's
      name becomes the model name and we don't double-nest.
    - Otherwise the zip stem (filename without .zip) is used and all files
      are extracted directly under it.
    - If a model with the same name already exists, raises InstallError.
      Callers can pre-check + delete the existing dir if they want to replace.
    """
    if not zip_path.is_file():
        raise InstallError(f"not a file: {zip_path}")
    if not zipfile.is_zipfile(zip_path):
        raise InstallError(f"not a zip file: {zip_path}")

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if not names:
            raise InstallError("empty zip")

        # Detect "single top-level directory" pattern. We look at the first
        # path segment of every member; if they all share one segment that
        # is itself a directory, that's our nest.
        roots = {n.split("/", 1)[0] for n in names if n and not n.startswith("/")}
        nested_dir: str | None = None
        if len(roots) == 1:
            sole = next(iter(roots))
            # Has to be a dir, not a top-level file
            if any(n.startswith(sole + "/") for n in names):
                nested_dir = sole

        target_name = _sanitize(nested_dir) if nested_dir else _sanitize(zip_path.stem)

        if not target_name:
            raise InstallError("could not derive model name from zip")

        models_root.mkdir(parents=True, exist_ok=True)
        target = models_root / target_name
        if target.exists():
            raise InstallError(
                f"model directory already exists: {target}. "
                "Remove it first if you want to reinstall."
            )

        if nested_dir:
            # Extract everything under nested_dir/ directly into target/.
            target.mkdir(parents=True, exist_ok=False)
            prefix = nested_dir + "/"
            for member in zf.infolist():
                if not member.filename.startswith(prefix):
                    continue
                rel = member.filename[len(prefix):]
                if not rel:
                    continue
                dest = target / rel
                if member.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, dest.open("wb") as out:
                    shutil.copyfileobj(src, out)
        else:
            target.mkdir(parents=True, exist_ok=False)
            zf.extractall(target)

    # Find the model3.json and run the import pipeline against this folder.
    # Lazy-import to keep core/ free of tools/ dependency in normal hot paths.
    from tools import import_live2d as importer

    model3 = importer._find_one(target, ".model3.json")
    if model3 is None:
        # Cleanup on failure
        shutil.rmtree(target, ignore_errors=True)
        raise InstallError(
            f"no *.model3.json inside the zip (under {target.name})"
        )

    vtube = importer._read_json(
        importer._find_one(target, ".vtube.json") or Path("/nonexistent")
    )
    cdi = importer._read_json(
        importer._find_one(target, ".cdi3.json") or Path("/nonexistent")
    )
    name_map = importer._extract_vtube_hotkeys(vtube)
    mouth_param = importer._detect_mouth_param(cdi)

    exp_files = importer._list_expression_files(target)
    expression_entries: list[dict] = []
    for p in exp_files:
        rel = p.relative_to(target).as_posix()
        name = name_map.get(rel) or name_map.get(p.name) or p.stem
        expression_entries.append({"Name": name, "File": rel})

    importer._patch_model3(model3, expression_entries, mouth_param, dry_run=False)
    importer._write_sidecar(
        target, model3, mouth_param, expression_entries,
        dry_run=False, force=False,
    )

    logger.info(
        "live2d_installer: installed {!r} at {} ({} expressions)",
        target_name, target, len(expression_entries),
    )
    return InstallResult(
        name=target_name,
        model_dir=target.resolve(),
        model_file=model3.name,
        expressions=len(expression_entries),
    )


def _sanitize(name: str) -> str:
    """Strip path separators and characters that misbehave as folder names.
    Keeps Unicode (so '海兔' / 'Haru' both work)."""
    bad = '<>:"/\\|?*'
    out = "".join(c for c in name if c not in bad).strip()
    out = out.rstrip(".")  # Windows: trailing dot in folder name is invalid
    return out
