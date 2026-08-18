# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for IBL Pressure.

One folder, one window, no console:
    pyinstaller IBLpressure.spec --noconfirm

Output lands in  dist\IBLpressure\  -- copy that whole folder to the
control PC and run IBLpressure.exe inside it.
"""

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'pyqtgraph.graphicsItems.DateAxisItem',
        'labjack',
        'labjack.ljm',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Qt ships a lot we never touch; dropping it keeps the folder small.
    excludes=[
        'tkinter', 'matplotlib', 'scipy', 'pandas', 'IPython',
        'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
        'PySide6.QtQuick', 'PySide6.QtQml', 'PySide6.Qt3DCore',
        'PySide6.QtMultimedia', 'PySide6.QtBluetooth', 'PySide6.QtNetworkAuth',
        'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtPdf',
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
    [],
    exclude_binaries=True,
    name='IBLpressure',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # no black console window behind the GUI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='IBLpressure',     # --onedir: dist\IBLpressure\IBLpressure.exe
)
