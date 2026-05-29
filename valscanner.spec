# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for ValScanner
# Build:
#   macOS / Linux : python -m PyInstaller valscanner.spec
#   Windows       : python -m PyInstaller valscanner.spec
#
# Or use the helper scripts:
#   bash scripts/build_app.sh [--dmg] [--sign "Developer ID Application: ..."]
#   .\scripts\build_app.ps1  [-Installer]

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"

ASSETS   = Path("assets")
APP_NAME = "ValScanner"
VERSION  = "0.2.4"
BUNDLE_ID = "com.valabji.valscanner"

block_cipher = None

# Pull in every valscanner sub-module so nothing is missed at runtime.
hidden = collect_submodules("valscanner")

# Collect web static assets (SPA build output)
_web_datas = collect_data_files('valscanner.web', includes=['static/**/*'])

# qtawesome ships its icon fonts as package data — bundle the .ttf + charmap .json files.
_qta_datas = collect_data_files('qtawesome', includes=['fonts/*'])

# Alembic migration files — needed by bootstrap.ensure_schema() at runtime.
_alembic_datas = [
    ("valscanner/alembic.ini", "valscanner"),
    ("valscanner/migrations", "valscanner/migrations"),
]

a = Analysis(
    ["app_entry.py"],
    pathex=["."],
    binaries=[],
    datas=_web_datas + _qta_datas + _alembic_datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Trim heavy stdlib extras that are never used.
    # Keep email, html, http, xml, xmlrpc — PySide6 may need them on Windows.
    excludes=["tkinter", "unittest", "doctest", "pdb", "difflib", "calendar",
              "matplotlib", "numpy", "scipy", "pandas"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── platform-specific EXE options ─────────────────────────────────────────────
_exe_extra = {}
if IS_WIN:
    _exe_extra["icon"]    = str(ASSETS / "icon.ico")
    _exe_extra["version"] = str(ASSETS / "windows_version_info.txt")
elif IS_MAC:
    _exe_extra["icon"] = str(ASSETS / "icon.icns")
else:
    _exe_extra["icon"] = str(ASSETS / "icon.png")

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,           # no terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    **_exe_extra,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)

# ── macOS: wrap the COLLECT output into a proper .app bundle ──────────────────
if IS_MAC:
    app = BUNDLE(  # noqa: F821  (PyInstaller global)
        coll,
        name=f"{APP_NAME}.app",
        icon=str(ASSETS / "icon.icns"),
        bundle_identifier=BUNDLE_ID,
        info_plist={
            "CFBundleName":                APP_NAME,
            "CFBundleDisplayName":         APP_NAME,
            "CFBundleVersion":             VERSION,
            "CFBundleShortVersionString":  VERSION,
            "CFBundleIconFile":            "icon",
            "NSHighResolutionCapable":     True,
            "NSRequiresAquaSystemAppearance": False,   # respects system dark/light
            "NSSupportsAutomaticGraphicsSwitching": True,
            "LSApplicationCategoryType":   "public.app-category.utilities",
            "NSHumanReadableCopyright":    "Copyright © 2026 Abdalrahman Valabji",
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName":       "ValScanner Database",
                    "CFBundleTypeExtensions": ["db"],
                    "CFBundleTypeRole":       "Editor",
                    "LSHandlerRank":          "Owner",
                }
            ],
        },
    )
