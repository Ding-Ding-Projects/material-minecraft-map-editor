# -*- mode: python ; coding: utf-8 -*-

# python -m PyInstaller -y installer/Amulet.spec

from typing import TYPE_CHECKING
import sys
import os

# pyinstaller moves the current directory to the front
# We would prefer to find modules in site packages first
cwd = os.path.normcase(os.path.realpath(os.getcwd()))
sys.path = [path for path in sys.path if os.path.normcase(os.path.realpath(path)) != cwd]
sys.path.append(cwd)

import amulet_map_editor

if TYPE_CHECKING:
    from PyInstaller.building.build_main import Analysis
    from PyInstaller.building.api import PYZ, EXE, COLLECT
    from PyInstaller.building.osx import BUNDLE

is_windows = os.name == "nt"
sys.modules["FixTk"] = None

a = Analysis(
    [os.path.join(amulet_map_editor.__path__[0], "__main__.py")],
    binaries=[],
    datas=[],
    runtime_hooks=[],
    excludes=["FixTk", "tcl", "tk", "_tkinter", "tkinter", "Tkinter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="amulet",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # Amulet is a windowed application: a console here would flash a black
    # terminal over the user's work on every launch.
    console=False,
    # Declares per-monitor v2 DPI awareness (and asInvoker). Read by the Windows
    # loader before any Python runs, so the process is never briefly treated as
    # DPI-unaware; amulet_map_editor.api.dpi makes the same declaration for a
    # source checkout, which has no manifest.
    manifest="amulet.manifest",
    icon="logo.ico",
    contents_directory="lib",
    # macOS packaging is intentionally unsigned; never discover or invoke a
    # developer certificate from the build environment.
    codesign_identity=None,
    entitlements_file=None,
)
exe_debug = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="amulet_debug",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # The debug bundle exists to show diagnostics, so it keeps its console.
    # The shipped "amulet" executable above never opens one.
    console=True,
    icon="logo.ico",
    contents_directory="lib",
    # Keep the debug bundle under the same unsigned policy as the release app.
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    exe_debug,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="amulet",
)

app = BUNDLE(
    coll,
    name=f"Amulet {amulet_map_editor.__version__}.app",
    icon="logo.ico",
    bundle_identifier="com.amuletmc.amulet_map_editor",
)
