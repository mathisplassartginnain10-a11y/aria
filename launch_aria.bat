@echo off
title ARIA
cd /d "c:\Users\mathi\OneDrive\Documents\assistant-ia\assistant-vocal"

REM Tuer les instances précédentes
taskkill /f /im python.exe >nul 2>&1
taskkill /f /im electron.exe >nul 2>&1
timeout /t 1 >nul

REM Supprimer le port file précédent
del "%TEMP%\aria_ws_port.json" >nul 2>&1

REM Lancer Python en arrière-plan (fenêtre cachée)
start /min "" cmd /c ".\.venv\Scripts\python.exe python\main.py > "%TEMP%\aria_python.log" 2>&1"

REM Attendre que le backend soit prêt (port file créé)
:WAIT_BACKEND
timeout /t 1 >nul
if not exist "%TEMP%\aria_ws_port.json" goto WAIT_BACKEND

REM Attendre encore 1s pour que le WebSocket soit bien actif
timeout /t 1 >nul

REM Lancer Electron
cd electron
start "" node_modules\.bin\electron.cmd .
