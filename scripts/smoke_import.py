"""Verify actual WPF-to-Python import, including direct executable launches."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    args = parser.parse_args()
    output = ROOT / 'test-output' / 'desktop-import' / uuid.uuid4().hex
    output.mkdir(parents=True)
    source = args.source
    expected_pages = None
    import pymupdf
    if source is None:
        source = output / 'Метрична книга тест.pdf'
        with pymupdf.open() as document:
            for i in range(3):
                document.new_page().insert_text((72, 72), f'Synthetic import page {i+1}')
            document.save(source)
    with pymupdf.open(source) as document:
        expected_pages = len(document)
    env = os.environ.copy()
    env.pop('ARCHIVEREADER_PYTHON', None)
    env['ARCHIVEREADER_DATA'] = str(output / 'library')
    app = ROOT / 'bin/Release/net10.0-windows/ArchiveReader.exe'
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    result = subprocess.run([str(app), '--smoke-import', str(source.resolve())], env=env,
                            cwd=str(output), startupinfo=startup, timeout=90)
    if result.returncode:
        error = output / 'library/smoke-error.txt'
        raise RuntimeError(error.read_text(encoding='utf-8-sig') if error.exists() else f'Exit {result.returncode}')
    imported = json.loads((output / 'library/smoke-import.json').read_text(encoding='utf-8-sig'))
    if imported['pages'] != expected_pages:
        raise RuntimeError(f'Expected {expected_pages} pages, got {imported}')
    print(f'Direct desktop import: OK ({expected_pages} pages). {output}')


if __name__ == '__main__':
    main()
