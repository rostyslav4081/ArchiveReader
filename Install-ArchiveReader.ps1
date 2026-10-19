param(
    [string]$Destination = (Join-Path $env:LOCALAPPDATA 'Programs\ArchiveReader'),
    [switch]$SkipDependencies,
    [switch]$NoShortcut
)
$ErrorActionPreference = 'Stop'
$taskSource = [IO.Path]::GetFullPath($PSScriptRoot)
$taskDestination = [IO.Path]::GetFullPath($Destination)
if ($taskDestination -eq $taskSource -or $taskSource.StartsWith($taskDestination.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Choose a separate installation folder.' }
New-Item -ItemType Directory -Path $taskDestination -Force | Out-Null
# An update copies application files only. Existing libraries and backup vaults are never deleted.
foreach ($taskDirectory in @('backend','src','scripts','docs')) {
    $taskFolder = Join-Path $taskSource $taskDirectory
    if (Test-Path -LiteralPath $taskFolder) {
        Get-ChildItem -LiteralPath $taskFolder -Recurse -File | Where-Object { $_.FullName -notmatch '[\\/](bin|obj|__pycache__)[\\/]' } | ForEach-Object {
            $taskRelative = $_.FullName.Substring($taskSource.Length + 1)
            $taskTarget = Join-Path $taskDestination $taskRelative
            New-Item -ItemType Directory -Path (Split-Path -Parent $taskTarget) -Force | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $taskTarget -Force
        }
    }
}
foreach ($taskFile in @('ArchiveReader.slnx','README.md','pyproject.toml','requirements.txt','requirements-ocr.txt','requirements-ocr-windows.lock.txt','requirements-htr.txt','Start-ArchiveReader.cmd','Start-ArchiveReader.ps1','Install-ArchiveReader.cmd','Install-ArchiveReader.ps1')) {
    Copy-Item -LiteralPath (Join-Path $taskSource $taskFile) -Destination $taskDestination -Force
}
$taskBinaries = Join-Path $taskSource 'bin\Release\net10.0-windows'
if (-not (Test-Path -LiteralPath (Join-Path $taskBinaries 'ArchiveReader.exe'))) { throw 'Build or use the Windows package before installing.' }
$taskInstalledBinaries = Join-Path $taskDestination 'bin\Release\net10.0-windows'
New-Item -ItemType Directory -Path $taskInstalledBinaries -Force | Out-Null
Get-ChildItem -LiteralPath $taskBinaries -File | Where-Object { $_.Extension -in @('.exe','.dll','.json','.py') } | Copy-Item -Destination $taskInstalledBinaries -Force
[IO.File]::WriteAllText((Join-Path $taskDestination 'installation.json'), '{"mode":"per-user","library":"LocalAppData/ArchiveReader/data","modelsBundled":false}')
if (-not $SkipDependencies) {
    & (Join-Path $taskDestination 'scripts\Setup.ps1') -SkipBuild
    if ($LASTEXITCODE -ne 0) { throw 'Dependency setup failed. Check the installation output.' }
}
if (-not $NoShortcut) {
    $taskShell = New-Object -ComObject WScript.Shell
    $taskShortcut = $taskShell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'ArchiveReader.lnk'))
    $taskShortcut.TargetPath = Join-Path $taskDestination 'Start-ArchiveReader.cmd'
    $taskShortcut.WorkingDirectory = $taskDestination
    $taskShortcut.Save()
}
Write-Host "ArchiveReader installed: $taskDestination"
Write-Host 'Imported documents and model weights are not included. Select your local model in the program.'
