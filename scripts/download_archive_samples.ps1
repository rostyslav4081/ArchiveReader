param([string]$Destination)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Destination) { $Destination = Join-Path $projectRoot 'test-output/archive-samples' }
New-Item -ItemType Directory -Force -Path $Destination | Out-Null
$samples = Get-Content -LiteralPath (Join-Path $projectRoot 'docs/archive-samples.json') -Raw -Encoding utf8 | ConvertFrom-Json
foreach ($sample in $samples) {
    if ([IO.Path]::GetFileName($sample.file) -ne $sample.file) { throw 'Invalid sample filename.' }
    $target = Join-Path $Destination $sample.file
    if ((Test-Path -LiteralPath $target) -and (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -eq $sample.sha256) {
        Write-Output ($sample.country + ': verified existing ' + $sample.file)
        continue
    }
    $partial = $target + '.partial'
    try {
        Invoke-WebRequest -Uri $sample.url -OutFile $partial -TimeoutSec 120
        if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash -ne $sample.sha256) {
            throw ('Source changed: ' + $sample.file + '. Check the catalog and update provenance before using it as the same sample.')
        }
        Move-Item -LiteralPath $partial -Destination $target -Force
        Write-Output ($sample.country + ': downloaded ' + $sample.file)
    } finally {
        if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial }
    }
}
Copy-Item -LiteralPath (Join-Path $projectRoot 'docs/archive-samples.json') -Destination (Join-Path $Destination 'provenance.json') -Force
