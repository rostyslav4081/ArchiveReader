"""Combine real local checkpoints without confusing coverage with accuracy."""
import hashlib
import html
import json
import os
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'test-output/integrations'


def escaped(value):
    return html.escape(str(value), quote=True)


def relative(path):
    return escaped(os.path.relpath(path, FOLDER).replace('\\', '/'))


def main():
    manifest_path = FOLDER / 'cases.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf8'))
    trials = []
    for name, label in [('pero', 'PERO OCR'), ('paddle', 'PaddleOCR'),
                        ('docling-ocr', 'Docling: OCR (10 прикладів)'),
                        ('docling-structure', 'Docling: структура, без OCR')]:
        path = FOLDER / name / 'report.json'
        if not path.exists():
            continue
        report = json.loads(path.read_text(encoding='utf8'))
        trials.append({'name': name, 'label': label, 'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                       'requested': report.get('requested', report.get('summary', {}).get('requested', report.get('expected_cases', len(report['cases'])))),
                       'phase': report.get('status', report.get('phase', 'in_progress')),
                       'cases': report['cases'], 'packages': report.get('packages', report.get('versions', {'pero-ocr': report.get('version')}))})
    unchanged = []
    for source, original in manifest.get('source_documents', {}).items():
        path = Path(source)
        with path.open('rb') as stream:
            checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        unchanged.append({'path': source, 'unchanged': checksum == original['sha256'], 'sha256': checksum})
    index = {t['name']: {c['id']: c for c in t['cases']} for t in trials}
    summary = {'generated_utc': datetime.now(timezone.utc).isoformat(), 'unique_inputs': len(manifest['cases']),
               'source_aliases': len(manifest['inventory']), 'human_confirmed_references': 0,
               'source_checks': unchanged, 'all_originals_unchanged': bool(unchanged) and all(c['unchanged'] for c in unchanged),
               'trials': [{k: v for k, v in t.items() if k != 'cases'} | {'processed': len(t['cases']), 'failed': sum(str(c['status']).lower() in ('failed', 'failure') for c in t['cases'])} for t in trials]}
    collections = []
    for unit in ['332','334','331','333','335','336']:
        manifest_extra = ROOT / 'test-output' / ('gologory-301-' + unit) / 'cases.json'
        if not manifest_extra.exists():
            continue
        extra = json.loads(manifest_extra.read_text(encoding='utf8'))
        report_name = 'gologory-paddle' if unit == '332' else 'gologory-deaths-paddle' if unit == '334' else 'gologory-' + unit + '-paddle'
        report_path = FOLDER / report_name / 'report.json'
        actual = json.loads(report_path.read_text(encoding='utf8')) if report_path.exists() else {}
        source = Path(extra['source'])
        with source.open('rb') as stream:
            actual_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        collections.append({'unit':unit,'source':str(source),'pages':len(extra['cases']),
                            'original_unchanged':actual_sha == extra['source_sha256'],
                            'prepared_index':str(manifest_extra.parent/'index.html'),
                            'report':str(report_path) if report_path.exists() else None,
                            'processed':len(actual.get('cases',[])),
                            'status':actual.get('status','queued'),
                            'failed':actual.get('summary',{}).get('failed',0)})
    summary['additional_collections'] = collections
    summary['additional_originals_unchanged'] = all(c['original_unchanged'] for c in collections)
    (FOLDER / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf8')
    parts = ['<!doctype html><html lang="uk"><meta charset="utf-8"><title>ArchiveReader — локальні перевірки</title><style>body{font:16px system-ui;margin:24px;background:#f5f3ee;color:#202c30}table{border-collapse:collapse;width:100%;background:white}th,td{border:1px solid #c8ceca;padding:10px;vertical-align:top}th{position:sticky;top:0;background:#e9eee8}pre{white-space:pre-wrap;max-height:420px;overflow:auto;max-width:360px}img{width:180px;max-height:320px;object-fit:contain}input{padding:10px;width:450px;max-width:90%}a{color:#165c80}.note{padding:16px;background:#fff2cc;max-width:1000px}</style><h1>Перевірка на твоїх документах</h1><p class="note">Успішний запуск не означає правильне прочитання. Перевірених людиною транскрипцій основного тексту немає, тому тут немає відсотка точності. Docling «структура» не розпізнає текст. Результати моделей неперевірені; оригінали залишаються локально.</p>',
             '<p>' + str(summary['unique_inputs']) + ' унікальних зображень · ' + str(summary['source_aliases']) + ' посилань на джерела · оригінали без змін: ' + str(summary['all_originals_unchanged']) + '</p><ul>']
    parts.append('</ul><h2>Додані книги Гологір та околиць</h2><p>Окремі прогони, без змішування з початковими 109 зображеннями. Стан «queued» означає: файл підготовлено, модель ще не завершила його обробку.</p><ul>')
    for collection in collections:
        parts.append('<li><a href="' + relative(collection['prepared_index']) + '">AGAD 301/' + escaped(collection['unit']) + ' — усі ' + str(collection['pages']) + ' сканів</a>: модель ' + str(collection['processed']) + '/' + str(collection['pages']) + ' · ' + escaped(collection['status']) + ' · помилок: ' + str(collection['failed']))
        if collection['report']:
            parts.append(' · <a href="' + relative(Path(collection['report']).with_suffix('.html')) + '">Результат моделі</a>')
        candidates = FOLDER / ('gologory-' + collection['unit'] + '-surname') / 'candidates.html'
        if candidates.exists():
            parts.append(' · <a href="' + relative(candidates) + '">Кандидати прізвища</a>')
        parts.append('</li>')
    visual = ROOT / 'test-output/gologory-surname-review/death-scan-005-left-top.png'
    if visual.exists():
        parts.append('</ul><p><a href="' + relative(visual) + '">Непідтверджене візуальне прочитання Mariannam Sko-/wra: 301/334, PDF 5, ліворуч</a>. Дата стосується поховання. Спорідненість не встановлена.</p><ul>')
    parts.append('</ul><h2>Початковий спільний набір моделей</h2><ul>')
    for trial in summary['trials']:
        parts.append('<li><a href="' + relative(Path(trial['path']).with_suffix('.html')) + '">' + escaped(trial['label']) + '</a>: ' + str(trial['processed']) + ' / ' + str(trial['requested']) + ' · помилок: ' + str(trial['failed']) + ' · стан: ' + escaped(trial['phase']) + '</li>')
    parts.append('</ul><label>Знайти файл або сторінку <input id="filter" type="search" placeholder="Назва PDF, номер сторінки, case…"></label><table><thead><tr><th>Зображення і походження</th>' + ''.join('<th>' + escaped(t['label']) + '</th>' for t in trials) + '</tr></thead><tbody>')
    for case in manifest['cases']:
        labels = '\n'.join(a['label'] + (' · сторінка ' + str(a['source_page']) if a.get('source_page') else '') + ' · ' + a['source_document'] for a in case['aliases'])
        parts.append('<tr data-search="' + escaped((case['id'] + ' ' + labels).lower()) + '"><td><b>' + escaped(case['id']) + '</b><br><a href="' + relative(case['image']) + '"><img loading="lazy" src="' + relative(case['image']) + '"></a><details><summary>Джерела (' + str(len(case['aliases'])) + ')</summary><pre>' + escaped(labels) + '</pre></details></td>')
        for trial in trials:
            row = index[trial['name']].get(case['id'])
            if row is None:
                parts.append('<td>Ще не оброблено або поза цим профілем</td>')
                continue
            content = escaped(row['status']) + ' · ' + str(round(row.get('seconds', 0), 2)) + ' с'
            if trial['name'] == 'docling-structure':
                content += '<p>Текст не розпізнавався. Ділянок: ' + escaped(row.get('layout_clusters', 0)) + '; таблиць: ' + escaped(row.get('tables', 0)) + '</p>'
            elif 'texts' in row:
                content += '<pre>' + escaped('\n'.join(row['texts'])) + '</pre>'
            else:
                content += '<p>Текстових елементів: ' + escaped(row.get('text_items', 0)) + '; таблиць: ' + escaped(row.get('tables', 0)) + '</p>'
            if row.get('error') or row.get('errors'):
                content += '<pre>' + escaped(row.get('error', row.get('errors'))) + '</pre>'
            raw = row.get('raw_path')
            if raw:
                content += '<a href="' + relative(raw) + '">Повний результат JSON</a>'
            for key, value in row.get('outputs', {}).items():
                if isinstance(value, str):
                    target = Path(value)
                    if not target.is_absolute():
                        target = Path(trial['path']).parent / target
                    if target.is_file():
                        content += '<br><a href="' + relative(target) + '">' + escaped(key) + '</a>'
            parts.append('<td>' + content + '</td>')
        parts.append('</tr>')
    parts.append('</tbody></table><script>document.getElementById("filter").addEventListener("input",e=>{let q=e.target.value.toLowerCase();document.querySelectorAll("tr[data-search]").forEach(r=>r.hidden=!r.dataset.search.includes(q));});</script></html>')
    (FOLDER / 'comparison.html').write_text(''.join(parts), encoding='utf8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'source_checks'}, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
