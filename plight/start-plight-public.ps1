param(
    [string]$PagesOrigin = "https://zship135.github.io",

    [string]$NgrokDomain = "interastral-precosmical-rayan.ngrok-free.dev",

    [string]$CreatorEmail
)

$ErrorActionPreference = "Stop"

$originUri = $null
if (-not [Uri]::TryCreate($PagesOrigin, [UriKind]::Absolute, [ref]$originUri) -or
    $originUri.Scheme -ne "https" -or
    $originUri.AbsolutePath -ne "/" -or
    $originUri.Query -or
    $originUri.Fragment) {
    throw "PagesOrigin must be the exact HTTPS origin, without a repository path, query, or fragment."
}
$pagesOrigin = $originUri.GetLeftPart([UriPartial]::Authority)

if (-not [string]::IsNullOrWhiteSpace($NgrokDomain) -and
    [Uri]::CheckHostName($NgrokDomain) -ne [UriHostNameType]::Dns) {
    throw "NgrokDomain must be a hostname only, such as your-assigned-name.ngrok-free.app."
}

$projectRoot = (Resolve-Path $PSScriptRoot).Path
$pythonCommand = Get-Command python -ErrorAction Stop
$ngrokCommand = Get-Command ngrok -ErrorAction Stop

Push-Location $projectRoot
try {
    & $pythonCommand.Source -m uvicorn --version
    if ($LASTEXITCODE -ne 0) {
        throw "Uvicorn is missing. Install backend dependencies with 'python -m pip install -r requirements.txt'."
    }

    & $ngrokCommand.Source config check
    if ($LASTEXITCODE -ne 0) {
        throw "ngrok is not configured. Install the ngrok agent and configure its auth token locally."
    }
} finally {
    Pop-Location
}

$apiListeners = @(
    Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
)
$ngrokListeners = @(
    Get-NetTCPConnection -LocalPort 4040 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
)
if ($apiListeners -or $ngrokListeners) {
    if ($apiListeners.Count -ne 1 -or $ngrokListeners.Count -ne 1) {
        throw "A Plight service is already using port 8000 or 4040. Close the existing Plight API and ngrok windows, then run this script again."
    }

    $apiProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($apiListeners[0])"
    $ngrokProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($ngrokListeners[0])"
    if ($apiProcess.Name -ne "python.exe" -or $apiProcess.CommandLine -notmatch "plight_server\.app:app") {
        throw "Port 8000 is occupied by a process that is not the Plight API; refusing to use or stop it."
    }
    if ($ngrokProcess.Name -notmatch "ngrok" -or $ngrokProcess.CommandLine -notmatch "ngrok\.exe.*http.*8000") {
        throw "Port 4040 is occupied by an ngrok process that does not appear to tunnel Plight; refusing to use or stop it."
    }

    $publicApi = "https://$NgrokDomain"
    $localHealth = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 5
    $preflight = Invoke-WebRequest `
        -Uri "http://127.0.0.1:8000/api/v1/auth/login" `
        -Method Options `
        -Headers @{
            Origin = $pagesOrigin
            "Access-Control-Request-Method" = "POST"
            "Access-Control-Request-Headers" = "authorization,content-type,ngrok-skip-browser-warning"
        } `
        -UseBasicParsing `
        -TimeoutSec 5
    $tunnels = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 5
    $tunnel = $tunnels.tunnels | Where-Object { $_.proto -eq "https" -and $_.public_url -eq $publicApi }
    if ($localHealth.status -ne "ok" -or
        $preflight.StatusCode -ne 200 -or
        $preflight.Headers["Access-Control-Allow-Origin"] -ne $pagesOrigin -or
        $preflight.Headers["Access-Control-Allow-Headers"] -notmatch "ngrok-skip-browser-warning" -or
        -not $tunnel) {
        throw "Existing services are running but are not correctly configured for the public Plight site."
    }

    $publicHealth = Invoke-RestMethod `
        -Uri "$publicApi/health" `
        -Headers @{ "ngrok-skip-browser-warning" = "true" } `
        -TimeoutSec 5
    if ($publicHealth.status -ne "ok") {
        throw "The existing public Plight API health check failed."
    }

    Write-Host "Plight is already running and verified."
    Write-Host "Game: https://zship135.github.io/"
    Write-Host "Public API: $publicApi"
    return
}

function ConvertTo-PowerShellLiteral([string]$Value) {
    return "'" + $Value.Replace("'", "''") + "'"
}

$rootLiteral = ConvertTo-PowerShellLiteral $projectRoot
$pythonLiteral = ConvertTo-PowerShellLiteral $pythonCommand.Source
$originLiteral = ConvertTo-PowerShellLiteral $pagesOrigin
$creatorSetup = if ([string]::IsNullOrWhiteSpace($CreatorEmail)) {
    "`Remove-Item Env:PLIGHT_CONTENT_EDITOR_EMAIL -ErrorAction SilentlyContinue"
} else {
    "`$env:PLIGHT_CONTENT_EDITOR_EMAIL = $(ConvertTo-PowerShellLiteral $CreatorEmail)"
}

$apiScript = @"
`$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $rootLiteral
`$env:PLIGHT_UI_ORIGIN = $originLiteral
$creatorSetup
& $pythonLiteral -m uvicorn plight_server.app:app --host 127.0.0.1 --port 8000 --workers 1 --ws-max-size 4096
if (`$LASTEXITCODE -ne 0) {
    throw "The Plight API stopped with exit code `$LASTEXITCODE."
}
"@
$apiEncoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($apiScript))
$apiWindow = Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit", "-EncodedCommand", $apiEncoded) -WorkingDirectory $projectRoot -PassThru

$apiReady = $false
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2
        if ($health.status -eq "ok") {
            $apiReady = $true
            break
        }
    } catch {
        Start-Sleep -Milliseconds 500
    }
}

if (-not $apiReady) {
    throw "The API did not become ready. Check the Plight API window (PID $($apiWindow.Id)) for its startup error."
}

$ngrokArguments = @("http", "8000")
$publicApi = $null
if (-not [string]::IsNullOrWhiteSpace($NgrokDomain)) {
    $ngrokArguments = @("http", "--url=https://$NgrokDomain", "8000")
    $publicApi = "https://$NgrokDomain"
}
$ngrokWindow = Start-Process -FilePath $ngrokCommand.Source -ArgumentList $ngrokArguments -PassThru

$tunnelReady = $false
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    try {
        $tunnels = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 2
        $httpsTunnel = $tunnels.tunnels |
            Where-Object { $_.proto -eq "https" } |
            Select-Object -First 1
        if (-not $publicApi -and $httpsTunnel) {
            $publicApi = $httpsTunnel.public_url
        }
        if ($httpsTunnel -and $httpsTunnel.public_url -eq $publicApi) {
            $health = Invoke-RestMethod `
                -Uri "$publicApi/health" `
                -Headers @{ "ngrok-skip-browser-warning" = "true" } `
                -TimeoutSec 5
            if ($health.status -eq "ok") {
                $tunnelReady = $true
                break
            }
        }
    } catch {
        Start-Sleep -Milliseconds 500
    }
    Start-Sleep -Milliseconds 500
}

if (-not $tunnelReady) {
    throw "The ngrok HTTPS health check failed. Check the ngrok window (PID $($ngrokWindow.Id)) and confirm the assigned domain is available to your account."
}

Write-Host ""
Write-Host "Plight's public API and live WebSocket are reachable through ngrok."
Write-Host "Public API: $publicApi"
Write-Host "Pages origin allowed by the API: $pagesOrigin"
Write-Host "API health: $publicApi/health"
Write-Host "Keep this laptop awake and both service windows running."
Write-Host "Do not open router ports or bind the API to a public interface."
