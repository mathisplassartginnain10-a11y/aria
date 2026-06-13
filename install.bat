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
