# install_shortcut.ps1 — Installe le raccourci ARIA dans le menu Démarrer

$ProjectDir = "c:\Users\mathi\OneDrive\Documents\assistant-ia\assistant-vocal"
$BatchFile = Join-Path $ProjectDir "launch_aria.bat"
$IconFile = Join-Path $ProjectDir "electron\assets\icon.ico"
$IconPng = Join-Path $ProjectDir "electron\assets\icon.png"
$FaviconFallback = Join-Path $ProjectDir "ui\favicon.ico"

# Générer icon.ico si absent
if (-not (Test-Path $IconFile)) {
    if (Test-Path $IconPng) {
        Copy-Item $IconPng $IconFile
        Write-Host "icon.ico créé depuis icon.png"
    } elseif (Test-Path $FaviconFallback) {
        Copy-Item $FaviconFallback $IconFile
        Write-Host "icon.ico créé depuis ui/favicon.ico"
    }
}

# Créer le raccourci dans le menu Démarrer
$StartMenuPath = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\ARIA.lnk"
$DesktopPath = "$env:USERPROFILE\Desktop\ARIA.lnk"

$WshShell = New-Object -ComObject WScript.Shell

foreach ($ShortcutPath in @($StartMenuPath, $DesktopPath)) {
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $BatchFile
    $Shortcut.WorkingDirectory = $ProjectDir
    $Shortcut.Description = "ARIA - Assistant Personnel IA"
    if (Test-Path $IconFile) {
        $Shortcut.IconLocation = $IconFile
    }
    $Shortcut.WindowStyle = 7  # Fenêtre minimisée (cache la console)
    $Shortcut.Save()
    Write-Host "Raccourci créé: $ShortcutPath"
}

Write-Host ""
Write-Host "ARIA ajouté au menu Démarrer et au Bureau"
Write-Host "   Tu peux maintenant taper ARIA dans la recherche Windows"
