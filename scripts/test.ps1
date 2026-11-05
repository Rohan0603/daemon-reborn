param(
    [ValidateSet("full", "unit")]
    [string]$Profile = "full",
    [string]$ArtifactRoot = (Join-Path $PSScriptRoot "..\\ci-artifacts")
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $ArtifactRoot | Out-Null
Set-Content -Path (Join-Path $ArtifactRoot "profile.log") -Value "profile=$Profile"

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $logPath = Join-Path $ArtifactRoot "$Name.log"
    Write-Output "=== $Name ==="
    & uv @Arguments 2>&1 | Tee-Object -FilePath $logPath
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "$Name failed with exit code $exitCode"
    }
}

Invoke-CheckedCommand -Name "uv-sync" -Arguments @("sync", "--locked")
if ($Profile -eq "unit") {
    Invoke-CheckedCommand -Name "pytest" -Arguments @("run", "pytest", "-q", "tests/unit")
} else {
    Invoke-CheckedCommand -Name "pytest" -Arguments @("run", "pytest", "-q")
}
Invoke-CheckedCommand -Name "ruff-check" -Arguments @("run", "ruff", "check", ".")
Invoke-CheckedCommand -Name "ruff-format" -Arguments @("run", "ruff", "format", "--check", ".")
Invoke-CheckedCommand -Name "mypy" -Arguments @("run", "mypy")
Invoke-CheckedCommand -Name "cli-help" -Arguments @("run", "python", "-m", "daemon_reborn", "--help")
