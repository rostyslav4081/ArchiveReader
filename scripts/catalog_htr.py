"""Summarize a locally downloaded HTR-United JSON catalog without fetching datasets."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def summarize(path):
    raw = path.read_bytes()
    catalog = json.loads(raw)
    entries = list(catalog.values()) if isinstance(catalog, dict) else catalog
    languages = Counter(language for entry in entries for language in set(entry.get('language', [])))
    candidates = []
    for entry in entries:
        candidates.append({key: entry.get(key) for key in
                           ['title', 'url', 'language', 'script', 'script-type', 'time', 'license', 'format', 'volume']})
    return {'source': 'https://github.com/HTR-United/htr-united',
            'catalog_sha256': hashlib.sha256(raw).hexdigest(), 'datasets': len(entries),
            'language_codes': len(languages), 'datasets_per_language': dict(languages.most_common()),
            'status': 'Metadata only; no dataset downloaded or evaluated by this command.',
            'candidates': candidates}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('catalog', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = summarize(args.catalog)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"{report['datasets']} datasets; {report['language_codes']} language codes. Metadata only.")
