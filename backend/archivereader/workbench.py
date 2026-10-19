"""Document workbench: evidence regions, book profiles, derivatives and paired HTR."""
from pathlib import Path
import hashlib
import json
import math
import re
import time
import unicodedata
import uuid
import contextlib
import sys

try:
    from .engine import uncertain_text
    from .htr_compare import compare
except ImportError:
    from engine import uncertain_text
    from htr_compare import compare


def validate_rect(rect):
    if not isinstance(rect, list) or len(rect) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in rect):
        raise ValueError('Неправильні межі ділянки.')
    x, y, w, h = rect
    if not (0 <= x < 1 and 0 <= y < 1 and .002 <= w <= 1 and .002 <= h <= 1 and x+w <= 1.000001 and y+h <= 1.000001):
        raise ValueError('Неправильні межі ділянки.')
    return rect


def name_key(text):
    text=unicodedata.normalize('NFKD',text).casefold().translate(str.maketrans({'ł':'l','ø':'o','đ':'d','æ':'ae','œ':'oe'}))
    return ''.join(c for c in text if not unicodedata.combining(c) and c.isalnum())


class Workbench:
    def __init__(self, engine):
        self.engine = engine
        self.db = engine.db
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS book_profiles(doc TEXT PRIMARY KEY REFERENCES documents(id), data TEXT);
        CREATE TABLE IF NOT EXISTS annotations(id TEXT PRIMARY KEY, page TEXT REFERENCES pages(id), data TEXT);
        CREATE TABLE IF NOT EXISTS annotation_history(id INTEGER PRIMARY KEY, annotation TEXT, before TEXT, after TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS derivatives(doc TEXT PRIMARY KEY REFERENCES documents(id), parent_page TEXT REFERENCES pages(id), settings TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS comparison_runs(id TEXT PRIMARY KEY, doc TEXT, path TEXT, manifest_sha TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')
        try:
            from .schema_indexes import ensure_indexes
        except ImportError:from schema_indexes import ensure_indexes
        ensure_indexes(self.db)

    def book_profile(self, a):
        page = self.engine.page(a['id'])
        group=self.photo_book(page['doc'])
        if 'values' in a:
            values = {key: a['values'].get(key, '') for key in ['languages', 'years', 'script', 'layout', 'model', 'notes', 'split','calendar']}
            if values['calendar'] not in ['', 'gregorian','julian']:raise ValueError('Неправильний календар книги.')
            if values['split'] not in ['', 'train', 'validation', 'test']:
                raise ValueError('Неправильна роль книги в наборі.')
            if values['split']:
                family=self.document_family(page['doc'])
                for row in self.db.execute('SELECT doc,data FROM book_profiles'):
                    role=json.loads(row['data']).get('split','')
                    if row['doc']!=page['doc'] and row['doc'] not in (self.photo_book_docs(page['doc']) if group else {page['doc']}) and row['doc'] in family and role and role!=values['split']:
                        raise ValueError('Оригінал і його похідні копії мають належати до однієї частини набору.')
            with self.db:
                self.db.execute('INSERT OR REPLACE INTO book_profiles VALUES (?,?)', (page['doc'], json.dumps(values, ensure_ascii=False)))
                if group:
                    data=json.loads(group['data']);data['profile']=values
                    self.db.execute('UPDATE photo_books SET data=? WHERE id=?',(json.dumps(data,ensure_ascii=False),group['id']))
                    for member in self.photo_book_docs(page['doc']):
                        self.db.execute('INSERT OR REPLACE INTO book_profiles VALUES (?,?)',(member,json.dumps(values,ensure_ascii=False)))
        if group:
            row=self.db.execute('SELECT data FROM photo_books WHERE id=?',(group['id'],)).fetchone()
            data=json.loads(row['data'])
            if 'profile' in data:return data['profile']
        row = self.db.execute('SELECT data FROM book_profiles WHERE doc=?', (page['doc'],)).fetchone()
        return json.loads(row['data']) if row else {}

    def photo_book(self,doc):
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='photo_books'").fetchone():return None
        return self.db.execute('SELECT DISTINCT b.* FROM photo_books b JOIN book_items i ON i.book=b.id JOIN pages p ON p.id=i.page WHERE p.doc=?',(doc,)).fetchone()

    def photo_book_docs(self,doc):
        group=self.photo_book(doc)
        if not group:return {doc}
        return {r['doc'] for r in self.db.execute('SELECT DISTINCT p.doc FROM book_items i JOIN pages p ON p.id=i.page WHERE i.book=?',(group['id'],))}

    def document_family(self, doc):
        edges=[(r['doc'],r['parent_doc']) for r in self.db.execute('SELECT d.doc,p.doc AS parent_doc FROM derivatives d JOIN pages p ON p.id=d.parent_page')]
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='photo_books'").fetchone():
            groups={}
            for row in self.db.execute('SELECT i.book,p.doc FROM book_items i JOIN pages p ON p.id=i.page'):groups.setdefault(row['book'],set()).add(row['doc'])
            for docs in groups.values():
                root=next(iter(docs))
                edges.extend((root,item) for item in docs)
        family={doc}
        while True:
            extended=family|{a for a,b in edges if b in family}|{b for a,b in edges if a in family}
            if extended==family: return family
            family=extended

    def annotations(self, a):
        self.engine.page(a['id'])
        return [json.loads(r['data']) | {'id': r['id']} for r in self.db.execute('SELECT id,data FROM annotations WHERE page=? ORDER BY rowid', (a['id'],))]

    def save_annotation(self, a):
        self.engine.page(a['page'])
        ident = a.get('annotation') or uuid.uuid4().hex
        old = self.db.execute('SELECT page,data FROM annotations WHERE id=?', (ident,)).fetchone()
        if old and old['page'] != a['page']:
            raise ValueError('Ділянка належить іншій сторінці.')
        data = dict(a['data'])
        data.pop('id', None)
        data['_page'] = a['page']
        validate_rect(data['rect'])
        if 'reading_order' in data and (type(data['reading_order']) is not int or not 1<=data['reading_order']<=100000):
            raise ValueError('Неправильний порядок читання.')
        if data.get('kind') not in ['line', 'entry', 'column', 'damage', 'missing']:
            raise ValueError('Неправильний тип ділянки.')
        data['verified'] = bool(data.get('verified')) and not uncertain_text(data.get('text', '')) and data['kind'] == 'line'
        record = data.get('record')
        if record and not self.db.execute('SELECT 1 FROM records WHERE id=? AND page=?', (record, a['page'])).fetchone():
            raise ValueError("Пов'язаний запис належить іншій сторінці.")
        parent = data.get('parent')
        if parent:
            row = self.db.execute('SELECT page,data FROM annotations WHERE id=?', (parent,)).fetchone()
            if not row or row['page'] != a['page'] or parent == ident:
                raise ValueError('Неправильна батьківська ділянка.')
            ancestor = parent
            visited = {ident}
            while ancestor:
                if ancestor in visited:
                    raise ValueError('Неправильна батьківська ділянка.')
                visited.add(ancestor)
                ancestor_row = self.db.execute('SELECT data FROM annotations WHERE id=?', (ancestor,)).fetchone()
                ancestor = json.loads(ancestor_row['data']).get('parent') if ancestor_row else None
            outer = json.loads(row['data'])['rect']
            inner = data['rect']
            if not (inner[0] >= outer[0] and inner[1] >= outer[1] and inner[0]+inner[2] <= outer[0]+outer[2]+.000001 and inner[1]+inner[3] <= outer[1]+outer[3]+.000001):
                raise ValueError('Дочірня ділянка має бути всередині батьківської.')
        for child in self.annotations({'id': a['page']}):
            if child.get('parent') == ident:
                outer, inner = data['rect'], child['rect']
                if not (inner[0] >= outer[0] and inner[1] >= outer[1] and inner[0]+inner[2] <= outer[0]+outer[2]+.000001 and inner[1]+inner[3] <= outer[1]+outer[3]+.000001):
                    raise ValueError('Дочірня ділянка має бути всередині батьківської.')
        encoded = json.dumps(data, ensure_ascii=False)
        with self.db:
            self.db.execute('INSERT INTO annotation_history(annotation,before,after) VALUES (?,?,?)', (ident, old['data'] if old else None, encoded))
            self.db.execute('INSERT INTO annotations VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data', (ident, a['page'], encoded))
        return {'id': ident}

    def delete_annotation(self, a):
        row = self.db.execute('SELECT data FROM annotations WHERE id=? AND page=?', (a['annotation'], a['page'])).fetchone()
        if not row:
            raise ValueError('Ділянку не знайдено.')
        for child in self.annotations({'id': a['page']}):
            if child.get('parent') == a['annotation']:
                raise ValueError('Спочатку видаліть дочірні ділянки.')
        with self.db:
            self.db.execute('INSERT INTO annotation_history(annotation,before,after) VALUES (?,?,NULL)', (a['annotation'], row['data']))
            self.db.execute('DELETE FROM annotations WHERE id=?', (a['annotation'],))
        return {'deleted': True}

    def whole_image(self, ident):
        # Annotations always reference the entire original, independently of OCR ROI.
        from PIL import Image
        rendering = self.engine.render({'id': ident, 'whole': True, 'full': True})
        with Image.open(rendering['path']) as source:
            return source.convert('RGB')

    def region_crop(self, a):
        from PIL import Image
        annotation = next((r for r in self.annotations({'id': a['id']}) if r['id'] == a['annotation']), None)
        if annotation is None:
            raise ValueError('Ділянку не знайдено.')
        image = self.whole_image(a['id'])
        x,y,w,h = annotation['rect']
        image = image.crop((round(x*image.width), round(y*image.height), round((x+w)*image.width), round((y+h)*image.height)))
        path = self.engine.root/'cache'/('region-'+uuid.uuid4().hex+'.png')
        image.save(path)
        return {'path': str(path), 'width': image.width, 'height': image.height}

    def compare_regions(self, a):
        page = self.engine.page(a['id'])
        rows = self.annotations({'id': a['id']})
        selected = [r for r in rows if r['kind'] == 'line' and (not a.get('annotation') or r['id'] == a['annotation'])]
        if not selected:
            raise ValueError('Спочатку створіть ділянку рядка.')
        return self.run_comparison([(page, r) for r in selected], a['models'])

    def run_comparison(self, selected, models):
        run_id = uuid.uuid4().hex
        folder = self.engine.root/'results'/('comparison-'+run_id)
        folder.mkdir(parents=True)
        cases = []
        for page, region in selected:
            cropped = self.region_crop({'id': page['id'], 'annotation': region['id']})
            source = Path(cropped['path'])
            image_name = region['id']+'.png'
            (folder/image_name).write_bytes(source.read_bytes())
            case = {'id': region['id'], 'image': image_name, 'image_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                    'source': page['doc']+':'+str(page['num']), 'document': page['doc'], 'page': page['num']+1,
                    'extraction': 'manually bounded rectangular line, not baseline-rectified', 'rect': region['rect']}
            damaged=any(r['kind'] in ['damage','missing'] and overlaps(region['rect'],r['rect']) for r in self.annotations({'id':page['id']}))
            if region.get('verified') and region.get('text', '').strip() and not damaged:
                case['reference'] = region['text']
            cases.append(case)
        manifest = folder/'manifest.json'
        manifest.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding='utf-8')
        with contextlib.redirect_stdout(sys.stderr):
            report = compare(manifest, models, folder)
        with self.db:
            self.db.execute('INSERT INTO comparison_runs(id,doc,path,manifest_sha) VALUES (?,?,?,?)',
                            (run_id, selected[0][0]['doc'], str(folder), hashlib.sha256(manifest.read_bytes()).hexdigest()))
        return {'rows': report['rows'], 'models': report['models'], 'paired': report.get('paired_comparison_first_two'), 'path': str(folder/'comparison.html')}

    def heldout_compare(self, a):
        selected = []
        for row in self.db.execute("SELECT doc,data FROM book_profiles"):
            if json.loads(row['data']).get('split') != 'test':
                continue
            for page in self.engine.list_pages({}):
                if page['doc'] != row['doc']:
                    continue
                for region in self.annotations({'id': page['id']}):
                    others=self.annotations({'id': page['id']})
                    if region['kind'] == 'line' and region.get('verified') and region.get('text', '').strip() and not any(r['kind'] in ['damage','missing'] and overlaps(region['rect'],r['rect']) for r in others):
                        selected.append((page, region))
        if not selected:
            raise ValueError('Позначте окремі книги як тестові та перевірте текст їхніх рядків.')
        self.check_known_training_overlap(selected,a['models'])
        return self.run_comparison(selected, a['models'])

    def check_known_training_overlap(self, selected, models):
        test_docs=set().union(*(self.document_family(page['doc']) for page,_ in selected))
        test_hashes={page['source_sha256'] for page,_ in selected if page.get('source_sha256')}
        hashes={hashlib.sha256(Path(model['path']).read_bytes()).hexdigest() for model in models if Path(model['path']).is_file()}
        for path in (self.engine.root/'models').glob('training-*/run.json'):
            run=json.loads(path.read_text(encoding='utf-8'))
            if not hashes.intersection(output['sha256'] for output in run.get('output_models',[])):
                continue
            manifest=path.parent/'dataset'/'manifest.json'
            if manifest.exists() and any(row['split'] in ['train','validation'] and (row['document'] in test_docs or row.get('source_sha256') in test_hashes) for row in json.loads(manifest.read_text(encoding='utf-8'))):
                raise ValueError('Вибрана модель вже навчалася або перевірялася на цій тестовій книзі. Виберіть окремі книги.')

    def similar_names(self, a):
        from difflib import SequenceMatcher
        query = name_key(a.get('query', ''))
        if len(query) < 2:
            return []
        results = []
        for row in self.db.execute('SELECT r.id,r.data,r.page,p.num,d.name FROM records r JOIN pages p ON p.id=r.page JOIN documents d ON d.id=p.doc'):
            record = json.loads(row['data'])
            for field in ['person', 'related1', 'related2']:
                value = record.get(field, '')
                if not value:
                    continue
                candidates = [name_key(value)] + [name_key(word) for word in value.split()]
                score = max(SequenceMatcher(None, query, candidate).ratio() for candidate in candidates)
                if score >= .6:
                    results.append({'record': row['id'], 'page': row['page'], 'document': row['name'], 'number': row['num']+1,
                                    'field': field, 'name': value, 'similarity': round(score, 3), 'verified': record.get('verified', False)})
        return sorted(results, key=lambda r: (-r['similarity'], r['document'], r['number']))[:100]

    def dataset_explicit(self, a):
        destination = Path(a['path']).resolve()
        if destination.exists() and any(destination.iterdir()):
            raise ValueError('Виберіть порожню папку для набору.')
        destination.mkdir(parents=True, exist_ok=True)
        lists = {split: [] for split in ['train', 'validation', 'test']}
        manifest = []
        excluded = 0
        for page in self.engine.list_pages({}):
            role = self.book_profile({'id': page['id']}).get('split', '')
            if role not in lists:
                continue
            regions = self.annotations({'id': page['id']})
            for region in regions:
                if region['kind'] != 'line':
                    continue
                if not region.get('verified') or not region.get('text', '').strip() or uncertain_text(region['text']):
                    excluded += 1; continue
                # A damaged/missing overlay makes the line unsuitable as ground truth.
                rect = region['rect']
                if any(r['kind'] in ['damage','missing'] and overlaps(rect, r['rect']) for r in regions):
                    excluded += 1; continue
                cropped = self.region_crop({'id': page['id'], 'annotation': region['id']})
                image = destination/(region['id']+'.png')
                image.write_bytes(Path(cropped['path']).read_bytes())
                image.with_suffix('.gt.txt').write_text(region['text'], encoding='utf-8')
                lists[role].append(str(image))
                manifest.append({'image': image.name, 'image_sha256': hashlib.sha256(image.read_bytes()).hexdigest(),
                                 'text': region['text'], 'document': page['doc'], 'source_sha256': page['sha'] if 'sha' in page else self.db.execute('SELECT sha FROM documents WHERE id=?', (page['doc'],)).fetchone()['sha'],
                                 'page': page['num']+1, 'split': role, 'rect': rect})
                group=self.photo_book(page['doc'])
                manifest[-1]['book']=group['id'] if group else page['doc']
                manifest[-1]['book_name']=group['name'] if group else page['name']
        for split, images in lists.items():
            (destination/(split+'.txt')).write_text('\n'.join(images), encoding='utf-8')
        (destination/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        return {split: len(images) for split,images in lists.items()} | {'excluded': excluded, 'path': str(destination)}

    def prepare_photo(self, a):
        from PIL import Image, ImageOps
        page = self.engine.page(a['id'])
        image = self.whole_image(a['id'])
        original_size = image.size
        mode = a.get('mode', 'rotate')
        if mode == 'rotate':
            angle = float(a.get('angle', 0))
            if not math.isfinite(angle) or not -180 <= angle <= 180:
                raise ValueError('Неправильний кут повороту.')
            images = [image.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor='white')]
        elif mode == 'split':
            position = float(a.get('position', .5))
            if not .1 <= position <= .9:
                raise ValueError('Неправильне положення поділу.')
            x = round(image.width*position)
            images = [image.crop((0,0,x,image.height)), image.crop((x,0,image.width,image.height))]
        elif mode == 'perspective':
            points = validate_points(a['points'], 4)
            pixel_points = [(x*image.width,y*image.height) for x,y in points]
            cross = [cross_product(pixel_points[i], pixel_points[(i+1)%4], pixel_points[(i+2)%4]) for i in range(4)]
            if not (all(v>0 for v in cross) or all(v<0 for v in cross)):
                raise ValueError('Позначте кути опуклої сторінки в указаному порядку.')
            tl,tr,br,bl = pixel_points
            width = max(1, round((math.dist(tl,tr)+math.dist(bl,br))/2))
            height = max(1, round((math.dist(tl,bl)+math.dist(tr,br))/2))
            coefficients = perspective_coefficients([(0,0),(width,0),(width,height),(0,height)], pixel_points)
            images = [image.transform((width,height), Image.Transform.PERSPECTIVE, coefficients, Image.Resampling.BICUBIC, fillcolor='white')]
        elif mode == 'dewarp':
            points = validate_points(a['points'], 6)
            top, bottom = points[:3], points[3:]
            if not (top[0][0] < top[1][0] < top[2][0] and bottom[0][0] < bottom[1][0] < bottom[2][0]) or any(abs(top[i][0]-bottom[i][0])>.08 or bottom[i][1]-top[i][1]<.02 for i in range(3)):
                raise ValueError('Виберіть відповідні ліві, середні й праві точки верхньої та нижньої напрямних.')
            left,right = top[0][0]*image.width,top[2][0]*image.width
            width = round(right-left)
            height = round(sum((bottom[i][1]-top[i][1])*image.height for i in range(3))/3)
            mesh = []
            for i in range(64):
                x0,x1 = round(i*width/64),round((i+1)*width/64)
                if x1 <= x0: continue
                sx0,sx1 = left+x0,left+x1
                t0,t1 = interpolate(top,sx0/image.width)*image.height,interpolate(top,sx1/image.width)*image.height
                b0,b1 = interpolate(bottom,sx0/image.width)*image.height,interpolate(bottom,sx1/image.width)*image.height
                if b0 <= t0 or b1 <= t1: raise ValueError('Напрямні перетинаються. Позначте їх знову.')
                mesh.append(((x0,0,x1,height),(sx0,t0,sx0,b0,sx1,b1,sx1,t1)))
            images = [image.transform((width,height), Image.Transform.MESH, mesh, Image.Resampling.BICUBIC, fillcolor='white')]
        else:
            raise ValueError('Невідома операція підготовки фото.')
        folder = self.engine.root/'results'/('photo-'+uuid.uuid4().hex)
        folder.mkdir(parents=True)
        paths = []
        for i, result in enumerate(images):
            path = folder/(f'{Path(page["name"]).stem}-p{page["num"]+1}-{mode}-{i+1}.png')
            result.save(path); paths.append(str(path))
        settings = {key: a.get(key) for key in ['mode','angle','position','points']}
        (folder/'provenance.json').write_text(json.dumps({'parent_page': page['id'], 'original_size': original_size, 'operation': settings, 'outputs': paths}, ensure_ascii=False, indent=2), encoding='utf-8')
        return {'paths': paths, 'provenance': str(folder/'provenance.json'), 'parent_page': page['id'], 'settings': settings}

    def import_derivative(self, a):
        parent=self.engine.page(a['parent_page'])
        imported = []
        for path in a['paths']:
            result = self.engine.import_file({'path': path})
            if result['id'] != parent['doc']:
                with self.db:
                    self.db.execute('INSERT OR IGNORE INTO derivatives(doc,parent_page,settings) VALUES (?,?,?)', (result['id'], a['parent_page'], json.dumps(a['settings'])))
            imported.append(result)
        return imported


def overlaps(a, b):
    return max(a[0],b[0]) < min(a[0]+a[2],b[0]+b[2]) and max(a[1],b[1]) < min(a[1]+a[3],b[1]+b[3])


def validate_points(points, number):
    if len(points) != number or any(len(p)!=2 or any(not isinstance(v,(int,float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in p) for p in points):
        raise ValueError('Неправильні точки напрямних.')
    return points


def cross_product(a,b,c):
    return (b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0])


def interpolate(points, x):
    return sum(y*math.prod((x-xj)/(xi-xj) for j,(xj,_) in enumerate(points) if j!=i) for i,(xi,y) in enumerate(points))


def perspective_coefficients(target, source):
    matrix=[]
    for (x,y),(u,v) in zip(target,source):
        matrix += [[x,y,1,0,0,0,-u*x,-u*y,u], [0,0,0,x,y,1,-v*x,-v*y,v]]
    for col in range(8):
        pivot=max(range(col,8),key=lambda row:abs(matrix[row][col]))
        matrix[col],matrix[pivot]=matrix[pivot],matrix[col]
        scale=matrix[col][col]
        if abs(scale)<1e-10: raise ValueError('За цими точками перспективу визначити неможливо.')
        matrix[col]=[v/scale for v in matrix[col]]
        for row in range(8):
            if row!=col:
                scale=matrix[row][col]; matrix[row]=[v-scale*p for v,p in zip(matrix[row],matrix[col])]
    return tuple(row[-1] for row in matrix)
