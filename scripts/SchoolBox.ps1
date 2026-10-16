param([ValidateSet('Start','Stop','Cloud','CopyKey','Drivers')][string]$Action = 'Start', [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskPython = Join-Path $taskRoot 'runtime\python\python.exe'
$taskProfilePath = Join-Path $taskRoot 'deployment\private\windows.json'
$taskLogs = Join-Path $taskRoot 'deployment\logs'
$taskBridgePath = Join-Path $PSScriptRoot 'camera_usb_bridge.py'
$taskCloudExe = Join-Path $taskRoot 'runtime\cloudflared.exe'
$taskKeyPath = Join-Path $taskRoot 'deployment\private\cloud-key.txt'
$taskStatePath = Join-Path $taskRoot 'deployment\private\school-processes.json'

function Test-TaskProcess($Process, $Kind) {
    if (-not $Process -or -not $Process.CommandLine) { return $false }
    if ($Kind -eq 'supervisor') {
        return $Process.Name -eq 'powershell.exe' -and $Process.CommandLine.Contains((Join-Path $PSScriptRoot 'Start-Balut.ps1'))
    }
    if ($Kind -eq 'tunnel') { return $Process.ExecutablePath -eq $taskCloudExe }
    if ($Process.ExecutablePath -ne $taskPython) { return $false }
    if ($Kind -eq 'bridge') { return $Process.CommandLine.Contains($taskBridgePath) -and $Process.CommandLine.Contains('--loopback') }
    if ($Kind -eq 'gateway') { return $Process.CommandLine.Contains('-m balut_api.cloud_gateway') }
    return $Process.CommandLine.Contains('-m balut_api.service_runner') -and $Process.CommandLine.Contains($taskProfilePath)
}

function Get-TaskListener($Port, $Kind) {
    $taskListeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalAddress -in @('127.0.0.1','0.0.0.0','::') })
    foreach ($taskListener in $taskListeners) {
        $taskProcess = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $taskListener.OwningProcess)
        if (-not (Test-TaskProcess $taskProcess $Kind)) { throw "Port $Port is used by another application. Stop it before starting this kit." }
    }
    return $taskListeners.Count -gt 0
}

function Start-TaskProcess($Kind, $Exe, $Arguments) {
    $taskProcess = Start-Process -FilePath $Exe -ArgumentList $Arguments -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $taskLogs ($Kind + '.out.log')) -RedirectStandardError (Join-Path $taskLogs ($Kind + '.err.log'))
    $taskState = @{}
    if (Test-Path -LiteralPath $taskStatePath) {
        (Get-Content -LiteralPath $taskStatePath -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $taskState[$_.Name] = $_.Value }
    }
    $taskState[$Kind] = $taskProcess.Id
    $taskState | ConvertTo-Json | Set-Content -LiteralPath $taskStatePath -Encoding UTF8
    return $taskProcess
}

function Wait-TaskListener($Port, $Kind, $Process) {
    for ($taskTry = 0; $taskTry -lt 90; $taskTry++) {
        if (Get-TaskListener $Port $Kind) { return }
        if ($Process.HasExited) { throw "$Kind stopped. Read deployment\logs\$Kind.err.log. For a camera error, connect its USB cable and install the included drivers if needed." }
        Start-Sleep -Seconds 1
    }
    throw "$Kind did not start in 90 seconds. Read deployment\logs."
}

function Start-TaskLocal {
    if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Extract the complete ZIP to a local folder first. Do not run inside the ZIP.' }
    if (-not (Test-Path -LiteralPath $taskProfilePath)) { & (Join-Path $PSScriptRoot 'Initialize-Serving.ps1') }
    New-Item -ItemType Directory -Path $taskLogs -Force | Out-Null
    $taskProfile = Get-Content -LiteralPath $taskProfilePath -Raw | ConvertFrom-Json
    if ($taskProfile.port -ne 8765 -or $taskProfile.https_origin) { throw 'Use a fresh school kit with its loopback profile.' }
    $taskNewService = -not (Get-TaskListener 8765 'service')
    $taskNewCamera = -not (Get-TaskListener 8767 'bridge')
    $taskOldPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = Join-Path $taskRoot 'apps\edge_api'
        if ($taskNewService) {
            $taskService = Start-TaskProcess 'supervisor' 'powershell.exe' ('-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $PSScriptRoot 'Start-Balut.ps1') + '" -Supervise')
            Wait-TaskListener 8765 'service' $taskService
        }
        if ($taskNewCamera) {
            $taskCamera = Start-TaskProcess 'bridge' $taskPython ('"' + $taskBridgePath + '" --loopback')
            Wait-TaskListener 8767 'bridge' $taskCamera
        }
    } finally { $env:PYTHONPATH = $taskOldPath }
    # Confirm ownership before sending the local administrator credential.
    if (-not (Get-TaskListener 8765 'service')) { throw 'The local service stopped.' }
    $taskHeaders = @{ Authorization = 'Bearer ' + $taskProfile.local_admin_token; 'X-Balut-Origin' = 'local' }
    $taskStatus = Invoke-RestMethod 'http://127.0.0.1:8765/api/v1/box/status' -Headers $taskHeaders -TimeoutSec 15
    if ($taskNewService -or $taskNewCamera -or $taskStatus.cameraUrl -ne 'http://127.0.0.1:8767') {
        $taskStatus = Invoke-RestMethod 'http://127.0.0.1:8765/api/v1/box/connect' -Method Post -Headers $taskHeaders `
            -ContentType 'application/json' -Body '{"cameraUrl":"http://127.0.0.1:8767"}' -TimeoutSec 40
    }
    Write-Host 'Box ready: http://127.0.0.1:8765/'
    Write-Host 'Sign in (or create this laptop account), then save the empty view with normal lighting before placing an egg.'
    if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:8765/' }
}

if ($Action -eq 'Stop') {
    if (Test-Path -LiteralPath $taskStatePath) {
        $taskState = Get-Content -LiteralPath $taskStatePath -Raw | ConvertFrom-Json
        foreach ($taskKind in @('tunnel','gateway','supervisor','bridge')) {
            $taskProcessId = $taskState.$taskKind
            if ($taskProcessId) {
                $taskProcess = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + [int]$taskProcessId)
                if (Test-TaskProcess $taskProcess $taskKind) { Stop-Process -Id $taskProcess.ProcessId -Force }
            }
        }
    }
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object {
        (Test-TaskProcess $_ 'service') -or (Test-TaskProcess $_ 'bridge') -or (Test-TaskProcess $_ 'gateway')
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Write-Host 'School laptop services stopped. The USB-powered spinner continues until its power is disconnected.'
    exit
}

if ($Action -eq 'Drivers') {
    $taskAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $taskAdmin) {
        Start-Process powershell.exe -WindowStyle Hidden -Verb RunAs -Wait -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -Action Drivers')
        exit
    }
    $taskDriverPaths = @((Join-Path $taskRoot 'deployment\drivers\ftdi\exported'), (Join-Path $taskRoot 'deployment\drivers\cp210x\package'))
    foreach ($taskDriverPath in $taskDriverPaths) {
        $taskCatalogs = @(Get-ChildItem -LiteralPath $taskDriverPath -Recurse -Filter '*.cat')
        if (-not $taskCatalogs.Count) { throw 'Driver catalog missing; extract the complete kit.' }
        foreach ($taskCatalog in $taskCatalogs) {
            if ((Get-AuthenticodeSignature -LiteralPath $taskCatalog.FullName).Status -ne 'Valid') { throw 'Driver signature did not validate. Use Windows Update instead.' }
        }
        & pnputil.exe /add-driver (Join-Path $taskDriverPath '*.inf') /subdirs /install | Out-File (Join-Path $taskRoot 'driver-install.log') -Append
        if ($LASTEXITCODE -notin @(0,3010)) { throw 'Driver setup failed. Read driver-install.log.' }
    }
    exit
}

if ($Action -eq 'CopyKey') {
    if (-not (Test-Path -LiteralPath $taskKeyPath)) { throw 'Run Start Vercel Connector first.' }
    Set-Clipboard -Value ((Get-Content -LiteralPath $taskKeyPath -Raw).Trim())
    Write-Host 'Private key copied. Paste only into Vercel BALUT_BOX_KEY, then clear your clipboard. Do not send it in chat.'
    exit
}

Start-TaskLocal
if ($Action -ne 'Cloud') { exit }
$taskSession = Invoke-RestMethod 'http://127.0.0.1:8765/api/v1/auth/session' -TimeoutSec 10
if ($taskSession.setupRequired) { throw 'First create your account at http://127.0.0.1:8765/, then run Start Vercel Connector again.' }
if (-not (Test-Path -LiteralPath $taskKeyPath)) {
    $taskBytes = New-Object byte[] 48
    $taskRng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $taskRng.GetBytes($taskBytes) } finally { $taskRng.Dispose() }
    [Convert]::ToBase64String($taskBytes).Replace('+','-').Replace('/','_') | Set-Content -LiteralPath $taskKeyPath -Encoding UTF8
}
if (-not (Get-TaskListener 8768 'gateway')) {
    $taskOldPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = Join-Path $taskRoot 'apps\edge_api'
        $taskGateway = Start-TaskProcess 'gateway' $taskPython '-m balut_api.cloud_gateway'
        Wait-TaskListener 8768 'gateway' $taskGateway
    } finally { $env:PYTHONPATH = $taskOldPath }
}
$taskTunnelRunning = $false
if (Test-Path -LiteralPath $taskStatePath) {
    $taskState = Get-Content -LiteralPath $taskStatePath -Raw | ConvertFrom-Json
    if ($taskState.tunnel) {
        $taskTunnelRunning = Test-TaskProcess (Get-CimInstance Win32_Process -Filter ('ProcessId = ' + [int]$taskState.tunnel)) 'tunnel'
    }
}
if (-not $taskTunnelRunning) {
    Start-TaskProcess 'tunnel' $taskCloudExe 'tunnel --url http://127.0.0.1:8768 --http-host-header 127.0.0.1:8768 --no-autoupdate --metrics 127.0.0.1:0' | Out-Null
}
$taskTunnelUrl = $null
for ($taskTry = 0; $taskTry -lt 60; $taskTry++) {
    $taskLog = Get-Content -LiteralPath (Join-Path $taskLogs 'tunnel.err.log') -Raw -ErrorAction SilentlyContinue
    $taskMatch = [regex]::Match([string]$taskLog, 'https://[a-z0-9-]+\.trycloudflare\.com')
    if ($taskMatch.Success) { $taskTunnelUrl = $taskMatch.Value; break }
    Start-Sleep -Seconds 1
}
if (-not $taskTunnelUrl) { throw 'Tunnel could not connect. Check internet and deployment\logs\tunnel.err.log. The local page still works.' }
$taskInstructions = @"
BALUT_BOX_URL=$taskTunnelUrl
BALUT_BOX_KEY: run Copy Vercel Key.cmd, then paste into the server-only Vercel environment variable.
Enable both variables for Production, then redeploy Vercel. Do not use VITE_ prefixes.
The tunnel URL changes after restarting the connector. Update BALUT_BOX_URL and redeploy.
Keep this laptop awake with both USB cables connected. Stop School Box.cmd closes remote access.
"@
$taskInstructions | Set-Content -LiteralPath (Join-Path $taskRoot 'Vercel Connection.txt') -Encoding UTF8
Write-Host $taskInstructions
if (-not $NoBrowser) { Start-Process notepad.exe -ArgumentList ('"' + (Join-Path $taskRoot 'Vercel Connection.txt') + '"') }
