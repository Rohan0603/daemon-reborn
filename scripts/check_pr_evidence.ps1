$ErrorActionPreference = "Stop"

# Narrow migration exception: bridge the legacy ORC-key PR gate to its already
# migrated GitHub governance issue. This applies only to the exact migration
# branch/title and must not relax evidence checks for normal product PRs.
$governanceMigration = (
    $env:PR_HEAD_REF -eq "governance/20261109-chief-worker-migration" -and
    $env:PR_TITLE -like "governance: adopt GitHub Chief/Worker template*" -and
    $env:PR_BODY -match "https://github\\.com/Rohan0603/daemon-reborn/issues/94\\b"
)
if ($governanceMigration) {
    if ($env:PR_BODY -notmatch "(?im)^#{1,6}\\s+(Verification|Testing)\\b") {
        throw "Governance migration PR must have a Verification or Testing evidence section."
    }
    Write-Output "Governance migration evidence linked to GitHub Issue #94."
    exit 0
}

$issueUrl = [regex]::Match(
    $env:PR_BODY,
    "https://linear\.app/agtorchestrator/issue/(ORC-\d+)",
    [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
)
if (-not $issueUrl.Success) {
    throw "PR body must link a Linear ORC issue."
}

$issueKey = $issueUrl.Groups[1].Value.ToUpperInvariant()
$titleIssue = [regex]::Match(
    $env:PR_TITLE,
    "ORC-\d+",
    [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
)
if (-not $titleIssue.Success -or $titleIssue.Value.ToUpperInvariant() -ne $issueKey) {
    throw "PR title must include the same ORC key as its Linear issue link ($issueKey)."
}

$branchIssue = [regex]::Match(
    $env:PR_HEAD_REF,
    "ORC-\d+",
    [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
)
if (-not $branchIssue.Success -or $branchIssue.Value.ToUpperInvariant() -ne $issueKey) {
    throw "PR branch must include the same ORC key as its Linear issue link ($issueKey)."
}

if ($env:PR_BODY -notmatch "(?im)^#{1,6}\s+(Verification|Testing)\b") {
    throw "PR body must include a Verification or Testing section with command results."
}

Write-Output "PR evidence links to $issueKey and includes verification results."
