"""Compare two corpus-specific Kraken models; optional out-of-domain TrOCR control."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.archivereader.htr_compare import compare


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'test-output/handwriting/manifest.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'test-output/handwriting/comparison')
    parser.add_argument('--with-trocr', action='store_true')
    parser.add_argument('--config', type=Path, help='JSON list of {name, engine, path}; paths relative to that file')
    args = parser.parse_args()
    configs = [
        {'name': 'FoNDUE manuscript GT3', 'engine': 'kraken', 'path': str(ROOT / 'models/fondue-handwriting/model.mlmodel')},
        {'name': 'FoNDUE mixed GT6', 'engine': 'kraken', 'path': str(ROOT / 'models/fondue-mixed/model.mlmodel')},
    ]
    if args.with_trocr:
        configs.append({'name': 'TrOCR IAM English — out-of-domain control', 'engine': 'trocr',
                        'path': str(ROOT / 'models/trocr-small-handwritten')})
    if args.config:
        configs = json.loads(args.config.read_text(encoding='utf-8'))
        for config in configs:
            config['path'] = str((args.config.resolve().parent / config['path']).resolve())
    result = compare(args.manifest, configs, args.output)
    for model in result['models']:
        print(model['name'], 'CER:', model['micro_cer'], 'failed:', model['failed_lines'], model.get('error', ''))
    print(args.output / 'comparison.html')
