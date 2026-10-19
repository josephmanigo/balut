param(
    [string]$FlutterExecutable = 'C:\balut-dev\flutter\bin\flutter.bat',
    [string]$Server = 'http://127.0.0.1:8765'
)
& (Join-Path $PSScriptRoot 'Build-BalutAndroid.ps1') @PSBoundParameters
exit $LASTEXITCODE
