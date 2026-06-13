# Assistant Vocal — Spec v5 : Conversion en vraie application Windows (.exe)

## Problème actuel
Le script Python ne peut pas intercepter les touches globalement de façon fiable sur Windows 11 car il n'est pas reconnu comme une vraie application Windows. Il faut compiler le projet en `.exe` avec `uac_admin=True` pour que le hook clavier F24 fonctionne systématiquement.

---

## Objectif
Transformer le projet en `ARIA.exe` — une vraie application Windows qui :
- Se lance au boot automatiquement
- Tourne sans terminal visible
- Intercepte F24 globalement sans problème
- S'installe en un double-clic sur `install.bat`

---

## Nouveaux fichiers à créer

```
assistant-vocal/
├── build.spec              # Config PyInstaller
├── build.bat               # Lance la compilation
├── install.bat             # MIS À JOUR — inclut build + shortcut
├── assets/
│   └── aria.ico            # Icône de l'app (générer une icône simple bleue si absente)
└── dist/
    └── ARIA/               # Résultat de la compilation
        └── ARIA.exe        # L'exécutable final
```

---

## build.spec

```python
# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[str(Path('.').resolve())],
    binaries=[],
    datas=[
        ('config.yaml', '.'),
        ('prompts', 'prompts'),
        ('sounds', 'sounds'),
        ('data', 'data'),
        ('assets', 'assets'),
    ],
    hiddenimports=[
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
    runtime_hooks=[],
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
    console=False,          # Pas de fenêtre terminal
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,         # Droits admin automatiques au lancement
    icon='assets/aria.ico' if Path('assets/aria.ico').exists() else None,
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
```

---

## build.bat

```bat
@echo off
cd /d "%~dp0"
echo Construction de ARIA.exe...
call .venv\Scripts\activate.bat

echo Installation PyInstaller...
pip install pyinstaller --quiet

echo Generation de l'icone...
python generate_icon.py

echo Compilation en cours (peut prendre 2-3 minutes)...
pyinstaller build.spec --clean --noconfirm

if errorlevel 1 (
    echo ERREUR : La compilation a echoue.
    pause
    exit /b 1
)

echo.
echo ARIA.exe compile avec succes dans dist\ARIA\
```

---

## generate_icon.py

Génère une icône `.ico` simple si elle n'existe pas :

```python
from pathlib import Path

def generate_icon():
    assets_dir = Path("assets")
    assets_dir.mkdir(exist_ok=True)
    ico_path = assets_dir / "aria.ico"
    
    if ico_path.exists():
        return
    
    try:
        from PIL import Image, ImageDraw, ImageFont
        
        sizes = [16, 32, 48, 64, 128, 256]
        images = []
        
        for size in sizes:
            img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            
            # Fond cercle bleu foncé
            margin = size // 8
            draw.ellipse(
                [margin, margin, size - margin, size - margin],
                fill=(8, 8, 16, 255),
                outline=(74, 158, 255, 255),
                width=max(1, size // 16)
            )
            
            # Lettre A au centre
            font_size = size // 2
            try:
                font = ImageFont.truetype("consola.ttf", font_size)
            except:
                font = ImageFont.load_default()
            
            text = "A"
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            x = (size - text_w) // 2
            y = (size - text_h) // 2
            draw.text((x, y), text, fill=(74, 158, 255, 255), font=font)
            
            images.append(img)
        
        images[0].save(
            ico_path,
            format='ICO',
            sizes=[(s, s) for s in sizes],
            append_images=images[1:]
        )
        print(f"Icône générée : {ico_path}")
        
    except ImportError:
        # PIL pas dispo, crée une icône minimale
        print("PIL absent, icône par défaut utilisée")

if __name__ == "__main__":
    generate_icon()
```

---

## install.bat — Version finale complète

```bat
@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Installation ARIA Assistant

:: Elevation admin
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Elevation des privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo.
echo ====================================
echo    Installation ARIA Assistant
echo ====================================
echo.

:: Etape 1 : Venv
echo [1/6] Creation de l environnement Python...
if not exist ".venv" (
    python -m venv .venv
    if errorlevel 1 (
        echo ERREUR : Python introuvable. Installez Python 3.10+ depuis python.org
        pause & exit /b 1
    )
)
call .venv\Scripts\activate.bat

:: Etape 2 : Dependances
echo [2/6] Installation des dependances...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERREUR lors de pip install
    pause & exit /b 1
)

:: Etape 3 : Playwright
echo [3/6] Installation Playwright + Chromium...
pip install playwright --quiet
playwright install chromium
if errorlevel 1 (
    echo AVERTISSEMENT : Playwright non installe, controle navigateur indisponible
)

:: Etape 4 : Compilation exe
echo [4/6] Compilation ARIA.exe (2-3 minutes)...
call build.bat
if errorlevel 1 (
    echo ERREUR : Compilation echouee
    pause & exit /b 1
)

:: Etape 5 : Demarrage auto
echo [5/6] Configuration demarrage automatique...
python setup_autostart.py --silent --exe
if errorlevel 1 (
    echo AVERTISSEMENT : Demarrage auto non configure
)

:: Etape 6 : Raccourcis
echo [6/6] Creation des raccourcis...
python create_shortcut.py --silent
if errorlevel 1 (
    echo AVERTISSEMENT : Raccourcis non crees
)

echo.
echo ====================================
echo    Installation terminee !
echo ====================================
echo.
echo ARIA demarre maintenant...
echo Appuyez sur F24 pour ouvrir l interface.
echo.

:: Lancement ARIA
start "" "dist\ARIA\ARIA.exe"
exit /b 0
```

---

## Mise à jour setup_autostart.py

Ajouter le flag `--exe` pour pointer vers `ARIA.exe` au lieu de `pythonw main.py` :

```python
import sys

use_exe = '--exe' in sys.argv

if use_exe:
    # Pointe vers ARIA.exe compilé
    exe_path = working_dir / "dist" / "ARIA" / "ARIA.exe"
    command = str(exe_path)
    arguments = ""
else:
    # Pointe vers pythonw (développement)
    python_exe = sys.executable.replace("python.exe", "pythonw.exe")
    command = python_exe
    arguments = f'"{script_path}"'
```

---

## Mise à jour create_shortcut.py

Pointer vers `dist\ARIA\ARIA.exe` en priorité, fallback sur `start.bat` :

```python
from pathlib import Path

exe_path = Path(__file__).parent / "dist" / "ARIA" / "ARIA.exe"
bat_path = Path(__file__).parent / "start.bat"

target = str(exe_path) if exe_path.exists() else str(bat_path)
```

---

## Points critiques PyInstaller

- `uac_admin=True` dans le spec → Windows demande les droits admin au lancement automatiquement, une bonne fois pour toutes
- `console=False` → aucun terminal visible, ARIA tourne silencieusement
- `onedir` (pas `onefile`) → plus stable, moins d'antivirus false positives
- Après compilation, tout est dans `dist/ARIA/` — ne pas déplacer `ARIA.exe` seul sans le reste du dossier
- Les fichiers `config.yaml`, `prompts/`, `sounds/`, `data/` sont embarqués dans l'exe via `datas`
- Pour modifier `config.yaml` après compilation : éditer `dist/ARIA/config.yaml`

---

## Mise à jour requirements.txt (ajouter)

```
pyinstaller
Pillow
```

---

## Prompt Cursor

> The voice assistant project is fully implemented (v2+v3+v4). The current problem is that the Python script cannot reliably intercept global hotkeys on Windows 11. The solution is to compile the project into a real Windows executable using PyInstaller with uac_admin=True.
>
> Create these files exactly as described in the attached spec:
> 1. `build.spec` — PyInstaller spec with uac_admin=True, console=False, all hidden imports, all data files included
> 2. `build.bat` — installs PyInstaller, runs generate_icon.py, runs pyinstaller build.spec
> 3. `generate_icon.py` — generates assets/aria.ico using Pillow (blue circle with letter A), fallback if PIL absent
> 4. Update `install.bat` — full 6-step process: venv, pip, playwright, build exe, autostart, shortcuts, then launch dist/ARIA/ARIA.exe
> 5. Update `setup_autostart.py` — add --exe flag to point Task Scheduler to dist/ARIA/ARIA.exe instead of pythonw
> 6. Update `create_shortcut.py` — point to dist/ARIA/ARIA.exe if it exists
>
> After install.bat runs, the user must have ARIA.exe that:
> - Runs as admin automatically (uac_admin=True)
> - Has no visible terminal window (console=False)
> - Auto-starts at Windows boot via Task Scheduler
> - Has a desktop shortcut and taskbar shortcut
> - Intercepts F24 globally without any Python dependency
>
> Only create/modify: build.spec, build.bat, generate_icon.py, install.bat, setup_autostart.py, create_shortcut.py, requirements.txt
> No placeholders. Every file fully implemented.
