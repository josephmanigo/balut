param([switch]$CompileCheck)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskArduino = Join-Path $env:USERPROFILE '.cache\balut-tools\arduino'
$taskPrivate = Join-Path $taskRoot 'deployment\private'
$taskSketch = Join-Path $taskPrivate 'camera-build\BoxCamera'
New-Item -ItemType Directory -Path $taskSketch -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $taskRoot 'firmware\camera\BoxCamera\BoxCamera.ino') -Destination (Join-Path $taskSketch 'BoxCamera.ino')
$taskBuild = Join-Path $taskPrivate $(if ($CompileCheck) { 'camera-build\check' } else { 'camera-build\release' })
$taskLog = Join-Path $taskPrivate 'camera-build\compile.log'
& (Join-Path $taskArduino 'arduino-cli.exe') --config-file (Join-Path $taskArduino 'arduino-cli.yaml') compile --fqbn esp32:esp32:esp32cam --build-path $taskBuild $taskSketch *> $taskLog
if ($LASTEXITCODE -ne 0) { throw "Camera build failed. Inspect the private compile log without sharing credentials: $taskLog" }
if (-not (Test-Path -LiteralPath (Join-Path $taskBuild 'BoxCamera.ino.bin'))) { throw 'Camera binary missing after compilation.' }
Write-Output $(if ($CompileCheck) { 'USB camera compile check passed; no upload performed.' } else { 'USB camera firmware built.' })
Get-FileHash -LiteralPath (Join-Path $taskBuild 'BoxCamera.ino.bin') -Algorithm SHA256
