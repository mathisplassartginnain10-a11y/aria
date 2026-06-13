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

echo Copie des donnees vers dist\ARIA\ (a cote de ARIA.exe)...
copy /Y "config.yaml" "dist\ARIA\config.yaml" >nul
if exist "prompts" xcopy /E /I /Y "prompts" "dist\ARIA\prompts\" >nul
if exist "sounds" xcopy /E /I /Y "sounds" "dist\ARIA\sounds\" >nul
if exist "data" xcopy /E /I /Y "data" "dist\ARIA\data\" >nul
if exist "assets" xcopy /E /I /Y "assets" "dist\ARIA\assets\" >nul

echo.
echo ARIA.exe compile avec succes dans dist\ARIA\
