@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title ARIA Mobile Server

if not exist ".venv\Scripts\python.exe" (
    echo Environnement .venv introuvable. Lance install.bat d'abord.
    pause
    exit /b 1
)

echo.
echo  Demarrage du serveur mobile ARIA...
echo  Connecte ton telephone sur le meme WiFi.
echo.

.venv\Scripts\python.exe aria_mobile_server.py
pause
