# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Strix Pulse Monitor (Windows). Build: see build.bat.
block_cipher = None

a = Analysis(
    ['..\\pulse_monitor.py'],
    pathex=[],
    binaries=[],
    datas=[('..\\i18n', 'i18n')],   # bundle the 13-language UI translations
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name='Strix Pulse Monitor',
    debug=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,          # GUI app: no console window
    icon='pulse.ico',
)
