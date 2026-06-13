# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

block_cipher = None
PROJECT = Path(SPECPATH)

# datas : config.yaml à la racine du bundle ; dossiers conservés pour sounds/prompts/data
# build.bat copie ensuite tout vers dist/ARIA/ (à côté de ARIA.exe)
datas = [
    (str(PROJECT / 'config.yaml'), '.'),
    (str(PROJECT / 'prompts'), 'prompts'),
    (str(PROJECT / 'sounds'), 'sounds'),
    (str(PROJECT / 'ui'), 'ui'),
]
for name in ('memory.json', 'history.json', 'timers.json', 'presets.json', 'ui_state.json'):
    path = PROJECT / 'data' / name
    if path.exists():
        datas.append((str(path), 'data'))
if (PROJECT / 'assets').exists():
    datas.append((str(PROJECT / 'assets'), 'assets'))

a = Analysis(
    [str(PROJECT / 'main.py')],
    pathex=[str(PROJECT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'app_paths',
        'webview',
        'webview.platforms.winforms',
        'faster_whisper',
        'sounddevice',
        'pygame',
        'pygame.mixer',
        'edge_tts',
        'keyboard',
        'pycaw',
        'pycaw.pycaw',
        'comtypes',
        'comtypes.client',
        'playwright',
        'playwright.sync_api',
        'psutil',
        'pyautogui',
        'pygetwindow',
        'duckduckgo_search',
        'actions.search',
        'actions.web_search',
        'sympy',
        'scipy',
        'scipy.stats',
        'numpy',
        'watchdog',
        'winshell',
        'win32com',
        'win32com.client',
        'win32gui',
        'win32con',
        'yaml',
        'requests',
        'asyncio',
        'tkinter',
        'tkinter.ttk',
        'tkinter.font',
        'logging.handlers',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(PROJECT / 'runtime_hook.py')],
    excludes=['matplotlib', 'IPython', 'jupyter'],
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
    name='ARIA',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon='assets/aria.ico',
    manifest='assets/aria.manifest',
    version='version_info.txt',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ARIA',
)
