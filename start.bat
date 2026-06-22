@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM Nettoyer les llama-server orphelins d'une session précédente
taskkill /F /IM llama-server.exe >nul 2>&1

echo === Demarrage ARIA backend ===
.\.venv\Scripts\python.exe python\main.py
set EXIT_CODE=%ERRORLEVEL%

REM Toujours tuer llama-server a la sortie (Ctrl+C, crash, fermeture)
taskkill /F /IM llama-server.exe >nul 2>&1

exit /b %EXIT_CODE%
