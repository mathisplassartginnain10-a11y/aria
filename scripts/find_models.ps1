# scripts/find_models.ps1
# Liste les modèles GGUF disponibles (blobs Ollama)

$manifestsPath = "$env:USERPROFILE\.ollama\models\manifests\registry.ollama.ai\library"
$blobsPath = "$env:USERPROFILE\.ollama\models\blobs"

Write-Host "=== Modèles GGUF disponibles ===" -ForegroundColor Cyan

if (-not (Test-Path $manifestsPath)) {
    Write-Host "Aucun modèle Ollama trouvé dans $manifestsPath" -ForegroundColor Red
    exit
}

Get-ChildItem $manifestsPath -Recurse -File | ForEach-Object {
    try {
        $manifest = Get-Content $_.FullName -Raw | ConvertFrom-Json
        $layers = $manifest.layers | Where-Object { $_.mediaType -eq "application/vnd.ollama.image.model" }
        if ($layers) {
            $hash = $layers[0].digest -replace "sha256:", "sha256-"
            $blobFile = Join-Path $blobsPath $hash
            if (Test-Path $blobFile) {
                $sizGo = [math]::Round((Get-Item $blobFile).Length / 1GB, 2)
                $modelName = "$($_.Directory.Name):$($_.Name)"
                Write-Host "`n$modelName" -ForegroundColor Green
                Write-Host "  Taille : $sizGo Go"
                Write-Host "  Chemin : $blobFile"
            }
        }
    } catch {}
}
Write-Host "`n=== Fin ===" -ForegroundColor Cyan
