@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo === Mise a jour ARIA ===
echo.
echo [1/4] git pull origin main...
git pull origin main
if errorlevel 1 (
  echo ERREUR git pull
  pause
  exit /b 1
)
echo.
echo [2/4] pip install...
if exist ".venv\Scripts\python.exe" (
  .venv\Scripts\python.exe -m pip install -r requirements.txt -q
) else (
  python -m pip install -r requirements.txt -q
)
echo.
echo [3/4] npm install...
cd electron
call npm install --silent
cd ..
echo.
echo [4/4] Nettoyage cache Electron...
if exist "%LOCALAPPDATA%\electron\Cache" rmdir /s /q "%LOCALAPPDATA%\electron\Cache" 2>nul
if exist "%APPDATA%\electron\Cache" rmdir /s /q "%APPDATA%\electron\Cache" 2>nul
echo.
echo Mise a jour terminee — relancez ARIA
pause
