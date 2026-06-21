# install_shortcut.ps1 — Installe le raccourci ARIA dans le menu Démarrer

$ProjectDir = "c:\Users\mathi\OneDrive\Documents\assistant-ia\assistant-vocal"
$BatchFile = Join-Path $ProjectDir "launch_aria.bat"
$IconFile = Join-Path $ProjectDir "electron\assets\icon.ico"

if (-not (Test-Path $IconFile)) {
    Write-Host "icon.ico absent - lance scripts\create_electron_assets.py d abord"
    exit 1
}

# Créer le raccourci dans le menu Démarrer et sur le Bureau
$StartMenuPath = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\ARIA.lnk"
$DesktopPath = "$env:USERPROFILE\Desktop\ARIA.lnk"

$WshShell = New-Object -ComObject WScript.Shell

foreach ($ShortcutPath in @($StartMenuPath, $DesktopPath)) {
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $BatchFile
    $Shortcut.WorkingDirectory = $ProjectDir
    $Shortcut.Description = "ARIA - Assistant Personnel IA"
    $Shortcut.IconLocation = "$IconFile,0"
    $Shortcut.WindowStyle = 7  # Fenêtre minimisée (cache la console)
    $Shortcut.Save()
    Write-Host "Raccourci créé: $ShortcutPath"
}

Write-Host ""
Write-Host "ARIA ajouté au menu Démarrer et au Bureau (icône: $IconFile)"
