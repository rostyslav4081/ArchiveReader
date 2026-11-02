"""Local, process-isolated ArchiveReader document engine. JSON in, JSON out."""
from __future__ import annotations
import csv
import ctypes
import hashlib
import io
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile

KINDS = ['Інші записи та примітки', 'Народження', 'Шлюби', 'Смерті', 'Нерозбірливі записи']
FIELDS = ['kind', 'number', 'date', 'person', 'related1', 'related2', 'age', 'cause', 'notes', 'place', 'house', 'text', 'verified']


class Engine:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ['originals', 'cache', 'results', 'models']:
            (self.root / name).mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / 'archive.sqlite', timeout=30)
        self.db.row_factory = sqlite3.Row
        # Readers may stay open while short write transactions update the library.
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, name TEXT, path TEXT, sha TEXT UNIQUE);
        CREATE TABLE IF NOT EXISTS pages(id TEXT PRIMARY KEY, doc TEXT REFERENCES documents(id), num INTEGER,
          status TEXT DEFAULT 'pending', text TEXT DEFAULT '', lines TEXT DEFAULT '[]', error TEXT DEFAULT '',
          engine TEXT DEFAULT '', elapsed REAL DEFAULT 0, UNIQUE(doc,num));
        CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, page TEXT REFERENCES pages(id), data TEXT);
        CREATE TABLE IF NOT EXISTS corrections(id INTEGER PRIMARY KEY, record TEXT, before TEXT, after TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS line_corrections(page TEXT REFERENCES pages(id), line INTEGER, original TEXT,
          corrected TEXT, verified INTEGER, box TEXT, PRIMARY KEY(page,line));
        CREATE TABLE IF NOT EXISTS line_history(id INTEGER PRIMARY KEY, page TEXT, line INTEGER, before TEXT, after TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS recognition_history(id INTEGER PRIMARY KEY, page TEXT REFERENCES pages(id), text TEXT, lines TEXT, engine TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')
        if 'roi' not in {row['name'] for row in self.db.execute('PRAGMA table_info(pages)')}:
            self.db.execute("ALTER TABLE pages ADD COLUMN roi TEXT DEFAULT 'null'")
            self.db.commit()

        try:
            from .schema_indexes import ensure_indexes
        except ImportError:from schema_indexes import ensure_indexes
        ensure_indexes(self.db)

    def settings(self, a):
        if 'values' in a:
            with self.db:
                for k, v in a['values'].items():
                    self.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (k, json.dumps(v, ensure_ascii=False)))
        return {r['key']: json.loads(r['value']) for r in self.db.execute('SELECT * FROM settings')}

    def profile(self, a):
        ram = 4 * 1024**3
        available = ram
        if os.name == 'nt':
            class Memory(ctypes.Structure):
                _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [(n, ctypes.c_ulonglong) for n in ['total', 'available', 'page', 'freepage', 'virtual', 'freevirtual', 'extended']]
            m = Memory(); m.length = ctypes.sizeof(m)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                ram, available = m.total, m.available
        gpu = []
        try:
            p = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=5, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            gpu = p.stdout.strip().splitlines() if p.returncode == 0 else []
        except (OSError, subprocess.TimeoutExpired):
            pass
        return {'cpu': os.cpu_count(), 'ramGB': round(ram / 1024**3, 1), 'availableGB': round(available / 1024**3, 1),
                'workers': max(1, min(2, (os.cpu_count() or 2)//2, int(available / (3*1024**3)))),
                'gpu': gpu, 'diskFreeGB': round(shutil.disk_usage(self.root).free / 1024**3, 1)}

    def import_file(self, a):
        from PIL import Image
        src = Path(a['path']).resolve()
        digest = hashlib.sha256()
        with src.open('rb') as f:
            for chunk in iter(lambda: f.read(1024*1024), b''):
                digest.update(chunk)
        sha = digest.hexdigest()
        existing = self.db.execute('SELECT id FROM documents WHERE sha=?', (sha,)).fetchone()
        if existing:
            return {'id': existing['id'], 'duplicate': True}
        if src.suffix.lower() == '.pdf':
            import pymupdf as fitz
            with fitz.open(src) as doc:
                if doc.needs_pass:
                    raise ValueError('PDF захищений паролем. Імпортуйте розблоковану копію.')
                count = len(doc)
        else:
            with Image.open(src) as im:
                count = getattr(im, 'n_frames', 1)
        if not count:
            raise ValueError('Документ не містить сторінок.')
        ident = uuid.uuid4().hex
        dest = self.root / 'originals' / (sha + src.suffix.lower())
        temp = dest.with_suffix(dest.suffix + '.partial')
        shutil.copyfile(src, temp)
        # Verify the copy too: a changing input must never be recorded under the wrong hash.
        with temp.open('rb') as copy:
            copied = hashlib.file_digest(copy, 'sha256').hexdigest()
        if copied != sha:
            temp.unlink(missing_ok=True)
            raise ValueError('Файл змінився під час імпорту. Спробуйте ще раз.')
        os.replace(temp, dest)
        with self.db:
            self.db.execute('INSERT INTO documents VALUES (?,?,?,?)', (ident, str(a.get('name') or src.name), str(dest), sha))
            self.db.executemany('INSERT INTO pages(id,doc,num) VALUES (?,?,?)', [(uuid.uuid4().hex, ident, n) for n in range(count)])
        return {'id': ident, 'pages': count, 'duplicate': False}

    def list_pages(self, a):
        query = '''SELECT p.*,d.name,d.path FROM pages p JOIN documents d ON p.doc=d.id'''
        args = ()
        if a.get('search'):
            query += " WHERE p.text LIKE ? OR d.name LIKE ? OR EXISTS (SELECT 1 FROM records r WHERE r.page=p.id AND r.data LIKE ?)"
            args = tuple('%'+a['search']+'%' for _ in range(3))
        query += ' ORDER BY d.rowid,p.num'
        rows=[dict(r) | {'label': f"{r['name']} · {r['num']+1} · {r['status']}"} for r in self.db.execute(query, args)]
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='book_items'").fetchone():
            groups={r['page']:dict(r) for r in self.db.execute('SELECT i.page,i.position,i.label,b.id AS book,b.name AS book_name FROM book_items i JOIN photo_books b ON b.id=i.book WHERE i.page IS NOT NULL')}
            anchors={}
            for index,row in enumerate(rows):
                if row['id'] in groups:anchors.setdefault(groups[row['id']]['book'],index)
            for index,row in enumerate(rows):
                item=groups.get(row['id']);row['_sort']=(anchors[item['book']],item['position']) if item else (index,0)
                if item:row.update(book=item['book'],book_position=item['position']+1,book_name=item['book_name'],display_name=f"{item['book_name']} · {item['position']+1} · {item['label'] or row['name']}")
            rows.sort(key=lambda row:row.pop('_sort'))
        return rows

    def page(self, ident):
        row = self.db.execute('SELECT p.*,d.path,d.name FROM pages p JOIN documents d ON d.id=p.doc WHERE p.id=?', (ident,)).fetchone()
        if row is None:
            raise ValueError('Сторінку не знайдено.')
        return dict(row)

    def render(self, a):
        from PIL import Image, ImageOps, ImageFilter, ImageMath
        p = self.page(a['id'])
        full = bool(a.get('full'))
        roi = json.loads(p['roi']) if full and not a.get('whole') else None
        mode = a.get('preprocess', 'original')
        if mode not in ['original', 'contrast', 'binary', 'lighting']:
            raise ValueError('Невідомий режим обробки.')
        region_key=hashlib.sha256(json.dumps(roi).encode()).hexdigest()[:8] if full else 'whole'
        dest = self.root / 'cache' / f"{p['id']}-{'ocr' if full else 'view'}-{mode}-{region_key}.png"
        if dest.exists():
            os.utime(dest, None)
            with Image.open(dest) as cached_image:
                return {'path': str(dest), 'width': cached_image.width, 'height': cached_image.height, 'roi':roi}
        max_side = 7000 if full else 1800
        if Path(p['path']).suffix.lower() == '.pdf':
            import pymupdf as fitz
            with fitz.open(p['path']) as doc:
                page = doc[p['num']]
                factor = min(300/72 if full else 140/72, max_side/max(page.rect.width, page.rect.height))
                pix = page.get_pixmap(matrix=fitz.Matrix(factor, factor), alpha=False)
                im = Image.frombytes('RGB', [pix.width, pix.height], pix.samples)
        else:
            with Image.open(p['path']) as source:
                source.seek(p['num'])
                im = ImageOps.exif_transpose(source).convert('RGB')
                im.thumbnail((max_side, max_side))
        if roi:
            x,y,w,h=roi
            im=im.crop((int(x*im.width),int(y*im.height),min(im.width,int((x+w)*im.width)),min(im.height,int((y+h)*im.height))))
        if mode == 'lighting':
            gray = ImageOps.grayscale(im)
            background = gray.filter(ImageFilter.GaussianBlur(max(12, min(im.size)/35)))
            im = ImageMath.lambda_eval(lambda args: 210 * args['ink'] / (args['background'] + 1), ink=gray.convert('F'), background=background.convert('F')).convert('L')
            im = ImageOps.autocontrast(im, cutoff=0.1)
        elif mode != 'original':
            im = ImageOps.autocontrast(ImageOps.grayscale(im)).filter(ImageFilter.MedianFilter(3))
            if mode == 'binary':
                im = im.point(lambda x: 255 if x > 160 else 0)
        temp = dest.with_name(dest.name + '.' + uuid.uuid4().hex + '.tmp')
        im.save(temp, format='PNG')
        os.replace(temp, dest)
        # LRU disk cache, bounded at 2 GiB. Do not evict recent files in active workers.
        cached = sorted((f for f in (self.root/'cache').glob('*.png')), key=lambda f:f.stat().st_mtime)
        total = sum(f.stat().st_size for f in cached)
        for f in cached:
            if total <= 2*1024**3:
                break
            if time.time()-f.stat().st_mtime > 3600:
                size = f.stat().st_size
                try:
                    f.unlink(); total -= size
                except OSError:
                    pass
        return {'path': str(dest), 'width': im.width, 'height': im.height, 'roi':roi}

    def image_quality(self, a):
        from PIL import Image, ImageOps, ImageStat
        rendering = self.render({'id': a['id'], 'full': True})
        with Image.open(rendering['path']) as source:
            gray = ImageOps.grayscale(source)
            gray.thumbnail((1600, 1600))
        histogram = gray.histogram()
        count = sum(histogram)
        def percentile(fraction):
            total = 0
            for value, amount in enumerate(histogram):
                total += amount
                if total >= count * fraction:
                    return value
            return 255
        p05, median, p95 = percentile(.05), percentile(.5), percentile(.95)
        flags = []
        if max(rendering['width'], rendering['height']) < 1200:
            flags.append('small')
        if p95-p05 < 40:
            flags.append('low_contrast')
        if median < 70:
            flags.append('dark')
        if p05 > 230:
            flags.append('pale_or_blank')
        return {'width': rendering['width'], 'height': rendering['height'], 'flags': flags,
                'contrast_p95_p05': p95-p05, 'median_luminance': median,
                'scope': 'Rendered OCR region, heuristic image statistics only. Not a legibility, damage or missing-text detector.'}

    def set_region(self, a):
        p=self.page(a['id'])
        if self.db.execute('SELECT 1 FROM line_corrections WHERE page=? LIMIT 1',(p['id'],)).fetchone():
            raise ValueError('Сторінка має виправлені рядки. Повторне OCR заблоковано для збереження прив’язки.')
        roi=a.get('roi')
        if roi is not None:
            if len(roi)!=4 or not all(isinstance(v,(int,float)) for v in roi): raise ValueError('Invalid region')
            x,y,w,h=roi
            if not (0<=x<1 and 0<=y<1 and 0.005<=w<=1 and 0.005<=h<=1 and x+w<=1.000001 and y+h<=1.000001): raise ValueError('Invalid region')
        with self.db:
            if p['text']:
                self.db.execute('INSERT INTO recognition_history(page,text,lines,engine) VALUES (?,?,?,?)',(p['id'],p['text'],p['lines'],p['engine']))
            self.db.execute("UPDATE pages SET roi=?,status='pending',text='',lines='[]',error='' WHERE id=?",(json.dumps(roi),p['id']))
        return {'roi':roi}

    def details(self, a):
        p = self.page(a['id'])
        p['lines'] = json.loads(p['lines'])
        try:from .recognition_workflow import review_flags
        except ImportError:from recognition_workflow import review_flags
        for line in p['lines']:line['review_flags']=review_flags(line.get('text'))
        for correction in self.db.execute('SELECT * FROM line_corrections WHERE page=?', (p['id'],)):
            if correction['line'] < len(p['lines']):
                p['lines'][correction['line']]['corrected'] = correction['corrected']
                p['lines'][correction['line']]['verified'] = bool(correction['verified'])
        p['records'] = [json.loads(r['data']) | {'id': r['id']} for r in self.db.execute('SELECT * FROM records WHERE page=? ORDER BY rowid', (p['id'],))]
        p['suggestion'] = suggest_record(p['text'])
        return p

    def save_record(self, a):
        self.page(a['page'])
        ident = a.get('id') or uuid.uuid4().hex
        data = {k: a.get(k, False if k == 'verified' else '') for k in FIELDS}
        if data['kind'] not in KINDS:
            raise ValueError('Невідомий тип запису.')
        data['verified'] = bool(data['verified'])
        encoded = json.dumps(data, ensure_ascii=False)
        with self.db:
            old = self.db.execute('SELECT data,page FROM records WHERE id=?', (ident,)).fetchone()
            if old and old['page'] != a['page']:
                raise ValueError('Запис належить іншій сторінці.')
            if not old or old['data'] != encoded:
                self.db.execute('INSERT INTO corrections(record,before,after) VALUES (?,?,?)', (ident, old['data'] if old else None, encoded))
            self.db.execute('INSERT INTO records VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data', (ident, a['page'], encoded))
        return {'id': ident}

    def save_line(self, a):
        p = self.page(a['id']); lines = json.loads(p['lines'])
        n = int(a['line'])
        if not 0 <= n < len(lines): raise ValueError('Неправильний номер рядка.')
        line = lines[n]
        with self.db:
            old=self.db.execute('SELECT corrected,verified FROM line_corrections WHERE page=? AND line=?',(p['id'],n)).fetchone()
            before={'text':old['corrected'],'verified':bool(old['verified'])} if old else {'text':line['text'],'verified':False}
            after={'text':a['text'],'verified':bool(a.get('verified',False))}
            if before!=after:
                self.db.execute('INSERT INTO line_history(page,line,before,after) VALUES (?,?,?,?)',(p['id'],n,json.dumps(before,ensure_ascii=False),json.dumps(after,ensure_ascii=False)))
            self.db.execute('INSERT OR REPLACE INTO line_corrections VALUES (?,?,?,?,?,?)', (p['id'], n, line['text'], a['text'], int(a.get('verified', False)), json.dumps(line.get('box'))))
        return {'saved': True}

    def recover(self, a):
        with self.db:
            n = self.db.execute("UPDATE pages SET status='pending',error='Попередню обробку перервано' WHERE status='running'").rowcount
        return {'recovered': n}

    def recognize(self, a):
        p = self.page(a['id'])
        if p['status'] == 'done' and not a.get('force'):
            return {'skipped': True}
        # Replacing line geometry would invalidate existing verified training examples.
        if self.db.execute('SELECT 1 FROM line_corrections WHERE page=? LIMIT 1', (p['id'],)).fetchone():
            raise ValueError('Сторінка має виправлені рядки. Повторне OCR заблоковано для збереження прив’язки.')
        started = time.monotonic()
        with self.db:
            self.db.execute("UPDATE pages SET status='running',error='' WHERE id=?", (p['id'],))
        try:
            text, lines, engine = '', [], a.get('engine', 'kraken')
            if Path(p['path']).suffix.lower() == '.pdf' and a.get('useTextLayer', True) and not json.loads(p['roi']):
                import pymupdf as fitz
                with fitz.open(p['path']) as doc:
                    pdf_page=doc[p['num']]
                    # Captions and fragmentary OCR layers must not bypass a photographed
                    # manuscript. Dominant raster pages use the selected OCR/HTR model.
                    area=max(1,pdf_page.rect.get_area())
                    image_area=sum((fitz.Rect(info['bbox']) & pdf_page.rect).get_area() for info in pdf_page.get_image_info())
                    text = pdf_page.get_text(sort=True).strip() if image_area/area < .25 else ''
                    if text:
                        engine = 'PDF text layer'
            if not text:
                source = self.render({'id': p['id'], 'full': True, 'preprocess': a.get('preprocess', 'original')})['path']
                exe = a.get('executable') or engine
                with tempfile.TemporaryDirectory(dir=self.root/'results') as temp:
                    if engine == 'kraken':
                        model = Path(a.get('model', ''))
                        if not model.is_file():
                            raise ValueError('Виберіть локальну модель Kraken (.mlmodel або .safetensors).')
                        out = Path(temp)/'result.xml'
                        local_executable=exe in ['kraken','kraken.exe'] or Path(exe).resolve().parent==Path(sys.executable).resolve().parent
                        if os.environ.get('ARCHIVEREADER_MODEL_SESSION')=='1' and a.get('device','cpu')=='cpu' and local_executable:
                            try:
                                from .recognizers import kraken_page
                            except ImportError:from recognizers import kraken_page
                            lines=kraken_page(source,str(model),a.get('segmentation') or None,out)
                        else:
                            cmd = [exe, '-r', '-i', source, str(out), '-a', '--device', a.get('device', 'cpu'), 'segment', '-bl']
                            if a.get('segmentation'):
                                cmd.extend(['-m', a['segmentation']])
                            cmd.extend(['ocr', '-m', str(model)])
                            run_process(cmd, a.get('timeout', 900))
                            lines = parse_alto(out)
                        text = '\n'.join(line['text'] for line in lines)
                        shutil.copyfile(out, self.root/'results'/f"{p['id']}.alto.xml")
                    elif engine == 'trocr':
                        try:
                            from .recognizers import trocr_page
                        except ImportError:from recognizers import trocr_page
                        if not Path(a.get('model','')).is_dir():raise ValueError('Виберіть папку локальної моделі TrOCR.')
                        lines=trocr_page(source,a['model'],a.get('segmentation') or None)
                        text='\n'.join(line['text'] for line in lines)
                    elif engine == 'paddle':
                        try:from .paddle_local import recognize as paddle_recognize
                        except ImportError:from paddle_local import recognize as paddle_recognize
                        result=paddle_recognize(source,a['model'],a.get('timeout',900));text=result['text'];lines=result['lines']
                    elif engine == 'tesseract':
                        output = Path(temp)/'result'
                        run_process([exe, source, str(output), '-l', a.get('languages', 'eng'), 'tsv'], a.get('timeout', 900))
                        lines = parse_tsv(output.with_suffix('.tsv'))
                        text = '\n'.join(line['text'] for line in lines)
                    else:
                        raise ValueError('Непідтримуваний рушій OCR.')
            with self.db:
                if p['text']:
                    self.db.execute('INSERT INTO recognition_history(page,text,lines,engine) VALUES (?,?,?,?)',(p['id'],p['text'],p['lines'],p['engine']))
                self.db.execute("UPDATE pages SET status='done',text=?,lines=?,engine=?,elapsed=?,error='' WHERE id=?", (text, json.dumps(lines, ensure_ascii=False), engine, time.monotonic()-started, p['id']))
            return {'text': text, 'lines': len(lines), 'engine': engine}
        except Exception as e:
            with self.db:
                self.db.execute("UPDATE pages SET status='error',error=?,elapsed=? WHERE id=?", (str(e), time.monotonic()-started, p['id']))
            raise

    def export(self, a):
        try:
            from .sources import SourceTools,EXPORT_FIELDS
        except ImportError:
            from sources import SourceTools,EXPORT_FIELDS
        sources=SourceTools(self)
        rows = []
        field_evidence={}
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='field_proposal_runs'").fetchone():
            for item in self.db.execute('SELECT data FROM field_proposal_runs'):
                proposal=json.loads(item['data'])
                if proposal.get('applied_record'):
                    field_evidence.setdefault(proposal['applied_record'],[]).append({'citation':proposal['citation'],'source_text':proposal['text'],'source_signature':proposal['signature'],
                        'selected':[proposal['candidates'][i] for i in proposal['selected']]})
        people_links={}
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='person_links'").fetchone():
            try:
                from .people import PeopleTools
            except ImportError:
                from people import PeopleTools
            people=PeopleTools(self)
            for link in people.link_inventory():
                for side in ['left','right']:
                    people_links.setdefault(link[side]['record'],[]).append(link)
        has_evidence=bool(self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='annotations'").fetchone())
        for p in self.list_pages({}):
            if a.get('doc') and p['doc'] != a['doc']:
                continue
            if a.get('pages') and p['id'] not in a['pages']:
                continue
            records = self.details({'id': p['id']})['records']
            source_card=sources.source_card({'id':p['id']})
            if not records:
                records = [dict.fromkeys(FIELDS, '') | {'kind': KINDS[0], 'text': p['text'], 'verified': False}]
            for r in records:
                evidence={'person_links':people_links.get(r.get('id'),[]),'field_evidence':field_evidence.get(r.get('id'),[])}
                if has_evidence:
                    profile=self.db.execute('SELECT data FROM book_profiles WHERE doc=?',(p['doc'],)).fetchone()
                    evidence.update({'page_id':p['id'],'document_id':p['doc'],'regions':[json.loads(region['data'])|{'id':region['id']} for region in self.db.execute('SELECT id,data FROM annotations WHERE page=?',(p['id'],))], 'book_profile':json.loads(profile['data']) if profile else {}})
                rows.append(r | {'document': p['name'], 'page': p['num']+1, 'source': p['path'], 'ocr_engine': p['engine'], 'ocr_status': p['status'], 'ocr_error': p['error'], 'page_text': p['text'],'source_card':source_card} | evidence | sources.export_values(source_card))
        dest = Path(a['path'])
        dest.parent.mkdir(parents=True, exist_ok=True)
        temp = dest.with_name(dest.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            if dest.suffix.lower() == '.xlsx':
                write_xlsx(temp, rows)
            elif dest.suffix.lower() == '.json':
                temp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
            elif dest.suffix.lower() == '.csv':
                keys = FIELDS + ['document','page','source','ocr_engine','ocr_status','ocr_error','page_text']+[key for key,_ in EXPORT_FIELDS]
                with temp.open('w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore'); writer.writeheader()
                    for row in rows:
                        writer.writerow({k: csv_safe(v) for k,v in row.items() if k in keys})
            elif dest.suffix.lower() == '.txt':
                temp.write_text('\n\n'.join(f"{r['document']} / {r['page']}\n{r['source_citation']}\n{r['text']}" for r in rows), encoding='utf-8')
            else:
                raise ValueError('Підтримується XLSX, JSON, CSV, TXT.')
            os.replace(temp, dest)
        finally:
            temp.unlink(missing_ok=True)
        return {'path': str(dest), 'records': len(rows)}

    def training(self, a):
        from PIL import Image
        dest = Path(a['path']); dest.mkdir(parents=True, exist_ok=True)
        train, validation, manifest = [], [], []
        candidates = self.db.execute('SELECT * FROM line_corrections WHERE verified=1 ORDER BY page,line').fetchall()
        corrections = [r for r in candidates if r['corrected'].strip() and not uncertain_text(r['corrected'])]
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='book_profiles'").fetchone():
            test_docs={r['doc'] for r in self.db.execute('SELECT * FROM book_profiles') if json.loads(r['data']).get('split')=='test'}
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='derivatives'").fetchone():
                edges=[(r['doc'],r['parent_doc']) for r in self.db.execute('SELECT d.doc,p.doc AS parent_doc FROM derivatives d JOIN pages p ON p.id=d.parent_page')]
                while True:
                    extended=test_docs|{x for x,y in edges if y in test_docs}|{y for x,y in edges if x in test_docs}
                    if extended==test_docs: break
                    test_docs=extended
            corrections=[r for r in corrections if self.page(r['page'])['doc'] not in test_docs]
        docs = sorted({self.page(r['page'])['doc'] for r in corrections})
        validation_docs = set(docs[-max(1, len(docs)//5):]) if len(docs)>1 else set()
        for r in corrections:
            if not r['corrected'].strip():
                continue
            box = json.loads(r['box'])
            if not box:
                continue
            p = self.page(r['page'])
            # Split by document to avoid adjacent pages leaking into validation.
            split = 'validation' if p['doc'] in validation_docs else 'train'
            image_path = self.render({'id': r['page'], 'full': True})['path']
            name = f"{r['page']}-{r['line']}"
            with Image.open(image_path) as im:
                x,y,w,h = box
                bounds = (max(0,int(x)),max(0,int(y)),min(im.width,int(x+w)),min(im.height,int(y+h)))
                if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
                    continue
                im.crop(bounds).save(dest/(name+'.png'))
            (dest/(name+'.gt.txt')).write_text(r['corrected'], encoding='utf-8')
            (validation if split == 'validation' else train).append(str((dest/(name+'.png')).resolve()))
            manifest.append({'image': name+'.png', 'text': r['corrected'], 'document': p['doc'], 'page': p['num']+1, 'split': split})
        for name, lines in [('train.txt', train), ('validation.txt', validation)]:
            (dest/name).write_text('\n'.join(lines), encoding='utf-8')
        (dest/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        return {'train': len(train), 'validation': len(validation), 'path': str(dest), 'excluded_uncertain': len(candidates)-len(corrections)}

    def quality(self, a):
        chars = words = char_errors = word_errors = count = 0
        for r in self.db.execute('SELECT original,corrected FROM line_corrections WHERE verified=1'):
            if uncertain_text(r['corrected']) or not r['corrected'].strip():
                continue
            ref, hyp = r['corrected'], r['original']
            if ref:
                char_errors += round(error_rate(list(ref), list(hyp))*len(ref))
                chars += len(ref)
            if ref.split():
                word_errors += round(error_rate(ref.split(), hyp.split())*len(ref.split()))
                words += len(ref.split())
            count += 1
        return {'lines':count, 'CER':char_errors/chars if chars else None, 'WER':word_errors/words if words else None,
                'scope':'Manually selected verified lines; not an independent accuracy benchmark.'}

    def train_model(self, a):
        model=Path(a['model']).resolve()
        if not model.is_file():
            raise ValueError('Виберіть локальну модель Kraken (.mlmodel або .safetensors).')
        run=self.root/'models'/('training-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
        if a.get('explicit'):
            try:
                from .workbench import Workbench
            except ImportError:
                from workbench import Workbench
            data=Workbench(self).dataset_explicit({'path':str(run/'dataset')})
        else:
            data=self.training({'path':str(run/'dataset')})
        if not data['train'] or not data['validation']:
            raise ValueError('Training requires verified lines from at least two different documents (training and validation).')
        epochs=int(a.get('epochs',20))
        if not 1<=epochs<=100: raise ValueError('Epochs must be between 1 and 100')
        cmd=[a.get('executable','ketos'),'train','--load',str(model),'-f','path','-t',str(run/'dataset'/'train.txt'),
             '-e',str(run/'dataset'/'validation.txt'),'--output',str(run/'checkpoints'),'--epochs',str(epochs),'--quit','fixed']
        with model.open('rb') as source:
            model_hash=hashlib.file_digest(source,'sha256').hexdigest()
        (run/'run.json').write_text(json.dumps({'command':cmd,'base_model':str(model),'base_sha256':model_hash,'data':data},indent=2),encoding='utf-8')
        # Save output directly to disk: training logs must not accumulate in UI memory.
        env=os.environ.copy(); env['PYTHONUTF8']='1'
        with (run/'training.log').open('w',encoding='utf-8') as log:
            result=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:
            raise RuntimeError(f'Training failed. See {run / "training.log"}')
        outputs=[str(f) for f in (run/'checkpoints').rglob('*.safetensors')]
        provenance=json.loads((run/'run.json').read_text(encoding='utf-8'))
        provenance['output_models']=[{'path':path,'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()} for path in outputs]
        (run/'run.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
        return {'path':str(run),'promoted':False,'models':outputs}

    def evaluate(self, a):
        reference, hypothesis = a['reference'], a['hypothesis']
        return {'CER': error_rate(list(reference), list(hypothesis)), 'WER': error_rate(reference.split(), hypothesis.split())}


def run_process(cmd, timeout):
    env = os.environ.copy()
    env['PYTHONUTF8'] = '1'
    env.setdefault('OMP_NUM_THREADS', str(max(1, min(4, os.cpu_count() or 1))))
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=int(timeout), env=env,
                                encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except FileNotFoundError:
        raise ValueError(f'Не знайдено OCR: {cmd[0]}. Укажіть шлях до встановленого рушія.')
    if result.returncode:
        raise RuntimeError(result.stderr[-2500:] or f'OCR завершився з кодом {result.returncode}')


def parse_alto(path):
    tree = ET.parse(path)
    lines = []
    for line in tree.getroot().iter():
        if line.tag.split('}')[-1] != 'TextLine':
            continue
        words = [e for e in line.iter() if e.tag.split('}')[-1] == 'String']
        text = ' '.join(e.get('CONTENT','') for e in words)
        scores = [float(e.get('WC')) for e in words if e.get('WC') is not None]
        box = None
        if all(k in line.attrib for k in ['HPOS','VPOS','WIDTH','HEIGHT']):
            box = [float(line.get(k)) for k in ['HPOS','VPOS','WIDTH','HEIGHT']]
        elif words and all(all(k in e.attrib for k in ['HPOS','VPOS','WIDTH','HEIGHT']) for e in words):
            x = min(float(e.get('HPOS')) for e in words); y = min(float(e.get('VPOS')) for e in words)
            box = [x,y,max(float(e.get('HPOS'))+float(e.get('WIDTH')) for e in words)-x,max(float(e.get('VPOS'))+float(e.get('HEIGHT')) for e in words)-y]
        lines.append({'text':text,'box':box,'confidence':sum(scores)/len(scores) if scores else None})
    return lines


def parse_tsv(path):
    groups = {}
    with open(path, encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f, delimiter='\t'):
            if r['level'] != '5' or not r.get('text','').strip():
                continue
            key = tuple(r[k] for k in ['page_num','block_num','par_num','line_num'])
            groups.setdefault(key, []).append(r)
    result = []
    for words in groups.values():
        x=min(int(w['left']) for w in words); y=min(int(w['top']) for w in words)
        box=[x,y,max(int(w['left'])+int(w['width']) for w in words)-x,max(int(w['top'])+int(w['height']) for w in words)-y]
        scores=[float(w['conf'])/100 for w in words if float(w['conf']) >= 0]
        result.append({'text':' '.join(w['text'] for w in words),'box':box,'confidence':sum(scores)/len(scores) if scores else None})
    return result


def uncertain_text(text):
    return bool(re.search(r'\[(?:lacuna|illegible|…|\.\.\.|\?)\]', text, flags=re.IGNORECASE))


def error_rate(reference, hypothesis):
    if not reference:
        return 0.0 if not hypothesis else None
    previous = list(range(len(hypothesis)+1))
    for i,a in enumerate(reference,1):
        current=[i]
        for j,b in enumerate(hypothesis,1):
            current.append(min(current[-1]+1,previous[j]+1,previous[j-1]+(a!=b)))
        previous=current
    return previous[-1]/len(reference)


def suggest_record(text):
    """Conservative, inspectable keyword hints. Never infer personal names."""
    patterns={KINDS[1]:r'\b(?:baptiz\w*|natus|nata|urodz\w*|народжен\w*|narozen\w*|birth)\b',
              KINDS[2]:r'\b(?:copulat\w*|matrimon\w*|nupt\w*|ślub\w*|шлюб\w*|sňat\w*|marriage)\b',
              KINDS[3]:r'\b(?:mortu\w*|obiit|defunct\w*|zmar\w*|помер\w*|úmrt\w*|death)\b'}
    matches={k:re.findall(p,text,re.IGNORECASE) for k,p in patterns.items()}
    found=[k for k,v in matches.items() if v]
    return {'kind':found[0] if len(found)==1 else KINDS[0], 'evidence':matches, 'requires_review':True}


def csv_safe(value):
    if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@','\t','\r')):
        return "'"+value
    return value


def xml_text(value):
    # XML 1.0 forbids most controls, which sometimes occur in extracted PDF text.
    return ''.join(c for c in str(value) if c in '\t\n\r' or 0x20 <= ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF)


def write_xlsx(path, rows):
    try:
        from .sources import EXPORT_FIELDS
    except ImportError:
        from sources import EXPORT_FIELDS
    ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    rel='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    headers=['№ запису','Дата','Особа','Батько / наречена','Мати / свідки','Примітки','Населений пункт','№ будинку','Повна транскрипція','Перевірено','Документ','Сторінка','Оригінал','OCR рушій','Стан OCR','Помилка OCR','Текст сторінки OCR (без виправлень)','Вік','Причина смерті']
    keys=['number','date','person','related1','related2','notes','place','house','text','verified','document','page','source','ocr_engine','ocr_status','ocr_error','page_text','age','cause']
    headers += [label for _,label in EXPORT_FIELDS]; keys += [key for key,_ in EXPORT_FIELDS]
    def column_name(index):
        label=''; index+=1
        while index: index,remainder=divmod(index-1,26); label=chr(65+remainder)+label
        return label
    workbook=ET.Element('workbook',xmlns=ns); sheets=ET.SubElement(workbook,'sheets')
    rels=ET.Element('Relationships',xmlns='http://schemas.openxmlformats.org/package/2006/relationships')
    types=ET.Element('Types',xmlns='http://schemas.openxmlformats.org/package/2006/content-types')
    ET.SubElement(types,'Default',Extension='rels',ContentType='application/vnd.openxmlformats-package.relationships+xml')
    ET.SubElement(types,'Default',Extension='xml',ContentType='application/xml')
    ET.SubElement(types,'Override',PartName='/xl/workbook.xml',ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml')
    def data(element): return ET.tostring(element, encoding='utf-8', xml_declaration=True)
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        for i,kind in enumerate(KINDS,1):
            ET.SubElement(sheets,'sheet',name=kind,sheetId=str(i),attrib={f'{{{rel}}}id':f'rId{i}'})
            ET.SubElement(rels,'Relationship',Id=f'rId{i}',Type=rel+'/worksheet',Target=f'worksheets/sheet{i}.xml')
            ET.SubElement(types,'Override',PartName=f'/xl/worksheets/sheet{i}.xml',ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml')
            sheet=ET.Element('worksheet',xmlns=ns)
            views=ET.SubElement(sheet,'sheetViews'); view=ET.SubElement(views,'sheetView',workbookViewId='0')
            ET.SubElement(view,'pane',ySplit='1',topLeftCell='A2',activePane='bottomLeft',state='frozen')
            cols=ET.SubElement(sheet,'cols'); ET.SubElement(cols,'col',min='1',max=str(len(keys)),width='24',customWidth='1')
            ET.SubElement(cols,'col',min='9',max='9',width='70',customWidth='1')
            sheetdata=ET.SubElement(sheet,'sheetData')
            selected=[r for r in rows if r['kind']==kind]
            actual_headers=headers.copy()
            if kind==KINDS[1]: actual_headers[2:5]=['Ім’я дитини','Батько','Мати']
            if kind==KINDS[2]: actual_headers[2:5]=['Наречений','Наречена','Свідки']
            for n,values in enumerate([actual_headers]+[[r.get(k,'') for k in keys] for r in selected],1):
                row=ET.SubElement(sheetdata,'row',r=str(n))
                for j,value in enumerate(values):
                    text=str(value) if not isinstance(value,bool) else ('Так' if value else 'Ні')
                    if len(text)>32767:
                        raise ValueError('Транскрипція перевищує ліміт комірки Excel (32767 символів). Використайте JSON або розділіть записи.')
                    c=ET.SubElement(row,'c',r=f'{column_name(j)}{n}',t='inlineStr'); inline=ET.SubElement(c,'is')
                    ET.SubElement(inline,'t',attrib={'{http://www.w3.org/XML/1998/namespace}space':'preserve'}).text=xml_text(text)
            ET.SubElement(sheet,'autoFilter',ref=f'A1:{column_name(len(keys)-1)}{len(selected)+1}')
            z.writestr(f'xl/worksheets/sheet{i}.xml',data(sheet))
        z.writestr('xl/workbook.xml',data(workbook)); z.writestr('xl/_rels/workbook.xml.rels',data(rels))
        z.writestr('[Content_Types].xml',data(types))
        rootrels=ET.Element('Relationships',xmlns='http://schemas.openxmlformats.org/package/2006/relationships')
        ET.SubElement(rootrels,'Relationship',Id='rId1',Type=rel+'/officeDocument',Target='xl/workbook.xml')
        z.writestr('_rels/.rels',data(rootrels))


def handle_request(request):
    if request['command'] in ['backup_list','backup_restore']:
        try:
            from .backups import BackupTools,RecoveryLibrary
        except ImportError:from backups import BackupTools,RecoveryLibrary
        return getattr(BackupTools(RecoveryLibrary(request['root'])),request['command'])(request)
    if request['command'] in ['bundle_inspect','bundle_restore']:
        try:
            from .backups import RecoveryLibrary
            from .research_bundle import ResearchBundleTools
        except ImportError:
            from backups import RecoveryLibrary
            from research_bundle import ResearchBundleTools
        recovery=RecoveryLibrary(request['root'])
        (recovery.root/'cache').mkdir(parents=True,exist_ok=True)
        return getattr(ResearchBundleTools(recovery),request['command'])(request)
    engine=Engine(request['root'])
    try:
        commands={name:getattr(engine,name) for name in ['settings','profile','import_file','list_pages','render','details','save_record','save_line','recover','recognize','export','training','evaluate','quality','train_model','set_region','image_quality']}
        if request['command']=='shape_search':
            try:from .shape_search import ShapeSearch
            except ImportError:from shape_search import ShapeSearch
            commands['shape_search']=ShapeSearch(engine).shape_search
        if request['command'] in ['workflow_status','workflow_model_status']:
            try:from .recognition_workflow import RecognitionWorkflow
            except ImportError:from recognition_workflow import RecognitionWorkflow
            commands[request['command']]=getattr(RecognitionWorkflow(engine),request['command'])
        extra=['book_profile','annotations','save_annotation','delete_annotation','region_crop','compare_regions','heldout_compare','similar_names','dataset_explicit','prepare_photo','import_derivative']
        if request['command'] in extra:
            try:
                from .workbench import Workbench
            except ImportError:
                from workbench import Workbench
            workbench=Workbench(engine)
            commands.update({name:getattr(workbench,name) for name in extra})
        library_commands=['index_status','index_step','library_search','review_queue','review_context','review_resolve','history_list','history_restore','template_save','template_apply','template_list','benchmark_inventory','benchmark_freeze','benchmark_compare']
        if request['command'] in library_commands:
            try:
                from .library import LibraryTools
            except ImportError:
                from library import LibraryTools
            library=LibraryTools(engine)
            commands.update({name:getattr(library,name) for name in library_commands})
        if request['command'] in ['page_review_start','page_review_step','page_review_status','page_review_fork']:
            try:from .page_review import PageReviewTools
            except ImportError:from page_review import PageReviewTools
            commands.update({name:getattr(PageReviewTools(engine),name) for name in ['page_review_start','page_review_step','page_review_status','page_review_fork']})
        layout_commands=['layout_propose','layout_apply','layout_order','recognize_region','region_recognition_apply','region_ordered_text','layout_quality','layout_edit_lines','layout_compare','book_quality_map']
        if request['command'] in layout_commands:
            try:
                from .layout import LayoutTools
            except ImportError:
                from layout import LayoutTools
            layout=LayoutTools(engine)
            commands.update({name:getattr(layout,name) for name in layout_commands})
        if request['command']=='source_card':
            try:
                from .sources import SourceTools
            except ImportError:
                from sources import SourceTools
            commands['source_card']=SourceTools(engine).source_card
        if request['command'] in ['person_mentions','person_candidates','person_link']:
            try:
                from .people import PeopleTools
            except ImportError:
                from people import PeopleTools
            people=PeopleTools(engine)
            commands.update({name:getattr(people,name) for name in ['person_mentions','person_candidates','person_link']})
        if request['command'] in ['backup_create','backup_list','backup_restore']:
            try:
                from .backups import BackupTools
            except ImportError:
                from backups import BackupTools
            backups=BackupTools(engine)
            commands.update({name:getattr(backups,name) for name in ['backup_create','backup_list','backup_restore']})
        groups=[
            ('global_languages','GlobalLanguagesTools',['historical_languages']),
            ('historical_reading','HistoricalTools',['historical_get','historical_profile','historical_package_get','historical_package_save','historical_word','historical_term','historical_analyze','historical_decide','historical_layout','historical_exemplar','historical_structure_propose']),
            ('interchange','InterchangeTools',['interchange_preview','interchange_apply','interchange_export']),
            ('research_hub','HubTools',['hub_photo','hub_queue','hub_review','hub_family_search','hub_gaps','hub_profile']),
            ('paging','PagingTools',['pages_window','book_page_ids']),
            ('research_bundle','ResearchBundleTools',['bundle_preview','bundle_create','bundle_inspect','bundle_restore']),
            ('review_corpus','CorpusTools',['corpus_import','corpus_list','corpus_save','corpus_history','corpus_freeze','corpus_compare','corpus_score_fields']),
            ('fact_review','FactReviewTools',['fact_reviews','fact_save','fact_history','fact_supports','neighbor_candidates']),
            ('board_navigation','BoardNavigation',['board_evidence']),
            ('board_import', 'BoardTools', ['board_preview', 'board_import', 'board_list', 'board_get', 'board_set_semantics']),
            ('agents', 'AgentTools', ['agent_jobs', 'agent_create', 'agent_step', 'agent_cancel', 'agent_review', 'agent_history']),
            ('tutor', 'TutorTools', ['tutor_lessons', 'tutor_save', 'tutor_history', 'tutor_compare', 'tutor_role', 'tutor_train']),
            ('recognizers', 'RecognizerTools', ['model_inspect']),
            ('candidate_models','CandidateTools',['candidate_list','candidate_train_check']),
            ('books','BookTools',['books','book_get','book_save','book_import_folder','book_index','book_pdf','record_search','research_task','book_template']),
            ('research','ResearchTools',['card_change','card_undo','card_operations','fact_crop','chronology_hints','book_dictionary']),
            ('gedcom','GedcomTools',['gedcom_preview','gedcom_import','gedcom_export']),
            ('duplicates','DuplicateTools',['duplicate_index','duplicate_find','duplicate_decide']),
            ('genealogy','GenealogyTools',['genealogy_mentions','person_list','person_save','person_attach','person_detach','person_card','family_list','family_save','family_tree','genealogy_export','genealogy_canvas']),
            ('extraction','ExtractionTools',['field_propose','field_apply']),
            ('operations','Operations',['evaluation_coverage','runtime_check','batch_books','batch_create','batch_status','batch_recover','batch_step']),
        ]
        # Load optional tools only when requested; browsing should not load OCR models.
        for module_name,class_name,names in groups:
            if request['command'] in names:
                import importlib
                module=importlib.import_module('.'+module_name,__package__) if __package__ else importlib.import_module(module_name)
                component=getattr(module,class_name)(engine)
                commands.update({name:getattr(component,name) for name in names})
        result=commands[request['command']](request)
        return result
    finally:
        engine.db.close()


def main():
    try:
        result=handle_request(json.load(sys.stdin))
        print(json.dumps({'ok':True,'result':result},ensure_ascii=False))
    except Exception as e:
        print(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False))
        sys.exit(1)


if __name__=='__main__':
    sys.stdin.reconfigure(encoding='utf-8'); sys.stdout.reconfigure(encoding='utf-8')
    main()
