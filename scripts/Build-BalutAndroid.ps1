param(
    [string]$FlutterExecutable = 'C:\balut-dev\flutter\bin\flutter.bat',
    [string]$Server = 'http://127.0.0.1:8765'
)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskMobile = Join-Path $taskRoot 'apps\mobile'
$taskUri = $null
if (-not [Uri]::TryCreate($Server, [UriKind]::Absolute, [ref]$taskUri) -or
    $taskUri.UserInfo -or $taskUri.Query -or $taskUri.Fragment -or $taskUri.AbsolutePath -ne '/' -or
    ($taskUri.Scheme -ne 'https' -and -not ($taskUri.Scheme -eq 'http' -and $taskUri.Host -in @('127.0.0.1', 'localhost')))) {
    throw 'Use an HTTPS server origin, or HTTP loopback for USB testing.'
}
if (-not (Get-Command $FlutterExecutable -ErrorAction SilentlyContinue)) { throw 'Pass -FlutterExecutable with the path to your Flutter SDK.' }
$taskJavaOptions = $env:JAVA_TOOL_OPTIONS
# Java falls back to TCP when AF_UNIX is unavailable in a Windows app host.
$taskUnusedPipePath = Join-Path ([IO.Path]::GetTempPath()) ('balut-unused-pipes-' + [Guid]::NewGuid().ToString('N'))
try {
    $env:JAVA_TOOL_OPTIONS = "$taskJavaOptions `"-Djdk.net.unixdomain.tmpdir=$taskUnusedPipePath`"".Trim()
    Push-Location $taskMobile
    & $FlutterExecutable pub get
    if ($LASTEXITCODE) { throw 'Flutter dependency resolution failed.' }
    & $FlutterExecutable analyze --no-pub
    if ($LASTEXITCODE) { throw 'Flutter analysis failed.' }
    & $FlutterExecutable test --no-pub
    if ($LASTEXITCODE) { throw 'Flutter tests failed.' }
    & $FlutterExecutable build apk --release --no-pub "--dart-define=BALUT_SERVER=$Server"
    if ($LASTEXITCODE) { throw 'Android build failed.' }
    $taskOutput = Join-Path $taskRoot 'artifacts\EggGrade-IoT-Android-0.4.1-preview.apk'
    Copy-Item -LiteralPath (Join-Path $taskMobile 'build\app\outputs\flutter-apk\app-release.apk') -Destination $taskOutput
    Get-FileHash -LiteralPath $taskOutput -Algorithm SHA256
    Write-Output 'Preview APK uses the Android debug signing key. Configure release signing before distribution.'
}
finally {
    Pop-Location
    $env:JAVA_TOOL_OPTIONS = $taskJavaOptions
}
