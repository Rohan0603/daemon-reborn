param(
    [string]$AssetRoot = (Join-Path $PSScriptRoot "..\assets"),
    [string]$ManifestPath
)

$ErrorActionPreference = "Stop"

if ($ManifestPath) {
    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
        throw "Asset manifest does not exist: $ManifestPath"
    }
    $manifests = @(Get-Item -LiteralPath $ManifestPath)
} elseif (-not (Test-Path -LiteralPath $AssetRoot -PathType Container)) {
    Write-Output "SKIP: no asset directory exists yet; the manifest is defined by the later asset issues."
    exit 0
} else {
    $manifests = @(
        Get-ChildItem -LiteralPath $AssetRoot -Filter "*manifest*.json" -File -Recurse
    )
}

if ($manifests.Count -eq 0) {
    Write-Output "SKIP: no JSON asset manifest exists yet; the manifest is defined by the later asset issues."
    exit 0
}

foreach ($manifest in $manifests) {
    try {
        $null = Get-Content -LiteralPath $manifest.FullName -Raw | ConvertFrom-Json -ErrorAction Stop
    } catch {
        throw "Invalid JSON asset manifest '$($manifest.FullName)': $($_.Exception.Message)"
    }
    Write-Output "Valid JSON asset manifest: $($manifest.FullName)"
}
