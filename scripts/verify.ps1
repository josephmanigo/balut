$ErrorActionPreference = "Stop"

$workspace = Split-Path -Parent $PSScriptRoot
$python = Join-Path $workspace ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Workspace virtual environment is missing. Follow README.md before verification."
}

Push-Location $workspace
try {
    & $python -m pytest
    if ($LASTEXITCODE -ne 0) { throw "Python verification failed." }

    & npm.cmd run verify
    if ($LASTEXITCODE -ne 0) { throw "Web verification failed." }

    $clientSecretHits = & rg -n -i "service.?role|supabase_service_role" apps\web\src apps\mobile\lib firmware 2>$null
    if ($LASTEXITCODE -eq 0 -and $clientSecretHits) {
        throw "A forbidden Supabase service-role reference was found in client or firmware source.`n$clientSecretHits"
    }
    if ($LASTEXITCODE -gt 1) { throw "Client secret scan failed to execute." }

    $bannedClaimHits = & rg -n "SAFE TO EAT|ROTTEN CONFIRMED|PATHOGEN-FREE|SALMONELLA-FREE" apps\web\src apps\mobile\lib firmware 2>$null
    if ($LASTEXITCODE -eq 0 -and $bannedClaimHits) {
        throw "A banned operator-facing safety claim was found.`n$bannedClaimHits"
    }
    if ($LASTEXITCODE -gt 1) { throw "Banned-claim scan failed to execute." }

    Write-Output "Software verification and client safety-string scans passed."
    Write-Output "Flutter, ESP-IDF, physical hardware, model, and research validation remain separate gates."
}
finally {
    Pop-Location
}
