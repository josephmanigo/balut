param([switch]$Supervise, [switch]$Phone)
& (Join-Path $PSScriptRoot 'Start-Balut.ps1') @PSBoundParameters
exit $LASTEXITCODE
