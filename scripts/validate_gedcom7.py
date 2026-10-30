"""Cross-check a GEDCOM/GEDZIP locally using a separately obtained karbassi/GEDCOM checkout.

The optional validator is deliberately not a runtime dependency. No genealogy data
is uploaded, and this command neither downloads nor installs third-party code.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    parser.add_argument('--library-source', required=True, type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    source = args.library_source.resolve()
    if not (source / 'src/gedcom/validation.py').is_file():
        parser.error('--library-source must point to a reviewed karbassi/GEDCOM checkout')
    sys.path.insert(0, str(source / 'src'))
    from gedcom import dumps, read_path, read_text, validate

    try:
        document = read_path(args.path.resolve())
        issues = validate(document, strict=True)
        normalized = dumps(document)
        validate(read_text(normalized), strict=True)
        result = {'ok': True, 'issues': issues, 'normalized_utf8_bytes': len(normalized.encode('utf-8')),
                  'scope': 'Strict structural validation and normalized reparse, not verification of historical facts.'}
    except Exception as exc:
        result = {'ok': False, 'error': type(exc).__name__, 'message': str(exc)}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
