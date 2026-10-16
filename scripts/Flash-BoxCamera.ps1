$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskPrivate = Join-Path $taskRoot 'deployment\private'
$taskBackupDir = Join-Path $taskPrivate 'camera-backup'
$taskManifest = Get-Content -LiteralPath (Join-Path $taskBackupDir 'manifest.json') -Raw | ConvertFrom-Json
$taskBackup = Join-Path $taskBackupDir 'original-20261016.bin'
if (-not $taskManifest.complete -or $taskManifest.bytes -ne 4194304 -or
    (Get-FileHash -LiteralPath $taskBackup -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskManifest.sha256) {
    throw 'A verified original camera backup is required before flashing.'
}
$taskCamera = Get-PnpDevice -PresentOnly | Where-Object {
    $_.InstanceId -eq 'FTDIBUS\VID_0403+PID_6001+A5069RR4A\0000' -and $_.FriendlyName -eq 'USB Serial Port (COM3)' -and $_.Status -eq 'OK'
}
if (-not $taskCamera) { throw 'The identified camera adapter is not on COM3. No flash attempted.' }
$taskPython = Join-Path $taskRoot '.venv-hardware\Scripts\python.exe'
$taskIdentityLog = Join-Path $taskBackupDir 'before-flash-identity.log'
& $taskPython -m esptool --chip esp32 --port COM3 --baud 115200 --connect-attempts 2 read-mac *> $taskIdentityLog
if ($LASTEXITCODE -ne 0 -or -not (Select-String -LiteralPath $taskIdentityLog -SimpleMatch $taskManifest.mac -Quiet)) {
    throw 'Camera identity could not be verified. No flash attempted.'
}
& (Join-Path $PSScriptRoot 'Build-BoxCamera.ps1')
$taskBuild = Join-Path $taskPrivate 'camera-build\release'
$taskLog = Join-Path $taskPrivate 'camera-build\upload.log'
& $taskPython -m esptool --chip esp32 --port COM3 --baud 115200 --connect-attempts 2 write-flash --flash-mode dio --flash-freq 40m --flash-size 4MB `
    0x1000 (Join-Path $taskBuild 'BoxCamera.ino.bootloader.bin') `
    0x8000 (Join-Path $taskBuild 'BoxCamera.ino.partitions.bin') `
    0xe000 (Join-Path $taskBuild 'boot_app0.bin') `
    0x10000 (Join-Path $taskBuild 'BoxCamera.ino.bin') *> $taskLog
if ($LASTEXITCODE -ne 0) { throw "Camera upload failed; preserve the original backup and inspect $taskLog" }
Write-Output 'Camera upload completed with esptool flash verification. Check USB JPEG before calibrating.'
