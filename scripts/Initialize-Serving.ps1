param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskPrivate = Join-Path $taskRoot 'deployment\private'
$taskProfile = Join-Path $taskPrivate 'windows.json'
$taskRegistry = Join-Path $taskRoot 'deployment\releases\source-labels-20260912\registry.json'
$taskAutomaticRegistry = Join-Path $taskRoot 'deployment\releases\automatic-three-class-20260912\registry.json'
if (Test-Path -LiteralPath $taskAutomaticRegistry) { $taskRegistry = $taskAutomaticRegistry }
$taskRecaptureRegistry = Join-Path $taskRoot 'deployment\releases\automatic-recapture-20260912\registry.json'
if (Test-Path -LiteralPath $taskRecaptureRegistry) { $taskRegistry = $taskRecaptureRegistry }
if (Test-Path -LiteralPath $taskProfile) { throw 'A private profile already exists. Preserve it; use the start script.' }
if (-not (Test-Path -LiteralPath $taskRegistry)) { throw 'Prepare the verified serving release first.' }
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Choose an unprivileged TCP port.' }
New-Item -ItemType Directory -Path $taskPrivate -Force | Out-Null
$taskIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls.exe $taskPrivate /inheritance:r /grant:r ($taskIdentity + ':(OI)(CI)F') 'SYSTEM:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not protect the credential directory.' }
function New-TaskSecret {
    $taskBytes = New-Object byte[] 48
    $taskRng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $taskRng.GetBytes($taskBytes) } finally { $taskRng.Dispose() }
    return [Convert]::ToBase64String($taskBytes)
}
$taskSettings = @{
    port = $Port
    database_path = Join-Path $taskRoot 'deployment\runtime\balut.db'
    evidence_path = Join-Path $taskRoot 'deployment\runtime\evidence'
    model_registry_path = $taskRegistry
    model_registry_sha256 = (Get-FileHash -LiteralPath $taskRegistry -Algorithm SHA256).Hash.ToLowerInvariant()
    web_dist_path = Join-Path $taskRoot 'apps\web\dist'
    log_path = Join-Path $taskRoot 'deployment\logs\service.log'
    local_admin_token = New-TaskSecret
    device_shared_secret = New-TaskSecret
}
$taskSettings | ConvertTo-Json | Set-Content -LiteralPath $taskProfile -Encoding utf8
Write-Output ('Created private deployment profile: ' + $taskProfile)
Write-Output ('Loopback URL: http://127.0.0.1:' + $Port)
Write-Output 'Credentials were generated and stored locally, not printed. Serving scope is source-label shadow only.'
