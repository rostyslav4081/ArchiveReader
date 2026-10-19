"""Add supplied books to the existing private lab without changing previous research."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.archivereader.engine import Engine


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, default=ROOT/'test-output/gologory-inputs.json')
    parser.add_argument('--library', type=Path, default=ROOT/'test-output/htr-lab-20261015/library')
    args = parser.parse_args()
    library = args.library.resolve()
    if not library.is_relative_to((ROOT/'test-output').resolve()):
        raise ValueError('This test helper only adds to an existing test-output library.')
    if not (library / 'archive.sqlite').is_file():
        raise ValueError('Existing private lab not found; refusing to select another library.')
    engine = Engine(library)
    try:
        before = {r[0] for r in engine.db.execute('SELECT id FROM documents')}
        records_before = [(r[0], r[1], r[2]) for r in engine.db.execute('SELECT id,page,data FROM records ORDER BY id')]
        results = []
        sources = [Path(p) for p in json.loads(args.sources.read_text(encoding='utf8'))['sources']]
        for source in sources:
            checksum = sha(source)
            imported = engine.import_file({'path': str(source)})
            pages = engine.db.execute('SELECT COUNT(*) FROM pages WHERE doc=?', (imported['id'],)).fetchone()[0]
            if sha(source) != checksum:
                raise ValueError('Source checksum changed')
            results.append({'source': str(source), 'source_sha256': checksum, 'original_unchanged': True,
                            'import': imported, 'pages': pages, 'ocr_status': 'pending; separate experimental model outputs are not verified library text'})
        after = {r[0] for r in engine.db.execute('SELECT id FROM documents')}
        assert before <= after
        assert records_before == [(r[0], r[1], r[2]) for r in engine.db.execute('SELECT id,page,data FROM records ORDER BY id')]
        report = {'library': str(library), 'previous_documents_preserved': True, 'previous_records_unchanged': True,
                  'documents_before': len(before), 'documents_after': len(after), 'added_books': results}
        destination = ROOT / 'test-output/gologory-added-to-lab.json'
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
        print(json.dumps({'report': str(destination), 'pages': [r['pages'] for r in results], 'documents': len(after)}), flush=True)
    finally:
        engine.db.close()


if __name__ == '__main__':
    main()
