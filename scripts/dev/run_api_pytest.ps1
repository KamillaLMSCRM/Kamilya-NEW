[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$apiRoot = Join-Path $repoRoot "apps\api"
$gitCommonDirText = (& git -C $repoRoot rev-parse --path-format=absolute --git-common-dir).Trim()
if ($LASTEXITCODE -ne 0 -or -not $gitCommonDirText) {
    throw "Could not resolve the Git common directory for the API test runtime"
}
$gitCommonDir = (Resolve-Path -LiteralPath $gitCommonDirText).Path
$canonicalCheckout = Split-Path -Parent $gitCommonDir
$canonicalPython = Join-Path $canonicalCheckout ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $canonicalPython -PathType Leaf)) {
    throw "Canonical API test runtime is missing: $canonicalPython"
}

& $canonicalPython -c "import pytest, pytest_asyncio" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Canonical API test runtime is incomplete: pytest/pytest_asyncio import failed"
}

$normalizedArgs = @(
foreach ($argument in $PytestArgs) {
    if ($argument -match '^apps[\\/]api[\\/](.+)$') {
        $matches[1]
    }
    elseif ($argument -match '^scripts[\\/]') {
        $selectorParts = $argument -split '::', 2
        $absolutePath = Join-Path $repoRoot $selectorParts[0]
        if ($selectorParts.Count -eq 2) {
            "${absolutePath}::$($selectorParts[1])"
        }
        else {
            $absolutePath
        }
    }
    else {
        $argument
    }
}
)

$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $apiRoot, $repoRoot -join [IO.Path]::PathSeparator
    Push-Location -LiteralPath $apiRoot
    try {
        & $canonicalPython -m pytest @normalizedArgs
        exit $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}
