# Installation des dépendances audio pour ARIA (STT / microphone)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Error "Python venv introuvable: $Python"
}

& $Python -m pip install `
    faster-whisper pyaudio sounddevice SpeechRecognition `
    numpy scipy pywin32

Write-Host "Installation audio terminée ✓" -ForegroundColor Green
Write-Host ""
Write-Host "Étapes manuelles Windows :" -ForegroundColor Yellow
Write-Host "  1. Ouvrir Paramètres > Confidentialité > Microphone"
Write-Host "  2. Activer l'accès micro pour les applications"
Write-Host "  3. Activer l'accès micro pour les applications de bureau"
Write-Host "  4. Relancer ARIA complètement"
Start-Process "ms-settings:privacy-microphone"
