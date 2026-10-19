"""Human-confirmed teaching examples; agreement is never reference transcription.

Examples are normal verified line annotations, so established damage exclusions,
book-family splits, export and training provenance remain authoritative.
"""
import json
import uuid

try:
    from .library import LibraryTools
    from .workbench import validate_rect, overlaps
    from .engine import uncertain_text
except ImportError:
    from library import LibraryTools
    from workbench import validate_rect, overlaps
    from engine import uncertain_text


class TutorTools(LibraryTools):
    def __init__(self, engine):
        super().__init__(engine)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS tutor_lessons(id TEXT PRIMARY KEY,
          page TEXT NOT NULL REFERENCES pages(id), annotation TEXT NOT NULL,
          data TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS tutor_history(id INTEGER PRIMARY KEY,
          lesson TEXT NOT NULL, action TEXT NOT NULL, data TEXT NOT NULL,
          created TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')

    def tutor_lessons(self, a):
        page = self.engine.page(a['id'])
        docs = self.photo_book_docs(page['doc'])
        rows = []
        for row in self.db.execute('SELECT l.*,p.doc,p.num,d.name FROM tutor_lessons l JOIN pages p ON p.id=l.page JOIN documents d ON d.id=p.doc ORDER BY l.rowid DESC'):
            if row['doc'] not in docs:
                continue
            data = json.loads(row['data'])
            current = self.db.execute('SELECT data FROM annotations WHERE id=?', (row['annotation'],)).fetchone()
            actual = json.loads(current['data']) if current else None
            rows.append(data | {'id': row['id'], 'page': row['page'], 'annotation': row['annotation'],
                               'number': row['num']+1, 'name': row['name'],
                               'stale': actual is None or any(actual.get(k) != data.get(k) for k in ['rect','text','verified'])})
        return rows

    def tutor_save(self, a):
        page = self.engine.page(a['id'])
        rect = validate_rect(a['rect'])
        text = str(a.get('text', '')).strip()
        if not text:
            raise ValueError('Введіть власне прочитання рядка.')
        verified = a.get('verified') is True
        if verified and uncertain_text(text):
            raise ValueError('Непевний текст збережіть без підтвердження.')
        if verified and any(r['kind'] in ['damage','missing'] and overlaps(rect,r['rect']) for r in self.annotations({'id':a['id']})):
            raise ValueError('Пошкоджений рядок збережіть без підтвердження.')
        ident = a.get('lesson') or uuid.uuid4().hex
        previous = self.db.execute('SELECT * FROM tutor_lessons WHERE id=?',(ident,)).fetchone()
        if previous and previous['page'] != a['id']:
            raise ValueError('Приклад належить іншій сторінці.')
        annotation = previous['annotation'] if previous else uuid.uuid4().hex
        old = json.loads(previous['data']) if previous else None
        if old and a.get('revision') != old.get('revision'):
            raise ValueError('Приклад змінився. Відкрийте його знову.')
        if old:
            actual = self.db.execute('SELECT data FROM annotations WHERE id=?',(annotation,)).fetchone()
            actual = json.loads(actual['data']) if actual else {}
            if any(actual.get(k) != old.get(k) for k in ['rect','text','verified']):
                raise ValueError('Ділянку змінено в іншому вікні. Створіть новий приклад.')
        data = {'rect':rect,'text':text,'verified':verified,'kind':'line','notes':str(a.get('notes','')),
                'source_sha256':self.db.execute('SELECT sha FROM documents WHERE id=?',(page['doc'],)).fetchone()['sha'],
                'revision':uuid.uuid4().hex}
        self.save_annotation({'page':a['id'],'annotation':annotation,'data':{k:data[k] for k in ['rect','text','verified','kind','notes']}})
        # Persist human input, never a model's result or ensemble consensus.
        with self.db:
            self.db.execute('INSERT INTO tutor_lessons(id,page,annotation,data) VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                            (ident,a['id'],annotation,json.dumps(data,ensure_ascii=False)))
            self.db.execute('INSERT INTO tutor_history(lesson,action,data) VALUES (?,?,?)',
                            (ident,'human_confirmed' if verified else 'draft',json.dumps({'before':old,'after':data},ensure_ascii=False)))
        return data | {'id':ident,'annotation':annotation,'weights_changed':False}

    def tutor_history(self,a):
        row = self.db.execute('SELECT page FROM tutor_lessons WHERE id=?',(a['lesson'],)).fetchone()
        if not row:
            raise ValueError('Приклад не знайдено.')
        return [dict(r)|{'data':json.loads(r['data'])} for r in self.db.execute('SELECT * FROM tutor_history WHERE lesson=? ORDER BY id DESC',(a['lesson'],))]

    def tutor_compare(self,a):
        # In-memory region survives neither cancellation nor failure. It cannot
        # leak into annotations/datasets if the worker process is terminated.
        page=self.engine.page(a['id'])
        rect = validate_rect(a['rect'])
        annotation = uuid.uuid4().hex
        data = {'id':annotation,'kind':'line','rect':rect,'verified':False,'text':''}
        self._tutor_region=(a['id'],data)
        try:
            return self.run_comparison([(page,data)],a['models'])
        finally:
            self._tutor_region=None

    def region_crop(self,a):
        transient=getattr(self,'_tutor_region',None)
        if not transient or transient[0]!=a['id'] or transient[1]['id']!=a['annotation']:
            return super().region_crop(a)
        image=self.whole_image(a['id'])
        x,y,w,h=transient[1]['rect']
        image=image.crop((round(x*image.width),round(y*image.height),round((x+w)*image.width),round((y+h)*image.height)))
        path=self.engine.root/'cache'/('tutor-'+uuid.uuid4().hex+'.png');image.save(path)
        return {'path':str(path),'width':image.width,'height':image.height}

    def tutor_role(self,a):
        values = self.book_profile({'id':a['id']})
        if 'role' in a:
            if a['role'] not in ['', 'train','validation','test']:
                raise ValueError('Неправильна роль книги в наборі.')
            values['split']=a['role']
            values=self.book_profile({'id':a['id'],'values':values})
        return values

    def tutor_train(self,a):
        if a.get('confirmed') is not True:
            raise ValueError('Підтвердьте навчання окремої копії Kraken.')
        # Engine creates a fresh directory, records the base hash, never promotes.
        return self.engine.train_model({'model':a['model'],'epochs':int(a.get('epochs',1)), 'explicit':True})
