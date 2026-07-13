param(
    [string]$SourcePath = $env:WATCHLIST_SOURCE_PATH,
    [string]$SshHost = $env:TRADING_ASSISTANT_SSH_HOST,
    [string]$SshKey = $env:TRADING_ASSISTANT_SSH_KEY
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not $SourcePath) {
    throw "Pass -SourcePath or set WATCHLIST_SOURCE_PATH."
}
if (-not $SshHost) {
    throw "Pass -SshHost or set TRADING_ASSISTANT_SSH_HOST."
}
if (-not $SshKey) {
    throw "Pass -SshKey or set TRADING_ASSISTANT_SSH_KEY."
}
if (-not (Test-Path -LiteralPath $SourcePath)) {
    throw "Watchlist source not found: $SourcePath"
}
if (-not (Test-Path -LiteralPath $python)) {
    throw "Project Python runtime not found: $python"
}
if (-not (Test-Path -LiteralPath $SshKey)) {
    throw "SSH key not found: $SshKey"
}

Push-Location $projectRoot
try {
    $payload = (& $python -m trading_assistant.watchlist_sync export --source $SourcePath --base64).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $payload) {
        throw "Failed to parse Active Watchlist from finance.md."
    }
} finally {
    Pop-Location
}

$remote = "set -a; . /etc/trading-assistant/trading-assistant.env; set +a; printf '%s' '$payload' | base64 -d | /opt/trading-assistant/venv/bin/python -m trading_assistant.watchlist_sync apply --stdin --source finance.md-active-watchlist"
$result = & ssh -i $SshKey -o BatchMode=yes $SshHost $remote
if ($LASTEXITCODE -ne 0) {
    throw "Cloud watchlist sync failed. Existing cloud watchlist was not replaced."
}

$result
