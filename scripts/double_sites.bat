@echo off
cd /d "%~dp0.."
if "%~1"=="" (
  .venv\Scripts\python.exe scripts\double_sites.py
) else (
  .venv\Scripts\python.exe scripts\double_sites.py --repeat %~1
)
pause
