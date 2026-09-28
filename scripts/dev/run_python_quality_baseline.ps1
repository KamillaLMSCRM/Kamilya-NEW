[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$gitCommonDirText = (& git -C $repoRoot rev-parse --path-format=absolute --git-common-dir).Trim()
if ($LASTEXITCODE -ne 0 -or -not $gitCommonDirText) {
    throw "Could not resolve the Git common directory for the Python quality runtime"
}
$gitCommonDir = (Resolve-Path -LiteralPath $gitCommonDirText).Path
$canonicalCheckout = Split-Path -Parent $gitCommonDir
$canonicalPython = Join-Path $canonicalCheckout ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $canonicalPython -PathType Leaf)) {
    throw "Canonical Python quality runtime is missing: $canonicalPython"
}

& $canonicalPython -m ruff --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Canonical Python quality runtime is incomplete: ruff is missing"
}
& $canonicalPython -m mypy --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Canonical Python quality runtime is incomplete: mypy is missing"
}

Push-Location -LiteralPath $repoRoot
try {
    & $canonicalPython scripts/ci/python_quality_baseline.py
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
