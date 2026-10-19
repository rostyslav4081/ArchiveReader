"""Add catalog provenance and one explicitly unverified visual candidate to the lab."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.sources import SourceTools
from backend.archivereader.library import LibraryTools

CATALOG = 'https://www.agad.gov.pl/inwentarze/KLwo301new.xml'
METADATA = {
    '331': ('Lipowce i Majdan Lipowiecki — urodzenia 1800–1834', '1800–1834'),
    '332': ('Gołogóry — śluby dla całej parafii 1755–1795', '1755–1795'),
    '333': ('Żuków — śluby 1806–1862', '1806–1862'),
    '334': ('Gołogóry — zgony i pogrzeby dla całej parafii 1755–1795', '1755–1795'),
    '335': ('Gołogóry i miejscowości parafii — zgony 1827–1834', '1827–1834'),
    '336': ('Gołogóry i miejscowości parafii — ekstrakty urodzeń, ślubów i zgonów 1839', '1839 (poświadczone 1840)'),
}


def main():
    imported = json.loads((ROOT / 'test-output/gologory-added-to-lab.json').read_text(encoding='utf8'))
    engine = Engine(imported['library'])
    saved = []
    try:
        sources = SourceTools(engine)
        for book in imported['added_books']:
            unit = next(n for n in METADATA if f'301_{n}' in book['source'])
            doc = book['import']['id']
            first = engine.db.execute('SELECT id FROM pages WHERE doc=? ORDER BY num LIMIT 1', (doc,)).fetchone()[0]
            if not engine.db.execute('SELECT 1 FROM book_sources WHERE doc=?', (doc,)).fetchone():
                title, years = METADATA[unit]
                card = sources.source_card({'id': first, 'book': {
                    'archive': 'Archiwum Główne Akt Dawnych (AGAD), Warszawa', 'country': 'Polska',
                    'collection': 'Księgi metrykalne wyznania rzymskokatolickiego z archidiecezji lwowskiej',
                    'fonds': '301', 'file': unit, 'title': title,
                    'place': 'Lipowce / Majdan Lipowiecki' if unit == '331' else 'Żuków' if unit == '333' else 'Parafia Gołogóry',
                    'url': f'http://agadd.home.net.pl/metrykalia/301/sygn.%20{unit}/indeks.htm', 'accessed': '2026-10-15',
                    'notes': f'Опис справи звірено з офіційним інвентарем AGAD: {CATALOG}. Роки: {years}. Основна мова за каталогом — латина. Номер сторінки PDF не дорівнює написаному номеру сторінки чи позначенню архівного скану. Факти про осіб і спорідненість не підтверджено.'
                }})
                saved.append({'unit': unit, 'source_signature': card['signature']})
            if unit == '334':
                page = engine.db.execute('SELECT id FROM pages WHERE doc=? AND num=4', (doc,)).fetchone()[0]
                match = json.loads((ROOT / 'test-output/gologory-source-research/death-page005-match.json').read_text())
                assert any(c['bytes_equal'] for c in match['comparisons'])
                if not engine.db.execute('SELECT 1 FROM page_sources WHERE page=?', (page,)).fetchone():
                    sources.source_card({'id': page, 'page_values': {
                        'original_page': '6 (ліва сторінка; поруч олівцем 4)', 'image_number': '5',
                        'scan_label': match['archive_scan_label'], 'page_url': match['archive_page_url'],
                        'page_notes': 'PDF: сторінка 5 із 123, ліва половина розвороту. JPEG з офіційної галереї та вбудований JPEG PDF побайтово однакові; SHA-256: ' + match['archive_image_sha256']
                    }})
                annotation = 'gologory-334-scan005-skowra-candidate'
                if not engine.db.execute('SELECT 1 FROM annotations WHERE id=?', (annotation,)).fetchone():
                    sources.save_annotation({'page': page, 'annotation': annotation, 'data': {
                        'kind': 'entry', 'rect': [.07, .10, .43, .125], 'verified': False,
                        'text': 'Непідтверджений кандидат Skowra / Skowyra. Попереднє прочитання ШІ: «Mariannam Sko-/wra [?]». Заголовок September 1755; Die 12 / Sepelivi: ймовірна дата ПОХОВАННЯ 12 вересня 1755, не окремо встановлена дата смерті. Прізвище потребує людської перевірки. Статус вдови не підтверджений. Спорідненість не встановлена.',
                        'provenance': {'type': 'unverified_visual_candidate', 'source_pdf_page_1based': 5,
                                       'archive_scan': match['archive_scan_label'], 'archive_image_sha256': match['archive_image_sha256'],
                                       'literal_partial_reading': 'Mariannam Sko-/wra', 'human_verified': False}
                    }})
                saved.append({'unit': unit, 'page': page, 'annotation': annotation, 'verified': False})
        index = LibraryTools(engine)
        for _ in range(30):
            if index.index_step({'limit': 25, 'budget_ms': 150})['complete']:
                break
        result = {'library': str(engine.root), 'saved': saved, 'index': index.index_status({}),
                  'policy': 'Catalog descriptions and candidate regions only. No person, family relationship or verified transcription created.'}
        (ROOT / 'test-output/gologory-source-research/attached-to-lab.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
        print(json.dumps(result, ensure_ascii=True), flush=True)
    finally:
        engine.db.close()


if __name__ == '__main__':
    main()
