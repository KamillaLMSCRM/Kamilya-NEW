[CmdletBinding()]
param(
    [ValidateSet("all", "migration", "tests")]
    [string]$Mode = "all"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ContainerName = "kamilya-postgres18-compat"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$ApiRoot = Join-Path $RepoRoot "apps/api"
$DatabaseName = "kamilya_step1_$PID"
$DatabaseUrl = $null
$DatabaseCreated = $false

function Write-SanitizedOutput {
    param([Parameter(ValueFromPipeline = $true)]$InputObject)

    process {
        $line = [string]$InputObject
        $line = $line -replace '(?i)postgres(?:ql)?(?:\+asyncpg)?://[^\s\]\)]+', '[REDACTED_DATABASE_URL]'
        $line = $line -replace '(?i)(password\s*[=:]\s*)\S+', '$1[REDACTED]'
        Write-Output $line
    }
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Program,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )

    Push-Location $WorkingDirectory
    try {
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & $Program @Arguments 2>&1 | Write-SanitizedOutput
        $programExitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousErrorActionPreference
        if ($programExitCode -ne 0) {
            throw "$Program failed with exit code $programExitCode"
        }
    }
    finally {
        Pop-Location
    }
}

function Get-ContainerEnvironment {
    $state = (& docker inspect --format '{{.State.Running}}' $ContainerName 2>$null).Trim()
    if ($LASTEXITCODE -ne 0 -or $state -ne "true") {
        throw "Required local container '$ContainerName' is not running."
    }

    $bindings = & docker inspect --format '{{json .HostConfig.PortBindings}}' $ContainerName
    if ($LASTEXITCODE -ne 0 -or $bindings -notmatch '5432/tcp') {
        throw "Local PG18 container does not publish its PostgreSQL port."
    }

    $values = @{}
    & docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' $ContainerName | ForEach-Object {
        if ($_ -match '^(POSTGRES_USER|POSTGRES_PASSWORD|POSTGRES_DB)=(.*)$') {
            $values[$Matches[1]] = $Matches[2]
        }
    }

    foreach ($name in @("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")) {
        if (-not $values.ContainsKey($name) -or [string]::IsNullOrWhiteSpace($values[$name])) {
            throw "Container is missing required PostgreSQL environment metadata."
        }
    }

    if ($values["POSTGRES_USER"] -notmatch '^[A-Za-z0-9_]+$') {
        throw "Unsafe PostgreSQL user metadata."
    }

    return $values
}

function Invoke-CatalogScalar {
    param(
        [Parameter(Mandatory = $true)][string]$Sql,
        [Parameter(Mandatory = $true)][string]$Expected
    )

    $result = (& docker exec $ContainerName psql `
        -U $containerEnv["POSTGRES_USER"] -d $DatabaseName `
        -v ON_ERROR_STOP=1 -Atqc $Sql 2>&1 | Write-SanitizedOutput)
    if ($LASTEXITCODE -ne 0) {
        throw "Sanitized PostgreSQL catalog assertion failed."
    }
    $actual = (($result | ForEach-Object { [string]$_ }) -join "`n").Trim()
    if ($actual -ne $Expected) {
        throw "PostgreSQL catalog assertion did not match its closed expected value."
    }
}

function Assert-PreviewCatalogContract {
    Invoke-CatalogScalar -Sql @"
SELECT c.relrowsecurity::text || '|' || c.relforcerowsecurity::text
FROM pg_class AS c
WHERE c.oid = 'public.ai_editor_request_previews'::regclass
"@ -Expected "true|true"

    Invoke-CatalogScalar -Sql @"
SELECT string_agg(p.cmd, ',' ORDER BY p.cmd)
FROM pg_policies AS p
WHERE p.schemaname = 'public' AND p.tablename = 'ai_editor_request_previews'
"@ -Expected "INSERT,SELECT,UPDATE"

    Invoke-CatalogScalar -Sql @"
SELECT string_agg(g.privilege_type, ',' ORDER BY g.privilege_type)
FROM information_schema.role_table_grants AS g
WHERE g.table_schema = 'public'
  AND g.table_name = 'ai_editor_request_previews'
  AND g.grantee = 'lms_app'
"@ -Expected "SELECT"

    Invoke-CatalogScalar -Sql @"
SELECT string_agg(g.column_name, ',' ORDER BY g.column_name)
FROM information_schema.role_column_grants AS g
WHERE g.table_schema = 'public'
  AND g.table_name = 'ai_editor_request_previews'
  AND g.grantee = 'lms_app'
  AND g.privilege_type = 'INSERT'
"@ -Expected "claim_token_sha256,payload_fingerprint,preview_key,request_id,state,tenant_id"

    Invoke-CatalogScalar -Sql @"
SELECT string_agg(g.column_name, ',' ORDER BY g.column_name)
FROM information_schema.role_column_grants AS g
WHERE g.table_schema = 'public'
  AND g.table_name = 'ai_editor_request_previews'
  AND g.grantee = 'lms_app'
  AND g.privilege_type = 'UPDATE'
"@ -Expected "claim_token_sha256,completed_at,completed_result_json,failed_at,failure_code,state,updated_at"

    Invoke-CatalogScalar -Sql @"
SELECT has_table_privilege('lms_app', 'public.ai_editor_request_previews', 'DELETE')::text
"@ -Expected "false"

    Invoke-CatalogScalar -Sql @"
SELECT (
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'ai_editor_requests'
          AND column_name = 'request_fingerprint_sha256'
          AND is_nullable = 'YES'
    )
    AND EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.ai_editor_requests'::regclass
          AND conname = 'ck_ai_editor_requests_fingerprint_sha256'
          AND contype = 'c'
    )
)::text
"@ -Expected "true"
}

try {
    $containerEnv = Get-ContainerEnvironment
    $portLines = @(& docker port $ContainerName 5432/tcp)
    $hostPort = ($portLines | Select-Object -First 1).Trim() -replace '^.*:', ''
    if ($LASTEXITCODE -ne 0 -or $hostPort -notmatch '^\d{2,5}$') {
        throw "Could not resolve the loopback PostgreSQL port."
    }

    & docker exec $ContainerName createdb -U $containerEnv["POSTGRES_USER"] $DatabaseName 2>&1 | Write-SanitizedOutput
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the disposable database."
    }
    $DatabaseCreated = $true

    $user = [Uri]::EscapeDataString($containerEnv["POSTGRES_USER"])
    $password = [Uri]::EscapeDataString($containerEnv["POSTGRES_PASSWORD"])
    $database = [Uri]::EscapeDataString($DatabaseName)
    $DatabaseUrl = "postgresql+asyncpg://${user}:${password}@127.0.0.1:${hostPort}/${database}"
    $env:DATABASE_URL = $DatabaseUrl
    $env:MIGRATION_DATABASE_URL = $DatabaseUrl
    $env:APP_ENV = "test"
    $env:PYTHONPATH = $ApiRoot

    if ($Mode -in @("all", "migration")) {
        Invoke-Checked -Program "poetry" -Arguments @("run", "alembic", "upgrade", "head") -WorkingDirectory $ApiRoot
        Invoke-Checked -Program "poetry" -Arguments @("run", "alembic", "downgrade", "0135") -WorkingDirectory $ApiRoot
        Invoke-Checked -Program "poetry" -Arguments @("run", "alembic", "upgrade", "0136") -WorkingDirectory $ApiRoot
        Invoke-Checked -Program "poetry" -Arguments @("run", "alembic", "downgrade", "0134") -WorkingDirectory $ApiRoot
        Invoke-Checked -Program "poetry" -Arguments @("run", "alembic", "upgrade", "0135") -WorkingDirectory $ApiRoot
        Invoke-Checked -Program "poetry" -Arguments @("run", "alembic", "upgrade", "0136") -WorkingDirectory $ApiRoot
        Invoke-Checked -Program "poetry" -Arguments @("run", "alembic", "upgrade", "head") -WorkingDirectory $ApiRoot
        Invoke-Checked -Program "poetry" -Arguments @("run", "alembic", "heads") -WorkingDirectory $ApiRoot
        Assert-PreviewCatalogContract
    }

    if ($Mode -in @("all", "tests")) {
        Invoke-Checked -Program "poetry" -Arguments @(
            "run", "python", "-m", "pytest", "-q",
            "tests/integration/test_editor_assistant_telemetry.py",
            "tests/integration/test_editor_assistant_preview_repository.py"
        ) -WorkingDirectory $ApiRoot
    }

    Write-Output "EDITOR ASSISTANT STEP 1 CHECKS PASSED ($Mode)"
}
finally {
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:MIGRATION_DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    $DatabaseUrl = $null

    if ($DatabaseCreated) {
        & docker exec $ContainerName dropdb --if-exists --force -U $containerEnv["POSTGRES_USER"] $DatabaseName 2>&1 | Write-SanitizedOutput
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Disposable database cleanup failed."
        }
    }
}
