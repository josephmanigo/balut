param([string]$Study = 'emeet-mobilenetv2-20261107')
$ErrorActionPreference = 'Stop'
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$dataRoot = [IO.Path]::GetFullPath((Join-Path $workspace 'data'))
$studyRoot = [IO.Path]::GetFullPath((Join-Path $dataRoot "local\$Study"))
if (-not $studyRoot.StartsWith($dataRoot + '\') -or -not (Test-Path -LiteralPath (Join-Path $studyRoot 'reject\audit.json'))) {
    throw 'A verified retained Reject dataset is required before archiving.'
}
$archiveRoot = [IO.Path]::GetFullPath((Join-Path $dataRoot "archive\before-$Study"))
if (-not $archiveRoot.StartsWith($dataRoot + '\')) { throw 'Archive must stay inside project data.' }
if (Test-Path -LiteralPath (Join-Path $archiveRoot 'moves.json')) { throw 'Preserve the existing archive inventory; this migration already ran.' }
$targets = @()
foreach ($kind in @('local', 'public')) {
    $sourceRoot = [IO.Path]::GetFullPath((Join-Path $dataRoot $kind))
    foreach ($folder in Get-ChildItem -LiteralPath $sourceRoot -Directory) {
        if ($folder.FullName -eq $studyRoot) { continue }
        $source = [IO.Path]::GetFullPath($folder.FullName)
        $destination = [IO.Path]::GetFullPath((Join-Path $archiveRoot "$kind\$($folder.Name)"))
        if (-not $source.StartsWith($sourceRoot + '\') -or -not $destination.StartsWith($archiveRoot + '\')) { throw 'Path escaped intended data folders.' }
        if (Test-Path -LiteralPath $destination) { throw "Archive destination already exists: $destination" }
        $targets += [pscustomobject]@{source=$source; destination=$destination}
    }
}
New-Item -ItemType Directory -Path $archiveRoot -Force | Out-Null
$targets | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $archiveRoot 'moves.json') -Encoding utf8
foreach ($target in $targets) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $target.destination) -Force | Out-Null
    Move-Item -LiteralPath $target.source -Destination $target.destination
    if (-not (Test-Path -LiteralPath $target.destination) -or (Test-Path -LiteralPath $target.source)) { throw 'Archive move did not complete.' }
}
"local/$Study" | Set-Content -LiteralPath (Join-Path $dataRoot 'active-study.txt') -Encoding ascii
[pscustomobject]@{archived_folders=$targets.Count; archive=$archiveRoot; active_study=$studyRoot; permanently_deleted=0} | ConvertTo-Json
