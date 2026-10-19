param([switch]$NoBuild)
$ErrorActionPreference = 'Stop'
$taskProject = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskProject
if (-not $NoBuild) {
    dotnet build ArchiveReader.slnx -c Release --nologo --warnaserror
    if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
}
$taskPackage = Join-Path $taskProject ('dist\ArchiveReader-Windows-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
& (Join-Path $taskProject 'Install-ArchiveReader.ps1') -Destination $taskPackage -SkipDependencies -NoShortcut
$taskZip = $taskPackage + '.zip'
Compress-Archive -LiteralPath $taskPackage -DestinationPath $taskZip
Write-Host "Package ready: $taskZip"
