$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'installation.json')) {
    $env:ARCHIVEREADER_DATA = Join-Path $env:LOCALAPPDATA 'ArchiveReader\data'
} else { $env:ARCHIVEREADER_DATA = Join-Path $PSScriptRoot 'data' }
$env:ARCHIVEREADER_KRAKEN = Join-Path $PSScriptRoot '.venv\Scripts\kraken.exe'
$taskDefaultModel = Join-Path $PSScriptRoot 'models\kraken-ppocrv6-medium\medium.safetensors'
if (-not (Test-Path -LiteralPath $taskDefaultModel)) { $taskDefaultModel = Join-Path $PSScriptRoot 'models\kraken-ppocrv6-tiny\tiny.safetensors' }
if (Test-Path -LiteralPath $taskDefaultModel) { $env:ARCHIVEREADER_MODEL = $taskDefaultModel }
$env:PYTHONUTF8 = '1'
$localPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $localPython) { $env:ARCHIVEREADER_PYTHON = $localPython }
$app = Join-Path $PSScriptRoot 'bin\Release\net10.0-windows\ArchiveReader.exe'
$taskSourcePaths = @('src', 'backend') | ForEach-Object { Join-Path $PSScriptRoot $_ }
$taskNewestSource = Get-ChildItem -LiteralPath $taskSourcePaths -Recurse -File | Where-Object { $_.FullName -notmatch '[\\/](bin|obj)[\\/]' -and $_.Extension -in @('.cs', '.xaml', '.csproj', '.json', '.py') } | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
$taskAssembly = Join-Path (Split-Path -Parent $app) 'ArchiveReader.dll'
if (-not (Test-Path -LiteralPath $taskAssembly) -or ($taskNewestSource -and $taskNewestSource.LastWriteTimeUtc -gt (Get-Item -LiteralPath $taskAssembly).LastWriteTimeUtc)) {
    dotnet build ArchiveReader.slnx -c Release --nologo
    if ($LASTEXITCODE -ne 0) { throw 'ArchiveReader build failed. See the output above.' }
}
Start-Process -FilePath $app -WorkingDirectory $PSScriptRoot -WindowStyle Normal
