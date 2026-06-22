# fix_cuda_dlls.ps1 — Copie les DLLs CUDA dans C:\llama.cpp\
# Lance en admin si nécessaire

$LlamaDir = "C:\llama.cpp"
$CudaPaths = @(
    "$env:CUDA_PATH\bin",
    "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.9\bin",
    "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.4\bin",
    "C:\Windows\System32"
)

$DllNames = @(
    "cudart64_12.dll", "cudart64_120.dll",
    "cublas64_12.dll", "cublas64_120.dll",
    "cublasLt64_12.dll", "cublasLt64_120.dll"
)

if (-not (Test-Path $LlamaDir)) {
    New-Item -ItemType Directory -Path $LlamaDir -Force | Out-Null
}

$Copied = 0
foreach ($dll in $DllNames) {
    $dest = Join-Path $LlamaDir $dll
    if (Test-Path $dest) { continue }

    foreach ($cudaPath in $CudaPaths) {
        if (-not $cudaPath) { continue }
        $src = Join-Path $cudaPath $dll
        if (Test-Path $src) {
            Copy-Item $src $dest -Force
            Write-Host "Copié: $dll" -ForegroundColor Green
            $Copied++
            break
        }
    }
}

Write-Host ""
if ($Copied -gt 0) {
    Write-Host "$Copied DLL(s) CUDA copiées dans $LlamaDir" -ForegroundColor Green
    Write-Host "Relance ARIA pour activer le GPU." -ForegroundColor Cyan
} else {
    Write-Host "Aucune DLL copiée — CUDA déjà configuré ou introuvable." -ForegroundColor Yellow
    Write-Host "Vérifie que CUDA Toolkit est installé." -ForegroundColor Yellow
}
