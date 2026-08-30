# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

root = Path(SPECPATH).parent

a = Analysis(
    [str(root / "scripts" / "frozen_entry.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=[
        (str(root / "resources"), "resources"),
        (str(root / "migrations"), "migrations"),
        (str(root / "THIRD_PARTY_LICENSES.md"), "."),
    ],
    hiddenimports=["PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "openpyxl", "xlrd", "reportlab"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="KajovoKarty",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(root / "resources" / "icons" / "kajovokarty.ico"),
    target_arch="x86_64",
)
