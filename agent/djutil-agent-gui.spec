# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the windowed 'DJUtil Agent' tray build.

Windows -> a --noconsole exe; macOS -> a .app bundle (LSUIElement, no Dock
icon). Started without arguments it runs `tray` (see gui_entry.py).
"""

import sys

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []

for pkg in ("pyrekordbox", "sqlcipher3", "pystray", "PIL"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

icon = (
    "assets/icon.icns" if sys.platform == "darwin" else "assets/icon.ico"
)

a = Analysis(
    ["gui_entry.py"],
    pathex=["src", "."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
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
    name="DJUtil Agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon,
)

if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="DJUtil Agent.app",
        icon="assets/icon.icns",
        bundle_identifier="com.djutil.agent",
        info_plist={
            "LSUIElement": True,  # agent app: no Dock icon
            "CFBundleShortVersionString": "0.1.0",
        },
    )
