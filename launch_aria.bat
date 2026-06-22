@echo off
title ARIA
cd /d "c:\Users\mathi\OneDrive\Documents\assistant-ia\assistant-vocal"

echo.
echo  === Demarrage ARIA ===
echo.

REM Tuer les instances Electron precedentes (pas python — evite de tuer le backend en cours)
taskkill /f /im electron.exe >nul 2>&1

REM Nettoyer llama-server orphelins
taskkill /f /im llama-server.exe >nul 2>&1

REM Supprimer le port file precedent
del "%TEMP%\aria_ws_port.json" >nul 2>&1

echo  [1/2] Backend Python...
start /min "" cmd /c ".\.venv\Scripts\python.exe python\main.py > "%TEMP%\aria_python.log" 2>&1"

REM Attendre le port WebSocket (max 30 secondes)
set /a WAIT=0
:WAIT_BACKEND
if exist "%TEMP%\aria_ws_port.json" goto BACKEND_READY
timeout /t 1 >nul
set /a WAIT+=1
if %WAIT% geq 30 goto BACKEND_TIMEOUT
echo       En attente du backend... %WAIT%s
goto WAIT_BACKEND

:BACKEND_TIMEOUT
echo.
echo  ERREUR: backend Python ne repond pas apres 30s.
echo  Voir le log: %TEMP%\aria_python.log
pause
exit /b 1

:BACKEND_READY
echo       Backend pret (%WAIT%s)
timeout /t 1 >nul

echo  [2/2] Interface Electron...
cd electron
start "" node_modules\.bin\electron.cmd .
echo.
echo  ARIA lance. Si la fenetre n'apparait pas, verifie la barre des taches.
exit /b 0
