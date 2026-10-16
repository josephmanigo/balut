param(
    [Parameter(Mandatory = $true)]
    [string]$ImagePath,
    [ValidateSet('duck-status', 'age16-18', 'pat-status')]
    [string]$Model = 'duck-status',
    [ValidateSet('baseline', 'accuracy-v2')]
    [string]$Version = 'baseline'
)

$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path $PSScriptRoot -Parent
$taskPython = Join-Path $taskProjectRoot '.venv-ml\Scripts\python.exe'
$taskRuns = @{
    'duck-status' = 'duck-candling-v1'
    'age16-18' = 'source-age16-18-v1'
    'pat-status' = 'pat-balut-v1'
}
$taskCheckpoint = Join-Path $taskProjectRoot ('ml\runs\' + $taskRuns[$Model] + '\best.pt')
$taskModule = 'balut_ml.predict_public'
if ($Version -eq 'accuracy-v2') {
    $taskCandidates = @{'duck-status' = 'duck-candling'; 'age16-18' = 'source-age16-18'; 'pat-status' = 'pat-balut'}
    $taskRun = Join-Path $taskProjectRoot ('ml\runs\accuracy-v2\' + $taskCandidates[$Model])
    $taskParityPath = Join-Path $taskRun 'onnx-parity.json'
    if (-not (Test-Path -LiteralPath $taskParityPath)) { throw 'The requested candidate has no verified ONNX export.' }
    $taskParity = Get-Content -LiteralPath $taskParityPath -Raw | ConvertFrom-Json
    if ($taskParity.passed -ne $true) { throw 'The requested candidate failed export verification.' }
    $taskCheckpoint = Join-Path $taskRun 'best.onnx'
    if ((Get-FileHash -LiteralPath $taskCheckpoint -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskParity.onnx_sha256) {
        throw 'The ONNX file changed after verification.'
    }
    $taskModule = 'balut_ml.predict_onnx'
}
$taskImage = (Resolve-Path -LiteralPath $ImagePath).Path
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'The .venv-ml Python environment is missing.' }
if (-not (Test-Path -LiteralPath $taskCheckpoint)) { throw "Checkpoint is missing: $taskCheckpoint" }
$taskOldPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $taskProjectRoot 'ml'
    & $taskPython -m $taskModule $taskCheckpoint $taskImage
    if ($LASTEXITCODE -ne 0) { throw 'Prediction failed; inspect the Python error above.' }
}
finally {
    $env:PYTHONPATH = $taskOldPythonPath
}
