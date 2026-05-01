# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


ROOT = Path(__file__).resolve().parent

datas = collect_data_files("imageio_ffmpeg")

hiddenimports = [
    "imageio.plugins.ffmpeg",
    "imageio_ffmpeg",
]

excludes = [
    "torch",
    "torchvision",
    "torchaudio",
    "transformers",
    "bitsandbytes",
    "gradio",
    "pandas",
    "sympy",
    "matplotlib",
    "jupyter",
    "IPython",
]


a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KFPlayer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="KFPlayer",
)
