# PyInstaller spec for desktop-kanojo (onedir).
#
# Produces dist/desktop-kanojo/ — a self-contained folder users can zip,
# unpack, and run by double-clicking desktop-kanojo.exe. No Python install
# required on the target machine.
#
# Build:  .venv\Scripts\pyinstaller.exe desktop-kanojo.spec --clean --noconfirm

# ruff: noqa
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# Conda Python ships some stdlib native dependencies in Library/bin/ next to
# the base interpreter (not next to the venv's python.exe). PyInstaller's
# dependency walker doesn't search there, so _sqlite3.pyd's sqlite3.dll (and
# a few others) go missing in the bundle. Pick them up by hand.
#
# sys.base_prefix points at the conda env we're venv'd into; the venv's own
# sys.prefix is the .venv dir which lacks Library/bin.
extra_binaries = []
for libbin in (Path(sys.base_prefix) / "Library" / "bin",
               Path(sys.executable).parent.parent / "Library" / "bin"):
    if libbin.is_dir():
        for dll in ("sqlite3.dll", "libcrypto-1_1-x64.dll", "libssl-1_1-x64.dll",
                    "ffi-8.dll", "ffi-7.dll", "ffi.dll",
                    "liblzma.dll", "libbz2.dll"):
            p = libbin / dll
            if p.is_file():
                extra_binaries.append((str(p), "."))
        break

# Small native-lib packages — collect_all is fine, they're tiny.
# We deliberately do NOT collect_all PySide6: that drags in every Qt
# module (Charts, Quick3D, Positioning, ...). PyInstaller's built-in
# PySide6 hook already picks the modules we actually import (QtCore,
# QtGui, QtWidgets, QtWebEngineCore/Widgets, QtMultimedia) plus their
# resources (Chromium .pak, locales, icudtl.dat, QtWebEngineProcess.exe).
sqlitevec_datas, sqlitevec_binaries, sqlitevec_hidden = collect_all("sqlite_vec")
miniaudio_datas, miniaudio_binaries, miniaudio_hidden = collect_all("miniaudio")

# Project-tracked assets that need to ship. PyInstaller puts these under
# _internal/ inside the dist folder; tools/build.ps1 then promotes the
# user-facing ones (live2d/, personas/, config.example.yaml) to the exe's
# top level so cwd-relative paths in the code still work.
project_datas = [
    ("live2d/index.html", "live2d"),
    ("live2d/lib", "live2d/lib"),
    ("personas", "personas"),
    ("config.example.yaml", "."),
]

a = Analysis(
    ["app/main.py"],
    pathex=[],
    binaries=sqlitevec_binaries + miniaudio_binaries + extra_binaries,
    datas=project_datas + sqlitevec_datas + miniaudio_datas,
    hiddenimports=(
        sqlitevec_hidden
        + miniaudio_hidden
        + [
            # edge-tts lazy-imports these; PyInstaller doesn't see them otherwise.
            "edge_tts",
            "websockets",
            "websockets.legacy",
            "websockets.legacy.client",
            # mss screen capture
            "mss",
            # cffi backend — miniaudio uses it for native audio decode/encode
            "_cffi_backend",
            "cffi",
            # core package — make sure all submodules ship
            "core.live2d_installer",
            "core.live2d_binding",
            "core.env_file",
            "core.preferences",
            "core.perception.privacy",
            "tools.import_live2d",
        ]
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # We don't ship the training pipeline; drop heavy ML/test stuff so
        # the bundle stays under ~400 MB.
        "torch",
        "torchaudio",
        "torchvision",
        "transformers",
        "pytest",
        "ruff",
        "pyinstaller",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="desktop-kanojo",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # console=True for the first build so users see tracebacks if something
    # crashes at startup. Once we're confident, switch to False for a clean
    # windowed launch.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="desktop-kanojo",
)
