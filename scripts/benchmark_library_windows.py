"""Synthetic bounded browsing and FTS replacement lookup benchmark, no OCR claims."""
import hashlib
import html
import json
from pathlib import Path
import statistics
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.paging import PagingTools
from backend.archivereader.library import LibraryTools
from backend.archivereader.genealogy import GenealogyTools
from backend.archivereader.operations import Operations
from benchmark_performance import populate


def measured(call, count=12):
    values = []
    for _ in range(count):
        start = time.perf_counter()
        result = call()
        values.append((time.perf_counter() - start) * 1000)
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True).encode()
    return {'samples': count, 'p50_ms': statistics.median(values), 'max_ms': max(values),
            'payload_bytes': len(payload), 'result_sha256': hashlib.sha256(payload).hexdigest()}


def main():
    out = ROOT / 'test-output' / ('library-window-benchmark-' + uuid.uuid4().hex[:10])
    out.mkdir(parents=True)
    engine = Engine(out / 'library')
    paging = PagingTools(engine)
    GenealogyTools(engine)
    Operations(engine)
    library = LibraryTools(engine)
    counts = populate(engine, 10000)
    report = {'counts': counts, 'method': 'Synthetic metadata; in-process calls, no IPC or OCR. Concurrent model experiments may affect timings.'}
    report['full_list'] = measured(lambda: engine.list_pages({}))
    report['window_first'] = measured(lambda: paging.pages_window({'limit': 200}))
    report['window_last'] = measured(lambda: paging.pages_window({'limit': 200, 'offset': 9800}))
    report['window_locate'] = measured(lambda: paging.pages_window({'limit': 200, 'locate': 'p009999'}))
    with engine.db:
        # One synthetic FTS row per page isolates replacement lookup from OCR text size.
        for i in range(10000):
            library._index_insert((f'p{i:06}', 'ocr', '', 'Synthetic archival index control'))
    plain = "SELECT rowid FROM library_fts WHERE page='p009999'"
    indexed = "SELECT entry FROM search_fts_rows WHERE page='p009999'"
    report['fts_scan_lookup'] = measured(lambda: [r[0] for r in engine.db.execute(plain)], 30)
    report['fts_indexed_lookup'] = measured(lambda: [r[0] for r in engine.db.execute(indexed)], 30)
    assert report['fts_scan_lookup']['result_sha256'] == report['fts_indexed_lookup']['result_sha256']
    report['fts_plan'] = [r['detail'] for r in engine.db.execute('EXPLAIN QUERY PLAN ' + indexed)]
    report['background_step'] = library.index_step({'limit': 25, 'budget_ms': 150})
    assert report['background_step']['processed'] <= 25
    assert len(paging.pages_window({'limit': 999999})['rows']) == 200
    engine.db.close()
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    (out / 'report.html').write_text('<!doctype html><meta charset="utf-8"><title>Library benchmark</title><h1>Synthetic library benchmark</h1><p>No recognition speed or historical accuracy claim.</p><pre>' + html.escape(json.dumps(report, ensure_ascii=False, indent=2)) + '</pre>', encoding='utf8')
    print(out, flush=True)


if __name__ == '__main__':
    main()
