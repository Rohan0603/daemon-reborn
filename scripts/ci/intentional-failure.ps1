$ErrorActionPreference = "Stop"
Write-Output "Intentional CI failure probe: this job must fail when explicitly enabled."
exit 1
