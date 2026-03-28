# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for CopySoft
# Usage:
#   Windows: pyinstaller copysoft.spec
#   macOS:   pyinstaller copysoft.spec

import sys
import os

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('core',   'core'),
        ('gui',    'gui'),
        ('assets', 'assets'),
    ],
    hiddenimports=[
        'PyQt5',
        'PyQt5.sip',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'PyQt5.QtNetwork',
        'core.drive_detect',
        'core.platform_io',
        'core.large_file',
        'core.small_files',
        'core.copy_engine',
        'gui.copy_worker',
        'gui.main_window',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'numpy', 'scipy', 'pandas',
        'PIL', 'cv2', 'sklearn', 'tensorflow',
        'tkinter', '_tkinter',
        'unittest', 'test',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='CopySoft',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,               # compress with UPX if available
    upx_exclude=[
        'vcruntime140.dll',
        'python3*.dll',
        'Qt5*.dll',
        'Qt6*.dll',
    ],
    runtime_tmpdir=None,
    console=False,          # windowed mode — no cmd window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Windows specific
    version=None,
    icon='assets/icon.ico',
)
