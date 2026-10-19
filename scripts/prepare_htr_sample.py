"""Download a small, pinned FoNDUE handwriting diagnostic sample and models."""
import hashlib
import argparse
import dataclasses
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.benchmark_ehri import fetch
from PIL import Image
from kraken.lib.xml import XMLPage
from kraken.lib.segmentation import extract_polygons

REVISION = '40e10ceccfba805ba4244d76af1236cf8255bc06'
TROCR_REVISION = 'b4648cfa171985a6745f37ddd637e98c0da958ac'
REPOSITORY = 'FoNDUE-HTR/FoNDUE_Wolfflin_Fotosammlung'
MODEL = '3_Models/3_1_HTR/HTR_ManuscriptLines_6/HTR_ManuscriptLines_6_best.mlmodel'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pages', type=int, default=20)
    parser.add_argument('--with-trocr', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.pages <= 50:
        parser.error('--pages must be between 1 and 50')
    output = ROOT / 'test-output' / 'handwriting'
    output.mkdir(parents=True, exist_ok=True)
    fetch(f'https://api.github.com/repos/{REPOSITORY}/git/trees/{REVISION}?recursive=1', output / 'tree.json')
    tree = json.loads((output / 'tree.json').read_text(encoding='utf-8'))
    if tree.get('truncated') or tree['sha'] != REVISION:
        raise ValueError('Incomplete or unexpected repository revision')
    paths = {entry['path']: entry for entry in tree['tree']}

    def download(remote, local):
        fetch(f'https://raw.githubusercontent.com/{REPOSITORY}/{REVISION}/{urllib.parse.quote(remote)}', local)
        data = local.read_bytes()
        if hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest() != paths[remote]['sha']:
            raise ValueError('Checksum mismatch: ' + remote)
        return hashlib.sha256(data).hexdigest()

    download('4_Split/ManuscriptLines/test.txt', output / 'test-split.txt')
    download('4_Split/test_all.txt', output / 'test-all-split.txt')
    common = {Path(p).name for p in (output / 'test-all-split.txt').read_text(encoding='utf-8').splitlines()}
    pages = [p for p in (output / 'test-split.txt').read_text(encoding='utf-8').splitlines() if Path(p).name in common][:args.pages]
    if not pages:
        raise ValueError('No common held-out pages between the two upstream test splits')
    cases = []
    for page in pages:
        name = Path(page).name
        remote_xml = '1_Data/1_3_ManuscriptLines/' + name
        remote_image = next(p for p in paths if p.endswith('/' + Path(name).stem + '.jpg'))
        image_path, xml_path = output / Path(remote_image).name, output / name
        image_hash = download(remote_image, image_path)
        xml_hash = download(remote_xml, xml_path)
        with Image.open(image_path) as image:
            segmentation = XMLPage(xml_path).to_container()
            for index, line in enumerate(segmentation.lines):
                if not line.text or not line.text.strip():
                    continue
                crop, _ = next(extract_polygons(image.copy(), dataclasses.replace(segmentation, lines=[line]), legacy=True))
                crop_path = output / f'{Path(name).stem}-line-{index}.png'
                crop.save(crop_path)
                cases.append({'id': crop_path.stem, 'image': crop_path.name, 'reference': line.text,
                              'source': f'https://github.com/{REPOSITORY}/blob/{REVISION}/{remote_xml}',
                              'page_image_sha256': image_hash, 'reference_xml_sha256': xml_hash,
                              'image_sha256': hashlib.sha256(crop_path.read_bytes()).hexdigest(),
                              'split': 'upstream test', 'kind': 'handwritten', 'license': 'CC-BY-4.0',
                              'line_id': line.id, 'extraction': 'shared Kraken legacy baseline polygon extraction',
                              'baseline': line.baseline, 'boundary': line.boundary})
    (output / 'manifest.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding='utf-8')
    model_dir = ROOT / 'models' / 'fondue-handwriting'
    model_dir.mkdir(parents=True, exist_ok=True)
    model_hash = download(MODEL, model_dir / 'model.mlmodel')
    (model_dir / 'provenance.json').write_text(json.dumps({'repository': REPOSITORY, 'revision': REVISION, 'path': MODEL, 'sha256': model_hash, 'license': 'CC-BY-4.0'}, indent=2), encoding='utf-8')
    mixed_dir = ROOT / 'models' / 'fondue-mixed'
    mixed_dir.mkdir(parents=True, exist_ok=True)
    mixed_path = '3_Models/3_1_HTR/AllLines/AllLines_best.mlmodel'
    mixed_hash = download(mixed_path, mixed_dir / 'model.mlmodel')
    (mixed_dir / 'provenance.json').write_text(json.dumps({'repository': REPOSITORY, 'revision': REVISION, 'path': mixed_path, 'sha256': mixed_hash, 'license': 'CC-BY-4.0'}, indent=2), encoding='utf-8')
    if args.with_trocr:
        from huggingface_hub import snapshot_download
        repo = 'microsoft/trocr-small-handwritten'
        destination = ROOT / 'models' / 'trocr-small-handwritten'
        snapshot_download(repo, revision=TROCR_REVISION, local_dir=destination,
                          allow_patterns=['*.json', '*.txt', '*.model', '*.bin', '*.safetensors'], max_workers=2)
        (destination / 'provenance.json').write_text(json.dumps({'repository': repo, 'revision': TROCR_REVISION}, indent=2), encoding='utf-8')
    print(f'Prepared {len(cases)} handwritten lines from {len(pages)} common upstream test pages.')


if __name__ == '__main__':
    main()
