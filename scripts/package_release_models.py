"""Build optional model assets from pinned public files, without private documents."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
import zipfile


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        while chunk := source.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group', choices=['PolishWords', 'PolishExperimental'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    metadata = root / 'docs/release-models'
    item = next(row for row in json.loads((metadata / 'manifest.json').read_text('utf-8')) if row['group'] == args.group)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    # Keep intermediate weights outside the asset directory uploaded by the workflow.
    work = output.parent / ('model-work-' + args.group)
    model = work / 'models' / item['folder']
    model.mkdir(parents=True, exist_ok=True)
    for name, expected in item['files'].items():
        path = model / name
        if not path.exists() or sha256(path) != expected:
            url = 'https://huggingface.co/' + item['repository'] + '/resolve/' + item['revision'] + '/' + name
            partial = path.with_suffix(path.suffix + '.partial')
            print('Fetching ' + name, flush=True)
            with urllib.request.urlopen(url, timeout=300) as response, partial.open('wb') as target:
                shutil.copyfileobj(response, target, length=8 * 1024 * 1024)
            if sha256(partial) != expected:
                raise ValueError('Upstream checksum mismatch: ' + name)
            partial.replace(path)
    archive = work / ('ArchiveReader-Models-' + args.group + '-v0.1.0.zip')
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as package:
        for path in sorted(model.iterdir()):
            if path.is_file() and path.name in item['files']:
                package.write(path, path.relative_to(work).as_posix())
        for path in metadata.iterdir():
            package.write(path, 'model-licenses/' + path.name)
        package.writestr('MODEL_PACKS.md', (metadata / 'README.md').read_text('utf-8'))
        package.writestr('model-licenses/ATTRIBUTION.json', json.dumps(item, indent=2))
    with zipfile.ZipFile(archive) as package:
        if package.testzip() is not None:
            raise ValueError('Archive integrity check failed')
    assets = []
    # GitHub limits each release asset; a standard ZIP can be reassembled exactly.
    limit = 900 * 1024 * 1024
    if archive.stat().st_size > 2_000_000_000:
        with archive.open('rb') as source:
            index = 1
            while True:
                target = output / (archive.name + f'.part{index:02d}')
                remaining = min(limit, archive.stat().st_size - source.tell())
                if remaining <= 0:
                    break
                with target.open('wb') as part:
                    while remaining:
                        chunk = source.read(min(8 * 1024 * 1024, remaining))
                        if not chunk:
                            raise ValueError('Unexpected end of archive')
                        part.write(chunk)
                        remaining -= len(chunk)
                assets.append(target)
                index += 1
        merge = output / 'Merge-ModelParts.ps1'
        expected = sha256(archive)
        merge.write_text("""$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskTarget = Join-Path $PSScriptRoot 'ARCHIVE_NAME'
if (Test-Path -LiteralPath $taskTarget) { throw 'The target ZIP already exists.' }
$taskParts = Get-ChildItem -LiteralPath $PSScriptRoot -File | Where-Object { $_.Name -like 'ARCHIVE_NAME.part*' } | Sort-Object Name
if ($taskParts.Count -ne PART_COUNT) { throw 'Download every model part first.' }
$taskStream = [IO.File]::Create($taskTarget)
try {
    foreach ($taskPart in $taskParts) {
        $taskInput = [IO.File]::OpenRead($taskPart.FullName)
        try { $taskInput.CopyTo($taskStream) } finally { $taskInput.Dispose() }
    }
} finally { $taskStream.Dispose() }
if ((Get-FileHash -LiteralPath $taskTarget -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'EXPECTED_SHA') { throw 'Checksum mismatch. Do not extract this ZIP.' }
Write-Host 'Model ZIP verified. Extract it into the installed ArchiveReader folder.'
""".replace('ARCHIVE_NAME', archive.name).replace('PART_COUNT', str(len(assets))).replace('EXPECTED_SHA', expected), 'utf-8')
        assets.append(merge)
    else:
        target = output / archive.name
        shutil.copyfile(archive, target)
        assets.append(target)
    (output / (args.group + '-SHA256SUMS.txt')).write_text(''.join(sha256(path) + '  ' + path.name + '\n' for path in assets), 'utf-8')
    print('Prepared ' + str(len(assets)) + ' verified assets', flush=True)


if __name__ == '__main__':
    main()
