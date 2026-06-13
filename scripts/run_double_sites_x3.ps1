# Double le catalogue de sites ARIA (×3 consécutifs)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..
$env:PYTHONIOENCODING = "utf-8"
& .\.venv\Scripts\python.exe scripts\double_sites.py --repeat 3
