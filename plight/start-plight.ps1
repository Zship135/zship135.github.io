$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path $PSScriptRoot).Path
$webRoot = Join-Path $projectRoot "web"
$creatorEmail = (Read-Host "Creator account email (must match your Plight login)").Trim()

if (-not $creatorEmail) {
    throw "A creator account email is required."
}

$pythonCommand = Get-Command python -ErrorAction Stop
$npmCommand = Get-Command npm.cmd -ErrorAction Stop

if (-not (Test-Path (Join-Path $webRoot "node_modules"))) {
    throw "Frontend dependencies are missing. Run 'npm install' from the web folder, then try again."
}

Push-Location $projectRoot
try {
    & $pythonCommand.Source -m uvicorn --version
    if ($LASTEXITCODE -ne 0) {
        throw "Uvicorn is missing. Install backend dependencies with 'python -m pip install -r requirements.txt'."
    }
} finally {
    Pop-Location
}

$apiListeners = @(
    Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
)

foreach ($processId in $apiListeners) {
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
    if ($processInfo.CommandLine -notmatch "plight_server\.app:app") {
        throw "Port 8000 is already used by PID $processId ($($processInfo.Name)). Close that process before starting Plight."
    }

    Write-Host "A Plight API is already running (PID $processId)."
    $answer = Read-Host "Stop it and restart with the creator email you entered? (y/N)"
    if ($answer -notmatch "^(y|yes)$") {
        throw "The existing API was left running. Stop it before starting Plight again."
    }
    Stop-Process -Id $processId
}

function Find-FreePort([int]$FirstPort, [int]$LastPort) {
    foreach ($candidate in $FirstPort..$LastPort) {
        $listeners = Get-NetTCPConnection -LocalPort $candidate -State Listen -ErrorAction SilentlyContinue
        if (-not $listeners) {
            return $candidate
        }
    }
    throw "No free port was found between $FirstPort and $LastPort."
}

$uiPort = Find-FreePort 5173 5190
$uiOrigin = "http://localhost:$uiPort"
$pythonPath = "'" + $pythonCommand.Source.Replace("'", "''") + "'"
$npmPath = "'" + $npmCommand.Source.Replace("'", "''") + "'"
$rootPath = "'" + $projectRoot.Replace("'", "''") + "'"
$webPath = "'" + $webRoot.Replace("'", "''") + "'"
$emailValue = "'" + $creatorEmail.Replace("'", "''") + "'"

$apiScript = @"
Set-Location -LiteralPath $rootPath
`$env:PLIGHT_CONTENT_EDITOR_EMAIL = $emailValue
`$env:PLIGHT_UI_ORIGIN = '$uiOrigin'
& $pythonPath -m uvicorn plight_server.app:app --host 127.0.0.1 --port 8000 --workers 1 --ws-max-size 4096
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
    throw "The API did not become ready. Check the Plight API window for its startup error."
}

$uiScript = @"
Set-Location -LiteralPath $webPath
`$env:VITE_API_BASE_URL = 'http://127.0.0.1:8000'
& $npmPath run dev -- --host localhost --port $uiPort --strictPort
"@
$uiEncoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($uiScript))
$uiWindow = Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit", "-EncodedCommand", $uiEncoded) -WorkingDirectory $webRoot -PassThru

$uiReady = $false
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    try {
        $response = Invoke-WebRequest -Uri $uiOrigin -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            $uiReady = $true
            break
        }
    } catch {
        Start-Sleep -Milliseconds 500
    }
}

if (-not $uiReady) {
    throw "The browser app did not become ready. Check the Plight web window for its startup error."
}

Write-Host ""
Write-Host "Plight is running."
Write-Host "Browser: $uiOrigin"
Write-Host "API health: http://127.0.0.1:8000/health"
Write-Host "Close the API and web PowerShell windows to stop the app."
Start-Process $uiOrigin
