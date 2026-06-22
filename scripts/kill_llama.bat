@echo off
chcp 65001 >nul
echo Arret de tous les llama-server.exe...
taskkill /F /IM llama-server.exe
if errorlevel 1 (
  echo Aucun llama-server en cours.
) else (
  echo llama-server arrete.
)
pause
