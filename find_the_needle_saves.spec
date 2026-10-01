# PyInstaller spec - build with:  pyinstaller find_the_needle_saves.spec
# Bundles Python + PySide6 + locale files into one self-contained client.

from pathlib import Path

ROOT = Path(SPECPATH)
SRC = ROOT / "src"

datas = [
    (str(SRC / "needle_saves" / "locales"), "needle_saves/locales"),
]

a = Analysis(
    [str(SRC / "needle_saves" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=["PySide6.QtWidgets", "PySide6.QtCore", "PySide6.QtGui"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="find-the-needle-saves",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # windowed app, no console
    icon=None,              # drop an .ico here later if desired
)
