param([string]$PythonExecutable = 'python')
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
& $PythonExecutable -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'This Windows package requires 64-bit Python 3.12.' }
$taskInventory = Get-Content -LiteralPath (Join-Path $taskRoot 'deployment\wheel-hashes.json') -Raw | ConvertFrom-Json
foreach ($taskItem in $taskInventory.PSObject.Properties) {
    $taskWheel = Join-Path $taskRoot ('deployment\wheelhouse\' + $taskItem.Name)
    if ((Get-FileHash -LiteralPath $taskWheel -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskItem.Value) { throw 'A dependency wheel checksum failed.' }
}
$taskVenv = Join-Path $taskRoot '.venv-serving'
if (-not (Test-Path -LiteralPath $taskVenv)) {
    & $PythonExecutable -m venv $taskVenv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the serving environment.' }
}
$taskPython = Join-Path $taskVenv 'Scripts\python.exe'
& $taskPython -m pip install --no-index --find-links (Join-Path $taskRoot 'deployment\wheelhouse') -r (Join-Path $taskRoot 'deployment\requirements-serving.lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Offline dependency installation failed.' }
& $taskPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency verification failed.' }
if (-not (Test-Path -LiteralPath (Join-Path $taskRoot 'deployment\private\windows.json'))) {
    & (Join-Path $PSScriptRoot 'Initialize-Serving.ps1')
}
Write-Output 'Installation complete. Run scripts\Start-Balut.ps1, then open http://127.0.0.1:8765.'
