# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec
#   macOS  → onedir → dist/Fast_Copy.app  (proper app bundle)
#   Windows → onefile → dist/Fast_Copy.exe (single portable exe)

import sys
import os

block_cipher = None
IS_MAC = sys.platform == 'darwin'

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
        'core.win_long_path',
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
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── macOS: onedir mode (required for proper .app bundle) ─────────────────
if IS_MAC:
    exe = EXE(
        pyz,
        a.scripts,
        [],                     # binaries/datas go into the bundle, not the exe
        exclude_binaries=True,  # onedir: keep binaries separate
        name='Fast_Copy',
        debug=False,
        strip=False,
        upx=False,
        console=False,
        icon='assets/icon.icns',
        argv_emulation=False,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        name='Fast_Copy',
    )
    app = BUNDLE(
        coll,
        name='Fast_Copy.app',
        icon='assets/icon.icns',
        bundle_identifier='com.ahsocode.fastcopy',
        info_plist={
            'CFBundleName':               'Fast_Copy',
            'CFBundleDisplayName':        'Fast Copy',
            'CFBundleShortVersionString': '1.0.0',
            'CFBundleVersion':            '1.0.0',
            'NSHumanReadableCopyright':   '© 2025 ahsocode',
            'NSHighResolutionCapable':    True,
            'NSRequiresAquaSystemAppearance': False,
            'LSMinimumSystemVersion':     '11.0',
        },
    )

# ── Windows: onefile mode (single portable exe) ───────────────────────────
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name='Fast_Copy',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=['vcruntime140.dll', 'python3*.dll', 'Qt5*.dll', 'Qt6*.dll'],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon='assets/icon.ico',
    )
