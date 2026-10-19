"""Reproducible, local PERO printed-model control; never a handwriting accuracy claim."""
import configparser
import hashlib
import html
import json
import os
from pathlib import Path
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMBA_NUM_THREADS'):
    os.environ[key] = '4'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(folder, report):
    report['summary'] = {'attempted': len(report['cases']), 'requested': report['requested'],
                         'failed': sum(c['status'] == 'failed' for c in report['cases']),
                         'source_aliases': sum(len(c['aliases']) for c in report['cases'])}
    temporary = folder / 'report.json.partial'
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    os.replace(temporary, folder / 'report.json')
    rows = []
    for case in report['cases']:
        photo = html.escape(os.path.relpath(case['image'], folder).replace('\\', '/'), quote=True)
        rows.append('<tr><td>' + html.escape(case['id']) + '<br><img width="220" src="' + photo + '"></td><td>' + html.escape(case['status']) + '<br>' + str(round(case.get('seconds', 0), 2)) + ' s<br>' + html.escape(case.get('error', '')) + '</td><td><pre>' + html.escape('\n'.join(case.get('texts', []))[:6000]) + '</pre></td></tr>')
    (folder / 'report.html').write_text('<!doctype html><meta charset="utf-8"><title>PERO local control</title><style>body{font:16px sans-serif;margin:28px}td{border:1px solid #aaa;padding:12px;vertical-align:top}pre{white-space:pre-wrap;max-width:700px}</style><h1>PERO: printed European/Czech model control</h1><p>No human-confirmed reference text. Execution and coverage only, no CER/WER or handwriting accuracy claim. Local CPU, language-model decoder disabled. Originals untouched.</p><p>' + html.escape(str(report['summary'])) + '</p><table>' + ''.join(rows) + '</table>', encoding='utf8')


def main():
    import cv2
    import torch
    from pero_ocr.document_ocr.page_parser import PageParser
    from pero_ocr.core.layout import PageLayout
    import importlib.metadata
    cv2.setNumThreads(1)
    torch.set_num_threads(4)
    folder = ROOT / 'test-output/integrations/pero'
    (folder / 'raw').mkdir(parents=True, exist_ok=True)
    manifest = ROOT / 'test-output/integrations/cases.json'
    cases = json.loads(manifest.read_text(encoding='utf8'))['cases']
    config_path = ROOT / 'models/pero-print/engine/pero_eu_cz_print_newspapers_2022-09-26/config_cpu.ini'
    signature = digest(config_path)
    previous = {}
    if (folder / 'report.json').exists():
        old = json.loads((folder / 'report.json').read_text(encoding='utf8'))
        if old.get('configuration_sha256') == signature:
            previous = {c['id']: c for c in old['cases']}
    report = {'tool': 'PERO OCR', 'version': importlib.metadata.version('pero-ocr'),
              'manifest': str(manifest), 'manifest_sha256': digest(manifest),
              'configuration_sha256': signature, 'configuration': str(config_path),
              'requested': len(cases), 'cases': [], 'policy': 'Printed-model control, not validated HTR. No reference text, no accuracy metric. Local CPU, decoder disabled.'}
    started = time.perf_counter()
    config = configparser.ConfigParser()
    config.read(config_path, encoding='utf8')
    try:
        pipeline = PageParser(config, device=torch.device('cpu'), config_path=str(config_path.parent))
    except Exception as exc:
        report.update(status='startup_failed', error=str(exc), traceback=traceback.format_exc())
        save(folder, report)
        raise
    report['model_load_seconds'] = time.perf_counter() - started
    patch_file = ROOT / 'models/pero-print/compatibility.json'
    patch = json.loads(patch_file.read_text(encoding='utf8')) if patch_file.exists() else None
    report['compatibility_patch'] = patch
    report['first_pass_report'] = str(folder / 'first-pass-unpatched.json') if (folder / 'first-pass-unpatched.json').exists() else None
    report['reused_successes'] = 0
    report['retried_failures'] = []
    for case in cases:
        prior = previous.get(case['id'])
        if prior and prior.get('image_sha256') == case['image_sha256'] and prior['status'] != 'failed':
            prior.setdefault('compatibility_mode', 'upstream')
            report['cases'].append(prior)
            report['reused_successes'] += 1
        else:
            result = dict(case)
            result['compatibility_mode'] = 'isolated_shapely2_patch' if patch else 'upstream'
            if prior and prior['status'] == 'failed':
                result['previous_failure'] = prior.get('error')
                report['retried_failures'].append(case['id'])
            start = time.perf_counter()
            try:
                if digest(case['image']) != case['image_sha256']:
                    raise ValueError('Input checksum changed')
                image = cv2.imread(case['image'])
                if image is None:
                    raise ValueError('Cannot decode input image')
                page = PageLayout(id=case['id'], page_size=image.shape[:2])
                page = pipeline.process_page(image, page)
                lines = [{'id': line.id, 'text': line.transcription or '',
                          'polygon': line.polygon.tolist() if line.polygon is not None else None,
                          'baseline': line.baseline.tolist() if line.baseline is not None else None}
                         for line in page.lines_iterator()]
                raw = folder / 'raw' / (case['id'] + '.json')
                raw.write_text(json.dumps(lines, ensure_ascii=False, indent=2), encoding='utf8')
                exports = {}
                for format_name, method in [('page', page.to_pagexml), ('alto', page.to_altoxml)]:
                    target = folder / 'raw' / (case['id'] + '.' + format_name + '.xml')
                    try:
                        method(str(target))
                        exports[format_name] = str(target)
                    except Exception as exc:
                        exports[format_name + '_error'] = str(exc)
                texts = [line['text'] for line in lines]
                result.update(status='recognized_unverified' if any(t.strip() for t in texts) else 'empty',
                              texts=texts, lines=len(lines), regions=len(page.regions), raw_path=str(raw),
                              exports=exports, source_unchanged=digest(case['image']) == case['image_sha256'])
            except Exception as exc:
                result.update(status='failed', error=str(exc), traceback=traceback.format_exc())
            result['seconds'] = time.perf_counter() - start
            report['cases'].append(result)
        save(folder, report)
        print(case['id'], report['cases'][-1]['status'], flush=True)
    report.update(status='complete', run_seconds=time.perf_counter() - started)
    save(folder, report)


if __name__ == '__main__':
    main()
