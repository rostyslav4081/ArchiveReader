param([switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
if ($SkipBuild) {
    $taskRuntimes = dotnet --list-runtimes
    if ($LASTEXITCODE -ne 0 -or -not ($taskRuntimes -match 'Microsoft.WindowsDesktop.App 10\.')) { throw 'Install the .NET 10 Windows Desktop Runtime and run setup again.' }
}
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { python -m venv .venv }
if ($LASTEXITCODE -ne 0) { throw 'Потрібен Python 3.10–3.13 із pip.' }
& .\.venv\Scripts\python.exe -m pip install -r requirements-ocr-windows.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Не вдалося встановити залежності. Kraken офіційно підтримує Linux/macOS; перевірте журнал встановлення у Windows.' }
if (-not $SkipBuild) {
    dotnet build ArchiveReader.slnx -c Release --nologo
    if ($LASTEXITCODE -ne 0) { throw 'Потрібен .NET 10 SDK із підтримкою Windows Desktop.' }
}
Write-Host 'Готово. Запустіть Start-ArchiveReader.cmd. Для рукописів виберіть локальну модель Kraken.'
