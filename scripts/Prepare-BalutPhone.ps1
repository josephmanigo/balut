#Requires -Version 7.2
param([Parameter(Mandatory)][string]$Address, [int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskPrivate = Join-Path $taskRoot 'deployment\private'
$taskProfilePath = Join-Path $taskPrivate 'windows-phone.json'
$taskCertificateDir = Join-Path $taskPrivate 'phone-tls'
$taskPublic = Join-Path $taskRoot 'deployment\phone-setup'
$taskAddress = [Net.IPAddress]::Parse($Address)
if ($taskAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
    $Address -notmatch '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)' -or
    $Port -lt 1024 -or $Port -gt 65535) { throw 'Use a private IPv4 address and port 1024-65535.' }
if (-not (Get-NetIPAddress -IPAddress $Address -ErrorAction SilentlyContinue)) { throw 'Address is not assigned to this PC.' }
if (Test-Path -LiteralPath $taskProfilePath) { throw 'Phone profile already exists; preserve its certificates and use Start-Balut.ps1 -Phone.' }
New-Item -ItemType Directory -Path $taskCertificateDir, $taskPublic -Force | Out-Null
$taskCaKey = [Security.Cryptography.RSA]::Create(3072)
$taskServerKey = [Security.Cryptography.RSA]::Create(2048)
$taskNow = [DateTimeOffset]::UtcNow.AddMinutes(-5)
try {
    $taskCaRequest = [Security.Cryptography.X509Certificates.CertificateRequest]::new(
        'CN=Balut Local Box', $taskCaKey, [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)
    $taskCaRequest.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new($true, $true, 0, $true))
    $taskCaRequest.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509KeyUsageExtension]::new([Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyCertSign, $true))
    $taskCa = $taskCaRequest.CreateSelfSigned($taskNow, $taskNow.AddYears(3))
    $taskRequest = [Security.Cryptography.X509Certificates.CertificateRequest]::new(
        "CN=$Address", $taskServerKey, [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)
    $taskRequest.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new($false, $false, 0, $true))
    $taskRequest.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509KeyUsageExtension]::new(
        [Security.Cryptography.X509Certificates.X509KeyUsageFlags]::DigitalSignature -bor [Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyEncipherment, $true))
    $taskEku = [Security.Cryptography.OidCollection]::new()
    $null = $taskEku.Add([Security.Cryptography.Oid]::new('1.3.6.1.5.5.7.3.1'))
    $taskRequest.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]::new($taskEku, $false))
    $taskSan = [Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder]::new()
    $taskSan.AddIpAddress($taskAddress)
    $taskRequest.CertificateExtensions.Add($taskSan.Build())
    $taskSerial = [Security.Cryptography.RandomNumberGenerator]::GetBytes(16)
    $taskCertificate = $taskRequest.Create($taskCa, $taskNow, $taskNow.AddDays(365), $taskSerial)
    [IO.File]::WriteAllText((Join-Path $taskCertificateDir 'server.pem'), $taskCertificate.ExportCertificatePem() + "`n" + $taskCa.ExportCertificatePem())
    [IO.File]::WriteAllText((Join-Path $taskCertificateDir 'server-key.pem'), $taskServerKey.ExportPkcs8PrivateKeyPem())
    [IO.File]::WriteAllText((Join-Path $taskCertificateDir 'root.pem'), $taskCa.ExportCertificatePem())
    [IO.File]::WriteAllBytes((Join-Path $taskPublic 'Balut-Local-Box.cer'), $taskCa.Export([Security.Cryptography.X509Certificates.X509ContentType]::Cert))
    $taskStore = [Security.Cryptography.X509Certificates.X509Store]::new('Root', 'CurrentUser')
    try { $taskStore.Open('ReadWrite'); $taskStore.Add($taskCa) } finally { $taskStore.Close() }
    $taskProfile = Get-Content -LiteralPath (Join-Path $taskPrivate 'windows.json') -Raw | ConvertFrom-Json -AsHashtable
    $taskProfile.port = $Port
    $taskProfile.https_origin = "https://${Address}:$Port"
    $taskProfile.ssl_certfile = Join-Path $taskCertificateDir 'server.pem'
    $taskProfile.ssl_keyfile = Join-Path $taskCertificateDir 'server-key.pem'
    $taskProfile | ConvertTo-Json | Set-Content -LiteralPath $taskProfilePath -Encoding utf8
    @"
<!doctype html><html lang="en"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Connect Balut on iPhone</title>
<style>body{max-width:38rem;margin:3rem auto;padding:0 1.25rem;font:18px/1.6 system-ui;background:#f6f3eb;color:#15221d}a{color:#165f50}li{margin:1rem 0}</style>
<h1>Connect your iPhone</h1><p>This PC hosts your Balut workspace. Keep both devices on the same router.</p>
<ol><li><a href="/Balut-Local-Box.cer">Download the Balut Local Box certificate</a>. Tap Allow.</li>
<li>Open Settings, then Profile Downloaded. Install <b>Balut Local Box</b>.</li>
<li>Open Settings &gt; General &gt; About &gt; Certificate Trust Settings. Enable full trust for <b>Balut Local Box</b>.</li>
<li><a href="$($taskProfile.https_origin)">Open Balut</a> and sign in with your existing account.</li>
<li>In Safari, tap Share &gt; Add to Home Screen. Enable Open as Web App if shown.</li></ol>
<p>The certificate is issued locally for this PC. Its root signing key was discarded after setup. Remove the Balut profile when you no longer use this box.</p>
<p>Certificate SHA-256: $([Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($taskCa.RawData)))</p>
</html>
"@ | Set-Content -LiteralPath (Join-Path $taskPublic 'index.html') -Encoding utf8
    "[InternetShortcut]`r`nURL=$($taskProfile.https_origin)" | Set-Content -LiteralPath (Join-Path $taskRoot 'Open Balut Phone.url') -Encoding ascii
    Write-Output "Workspace: $($taskProfile.https_origin)"
    Write-Output "iPhone setup: http://${Address}:8770"
    Write-Output "Certificate SHA-256: $([Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($taskCa.RawData)))"
} finally {
    # The root signing key is never saved; only this server's key remains in the protected directory.
    $taskCaKey.Dispose()
    $taskServerKey.Dispose()
}
