"""Fetch seven pinned public EHRI pages and evaluate the local OCR pipeline.

Diagnostic sample only; not a representative benchmark or training dataset.
Source: FloChiff/ehri-dataset, CC-BY 4.0; see docs/INTERNATIONAL.uk.md.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import unicodedata
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.archivereader.engine import Engine, error_rate, parse_alto
from scripts.test_corpus import recognize

REVISION = '20a5e002031c1f9e66176133b4602ed439db6521'
LANGUAGES = ['czech', 'danish', 'english', 'german', 'hungarian', 'polish', 'slovak']


def fetch(url, destination):
    if destination.exists():
        return
    request = urllib.request.Request(url, headers={'User-Agent': 'ArchiveReader-research/0.1'})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(32 * 1024 * 1024 + 1)
    if len(data) > 32 * 1024 * 1024:
        raise ValueError('Sample exceeds 32 MiB limit')
    temporary = destination.with_suffix(destination.suffix + '.part')
    temporary.write_bytes(data)
    temporary.replace(destination)
    time.sleep(1)


def normalized(text):
    return ' '.join(unicodedata.normalize('NFC', text).split())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch', action='store_true', help='Download only; no OCR')
    parser.add_argument('--output', type=Path, default=ROOT / 'test-output' / 'ehri')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    tree_path = output / 'tree.json'
    if args.fetch:
        fetch(f'https://api.github.com/repos/FloChiff/ehri-dataset/git/trees/{REVISION}?recursive=1', tree_path)
    tree = json.loads(tree_path.read_text(encoding='utf-8'))
    if tree['sha'] != REVISION or tree.get('truncated'):
        raise ValueError('Unexpected or incomplete source revision')
    paths = {entry['path']: entry for entry in tree['tree']}
    cases = []
    for language in LANGUAGES:
        image_path = sorted(p for p in paths if p.startswith(f'data/{language}/') and Path(p).suffix.lower() in {'.jpg', '.tif', '.png'})[0]
        xml_path = str(Path(image_path).with_suffix('.xml')).replace('\\', '/')
        case = {'language': language, 'source': image_path, 'revision': REVISION,
                'license': 'CC-BY-4.0', 'selection': 'lexicographically first page per language'}
        for kind, remote_path in [('image', image_path), ('reference', xml_path)]:
            local = output / (language + Path(remote_path).suffix)
            if args.fetch:
                fetch(f'https://raw.githubusercontent.com/FloChiff/ehri-dataset/{REVISION}/{remote_path}', local)
            data = local.read_bytes()
            blob_hash = hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()
            if blob_hash != paths[remote_path]['sha']:
                raise ValueError(f'Source checksum mismatch: {remote_path}')
            case[kind] = str(local)
            case[kind + '_sha256'] = hashlib.sha256(data).hexdigest()
        cases.append(case)
    (output / 'manifest.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.fetch:
        print('Downloaded and verified seven image/ALTO pairs.'); return
    report = {'revision': REVISION, 'model_sha256': hashlib.sha256((ROOT / 'models/kraken-ppocrv6-tiny/tiny.safetensors').read_bytes()).hexdigest(),
              'normalization': 'Unicode NFC; whitespace collapsed; case and punctuation retained',
              'limitations': ['One typewritten page per language, selected without quality filtering.',
                              'Full-page pipeline: segmentation, reading order and recognition errors combined.',
                              'EHRI references exclude some handwritten additions and struck-through text.',
                              'Reference lines retain ALTO XML order; this can differ from visual reading order (observed on Czech sample). Scores are diagnostic, not pure character-recognizer accuracy.',
                              'Training overlap of pretrained weights with this sample is unknown.',
                              'No model was trained or tuned on these pages in this project.'], 'cases': []}
    engine = Engine(output / 'library')
    for case in cases:
        print('Recognizing ' + case['language'], flush=True)
        try:
            imported = engine.import_file({'path': case['image']})
            page = next(p for p in engine.list_pages({}) if p['doc'] == imported['id'])
            # Separate fresh output directory for comparisons; do not overwrite a prior run.
            if page['status'] == 'done':
                engine.set_region({'id': page['id'], 'roi': None})
            result = recognize(engine.root, page, output)
            case['run'] = result
            if result['ok']:
                reference = normalized('\n'.join(line['text'] for line in parse_alto(Path(case['reference']))))
                hypothesis = normalized(engine.details({'id': page['id']})['text'])
                case.update(reference_characters=len(reference), hypothesis_characters=len(hypothesis),
                            cer=error_rate(list(reference), list(hypothesis)),
                            wer=error_rate(reference.split(), hypothesis.split()))
                (output / (case['language'] + '.txt')).write_text(hypothesis, encoding='utf-8')
                print(f"CER={case['cer']}; WER={case['wer']}", flush=True)
        except Exception as exc:
            case['error'] = str(exc)
        report['cases'].append(case)
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    engine.db.close()


if __name__ == '__main__':
    main()
