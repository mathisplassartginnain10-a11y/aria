@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo.
echo  Build APK ARIA Mobile (EAS Cloud)
echo  ==================================
echo.

where npm >nul 2>&1
if errorlevel 1 (
    echo Node.js / npm introuvable. Installe Node.js 18+.
    pause
    exit /b 1
)

if not exist "node_modules\" (
    echo Installation des dependances...
    call npm install
)

where eas >nul 2>&1
if errorlevel 1 (
    echo Installation EAS CLI...
    call npm install -g eas-cli
)

echo Lancement du build APK preview...
call npm run build:apk
pause
