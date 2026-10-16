$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskProfile = Get-Content -LiteralPath (Join-Path $taskRoot 'deployment\private\windows.json') -Raw | ConvertFrom-Json
Set-Clipboard -Value $taskProfile.local_admin_token
Write-Output 'Password copied to the clipboard. Use username operator in the browser login. Clear your clipboard after pasting.'
