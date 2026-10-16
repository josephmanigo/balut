#Requires -RunAsAdministrator
param([Parameter(Mandatory)][string]$Address)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskProfile = Get-Content -LiteralPath (Join-Path $taskRoot 'deployment\private\windows-phone.json') -Raw | ConvertFrom-Json
$taskIp = Get-NetIPAddress -IPAddress $Address -AddressFamily IPv4 -ErrorAction Stop
if ($taskIp.PrefixLength -ne 24 -or $taskProfile.https_origin -ne "https://${Address}:8765") { throw 'This rule requires the configured /24 local network and HTTPS port 8765.' }
$taskSubnet = $Address.Substring(0, $Address.LastIndexOf('.')) + '.0/24'
$taskRule = Get-NetFirewallRule -Name 'Balut-Local-Phone' -ErrorAction SilentlyContinue
if ($taskRule) { throw 'Balut firewall rule already exists. Inspect it before replacing it.' }
New-NetFirewallRule -Name 'Balut-Local-Phone' -DisplayName 'Balut local iPhone workspace' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765,8770 -LocalAddress $Address -RemoteAddress $taskSubnet -InterfaceAlias $taskIp.InterfaceAlias -Profile Any | Out-Null
Get-NetFirewallRule -Name 'Balut-Local-Phone' | Select-Object Name,Enabled,Direction,Action | ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $taskRoot 'deployment\phone-setup\firewall-status.json')
