Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\ARIA.lnk" -ErrorAction SilentlyContinue
Remove-Item "$env:USERPROFILE\Desktop\ARIA.lnk" -ErrorAction SilentlyContinue
Write-Host "Raccourcis ARIA supprimés"
