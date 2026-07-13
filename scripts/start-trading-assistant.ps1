$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$frontendDir = Join-Path $repoRoot "frontend\openstock"
$srcDir = Join-Path $repoRoot "src"
$backendHost = "127.0.0.1"
$backendPort = 8765
$frontendHost = "127.0.0.1"
$frontendPort = 3000
$backendUrl = "http://${backendHost}:${backendPort}"
$frontendUrl = "http://localhost:${frontendPort}"
$localEnvFile = Join-Path $repoRoot "configs\local.env"

function Write-Section([string] $Text) {
    Write-Host ""
    Write-Host "== $Text ==" -ForegroundColor Cyan
}

function Test-PortOpen([string] $HostName, [int] $Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $connect = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $connect.AsyncWaitHandle.WaitOne(300)) {
            return $false
        }
        $client.EndConnect($connect)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

function Wait-PortOpen([string] $HostName, [int] $Port, [int] $TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortOpen $HostName $Port) {
            return $true
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Test-DockerDaemon {
    try {
        docker info *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

function Get-EnvValue([string] $Path, [string] $Name) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    $line = Get-Content -LiteralPath $Path | Where-Object { $_ -match "^$([regex]::Escape($Name))=" } | Select-Object -First 1
    if (-not $line) {
        return $null
    }
    return $line.Substring($Name.Length + 1).Trim()
}

function Get-EnvAssignmentCommand([string] $Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return ""
    }

    $lines = New-Object System.Collections.Generic.List[string]
    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            return
        }
        $name, $value = $line.Split("=", 2)
        $name = $name.Trim()
        $value = $value.Trim().Trim('"').Trim("'").Replace("'", "''")
        if ($name -match '^[A-Za-z_][A-Za-z0-9_]*$') {
            $lines.Add("`$env:$name = '$value'")
        }
    }

    return ($lines -join "`r`n")
}

function Test-LocalMongoUri([string] $MongoUri) {
    return $MongoUri -match '^mongodb://.*(localhost|127\.0\.0\.1|\[::1\])'
}

function Ensure-FrontendDependencies {
    $nodeModules = Join-Path $frontendDir "node_modules"
    if (-not (Test-Path -LiteralPath $nodeModules)) {
        Write-Host "Frontend dependencies are missing or outdated. Running npm install..."
        Push-Location $frontendDir
        try {
            npm install
        }
        finally {
            Pop-Location
        }
    }
    else {
        Write-Host "OpenStock node_modules found."
    }
}

function Get-DockerDesktopPath {
    $candidates = @(
        (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe")
    )

    $dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
    if ($dockerCommand) {
        $dockerBin = Split-Path -Parent $dockerCommand.Source
        $dockerResources = Split-Path -Parent $dockerBin
        $dockerRoot = Split-Path -Parent $dockerResources
        $candidates += (Join-Path $dockerRoot "Docker Desktop.exe")
    }

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }

    return $null
}

function Start-DockerDesktop {
    if (Test-DockerDaemon) {
        return $true
    }

    $dockerDesktop = Get-DockerDesktopPath
    if ($dockerDesktop -and (Test-Path -LiteralPath $dockerDesktop)) {
        Write-Host "Docker daemon is not running. Starting Docker Desktop..."
        Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
        for ($i = 1; $i -le 60; $i++) {
            Start-Sleep -Seconds 2
            if (Test-DockerDaemon) {
                Write-Host "Docker daemon is ready."
                return $true
            }
            Write-Host "Waiting for Docker Desktop... ($($i * 2)s)"
        }
    }

    return (Test-DockerDaemon)
}

function Start-ServiceWindow([string] $Title, [string] $Command) {
    $wrapped = @"
`$Host.UI.RawUI.WindowTitle = '$Title'
$Command
"@
    $encodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($wrapped))
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        $encodedCommand
    )
}

Write-Host "Semi-Automated Trading Assistant Launcher" -ForegroundColor Green
Write-Host "Repository: $repoRoot"

Write-Section "Addresses"
Write-Host "Frontend: $frontendUrl"
Write-Host "Backend : $backendUrl"
Write-Host "Health  : $backendUrl/health"

Write-Section "Environment"
$envFile = Join-Path $frontendDir ".env"
$mongoUri = Get-EnvValue $envFile "MONGODB_URI"
if (Test-Path -LiteralPath $envFile) {
    Write-Host "OpenStock .env found."
}
else {
    Write-Warning "OpenStock .env was not found: $envFile"
    Write-Warning "Create it before using market data. The Finnhub key belongs in NEXT_PUBLIC_FINNHUB_API_KEY."
}
if (Test-Path -LiteralPath $localEnvFile) {
    Write-Host "Local backend config found: configs\\local.env"
}
else {
    Write-Warning "Local backend config was not found: configs\\local.env"
    Write-Warning "Copy configs\\local.env.example to configs\\local.env before enabling email alerts."
}

Write-Section "Dependencies"
Ensure-FrontendDependencies

Write-Section "MongoDB"
$requiresLocalMongo = -not $mongoUri -or (Test-LocalMongoUri $mongoUri)
if ($requiresLocalMongo) {
    if (Test-PortOpen "127.0.0.1" 27017) {
        Write-Host "Local MongoDB is already listening on 127.0.0.1:27017."
    }
    else {
        if (Get-Command docker -ErrorAction SilentlyContinue) {
            if (Start-DockerDesktop) {
                Push-Location $frontendDir
                try {
                    docker compose up -d mongodb
                    if ($LASTEXITCODE -eq 0) {
                        Write-Host "MongoDB container requested."
                        [void](Wait-PortOpen "127.0.0.1" 27017 30)
                    }
                    else {
                        Write-Warning "docker compose returned exit code $LASTEXITCODE."
                    }
                }
                finally {
                    Pop-Location
                }
            }
            else {
                Write-Warning "Docker daemon is not available. Start Docker Desktop or run MongoDB manually."
            }
        }
        else {
            Write-Warning "Docker command not found. Run MongoDB manually or install Docker Desktop."
        }
    }

    if (-not (Test-PortOpen "127.0.0.1" 27017)) {
        Write-Warning "Docker MongoDB is still not reachable."
    }
}
else {
    Write-Host "MONGODB_URI is not local; skipping local MongoDB startup."
}

if ($requiresLocalMongo -and -not (Test-PortOpen "127.0.0.1" 27017)) {
    Write-Host ""
    Write-Host "MongoDB is required but is not reachable at 127.0.0.1:27017." -ForegroundColor Red
    Write-Host "Frontend will stay blank or fail during auth without MongoDB." -ForegroundColor Red
    Write-Host ""
    Write-Host "Fix one of these first:"
    Write-Host "1. Start Docker Desktop, then run this launcher again."
    Write-Host "2. Run: cd frontend\\openstock; docker compose up -d mongodb"
    Write-Host "3. Install/start MongoDB locally on port 27017."
    Write-Host "4. Change frontend\\openstock\\.env MONGODB_URI to a reachable MongoDB Atlas URI."
    Write-Host ""
    Write-Host "Press Enter to close this launcher window."
    [void][Console]::ReadLine()
    exit 1
}

Write-Section "Start Backend"
if (Test-PortOpen $backendHost $backendPort) {
    Write-Host "Backend port $backendPort is already in use. Assuming backend is already running."
}
else {
    $backendEnvCommand = Get-EnvAssignmentCommand $localEnvFile
    $backendCommand = @"
Set-Location -LiteralPath '$repoRoot'
$backendEnvCommand
`$env:PYTHONPATH = '$srcDir'
python -m trading_assistant.api --host $backendHost --port $backendPort
"@
    Start-ServiceWindow "Trading Assistant API - $backendUrl" $backendCommand
    Write-Host "Backend service window started."
}

Write-Section "Start Frontend"
if (Test-PortOpen $frontendHost $frontendPort) {
    Write-Host "Frontend port $frontendPort is already in use. Assuming frontend is already running."
}
else {
    $frontendCommand = @"
Set-Location -LiteralPath '$frontendDir'
`$env:OPENSTOCK_AUTH_MODE = 'local'
`$env:NEXT_PUBLIC_OPENSTOCK_AUTH_MODE = 'local'
`$env:OPENSTOCK_LOCAL_USER_ID = 'local-user'
`$env:OPENSTOCK_LOCAL_USER_NAME = '本地用户'
`$env:OPENSTOCK_LOCAL_USER_EMAIL = 'local@openstock.local'
`$env:NEXT_PUBLIC_TRADING_ASSISTANT_API_URL = '$backendUrl'
npx next dev --turbopack -H $frontendHost -p $frontendPort
"@
    Start-ServiceWindow "OpenStock Frontend - $frontendUrl" $frontendCommand
    Write-Host "Frontend service window started."
}

Write-Section "Ready"
Write-Host "Frontend: $frontendUrl" -ForegroundColor Green
Write-Host "Backend : $backendUrl" -ForegroundColor Green
Write-Host "Health  : $backendUrl/health" -ForegroundColor Green
Write-Host ""
Write-Host "Keep the service windows open while using the app."
Write-Host "Press Enter to close this launcher window."
[void][Console]::ReadLine()
