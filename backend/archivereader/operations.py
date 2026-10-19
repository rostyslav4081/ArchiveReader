"""Persistent book queues, local runtime checks and evaluation coverage."""
import importlib.metadata
import json
from pathlib import Path
import sys
import uuid
try:
    from .library import LibraryTools
    from .model_identity import fingerprint_models,validate_models
    from .schema_indexes import ensure_indexes
except ImportError:
    from library import LibraryTools
    from model_identity import fingerprint_models,validate_models
    from schema_indexes import ensure_indexes


class Operations(LibraryTools):
    def __init__(self,engine):
        super().__init__(engine)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS book_jobs(id TEXT PRIMARY KEY,data TEXT NOT NULL,created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS book_tasks(job TEXT REFERENCES book_jobs(id),page TEXT REFERENCES pages(id),state TEXT,error TEXT DEFAULT '',PRIMARY KEY(job,page));
        ''')
        ensure_indexes(self.db)

    def evaluation_coverage(self,a):
        inventory=self.benchmark_inventory({});result=[]
        for book in inventory:
            pages=list(self.db.execute('SELECT id,status FROM pages WHERE doc=? ORDER BY num',(book['doc'],)))
            corrections=self.db.execute('SELECT COUNT(*) FROM line_corrections l JOIN pages p ON p.id=l.page WHERE p.doc=? AND l.verified=1',(book['doc'],)).fetchone()[0]
            damaged=self.db.execute("SELECT COUNT(*) FROM annotations a JOIN pages p ON p.id=a.page WHERE p.doc=? AND json_extract(a.data,'$.kind') IN ('damage','missing')",(book['doc'],)).fetchone()[0]
            result.append(book|{'pages':len(pages),'processed':sum(p['status']=='done' for p in pages),'ocr_verified':corrections,'damage_regions':damaged,
                                'first_page':pages[0]['id'] if pages else None,'ready':book['split']=='test' and book['verified_lines']>0,
                                'missing_profile':[key for key in ['languages','years','script','split'] if not book[key]]})
        return result

    def runtime_check(self,a):
        packages={}
        for name in ['Pillow','PyMuPDF','kraken','torch','transformers']:
            try:packages[name]=importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:packages[name]=None
        model=a.get('model','');path=Path(model) if model else None
        exists=bool(path and (path.is_file() or path.is_dir()))
        size=sum(p.stat().st_size for p in path.rglob('*') if p.is_file()) if path and path.is_dir() else path.stat().st_size if path and path.is_file() else 0
        return {'python':sys.version.split()[0],'executable':sys.executable,'packages':packages,'model_exists':exists,
                'model_bytes':size,'model_kind':'folder' if path and path.is_dir() else 'file' if exists else None,'profile':self.engine.profile({})}

    def batch_books(self,a):
        return [dict(r) for r in self.db.execute('SELECT d.id,d.name,COUNT(p.id) AS pages,SUM(p.status="done") AS done FROM documents d JOIN pages p ON p.doc=d.id GROUP BY d.id ORDER BY d.rowid')]

    def batch_create(self,a):
        docs=set(a.get('documents',[]))
        known={r['id'] for r in self.db.execute('SELECT id FROM documents')}
        if not docs or not docs<=known:raise ValueError('Виберіть книги для черги.')
        options=dict(a.get('options',{}));options.pop('id',None);options.pop('root',None);options.pop('command',None)
        ident=uuid.uuid4().hex
        identity=fingerprint_models(options)
        with self.db:
            self.db.execute('INSERT INTO book_jobs(id,data) VALUES (?,?)',(ident,json.dumps({'options':options,'model_identity':identity},ensure_ascii=False)))
            for page in self.db.execute('SELECT id,doc,status FROM pages ORDER BY rowid'):
                if page['doc'] not in docs or page['status']=='done':continue
                corrected=self.db.execute('SELECT 1 FROM line_corrections WHERE page=? LIMIT 1',(page['id'],)).fetchone()
                self.db.execute('INSERT INTO book_tasks(job,page,state,error) VALUES (?,?,?,?)',(ident,page['id'],'skipped' if corrected else 'queued','Сторінка має виправлені рядки.' if corrected else ''))
        return self.batch_status({'job':ident})

    def batch_status(self,a):
        if not a.get('job'):
            return [{'id':r['id'],'created':r['created']} for r in self.db.execute('SELECT id,created FROM book_jobs ORDER BY rowid DESC LIMIT 30')]
        job=self.db.execute('SELECT * FROM book_jobs WHERE id=?',(a['job'],)).fetchone()
        if not job:raise ValueError('Чергу не знайдено.')
        counts={state:0 for state in ['queued','running','done','failed','skipped']}
        for row in self.db.execute('SELECT state,COUNT(*) AS n FROM book_tasks WHERE job=? GROUP BY state',(a['job'],)):counts[row['state']]=row['n']
        errors=[dict(r) for r in self.db.execute('SELECT t.page,t.error,t.state,p.num,d.name FROM book_tasks t JOIN pages p ON p.id=t.page JOIN documents d ON d.id=p.doc WHERE t.job=? AND t.state IN ("failed","skipped") LIMIT 50',(a['job'],))]
        return {'id':job['id'],'counts':counts,'errors':errors,'options':json.loads(job['data'])['options']}

    def batch_recover(self,a):
        self.batch_status(a)
        config=json.loads(self.db.execute('SELECT data FROM book_jobs WHERE id=?',(a['job'],)).fetchone()['data'])
        validate_models(config['options'],config.get('model_identity'))
        with self.db:
            self.db.execute('UPDATE pages SET status="pending" WHERE id IN (SELECT page FROM book_tasks WHERE job=? AND state="running")',(a['job'],))
            self.db.execute('UPDATE book_tasks SET state="queued",error="" WHERE job=? AND state="running"',(a['job'],))
            if a.get('retry_errors'):self.db.execute('UPDATE book_tasks SET state="queued",error="" WHERE job=? AND state="failed"',(a['job'],))
        return self.batch_status(a)

    def batch_step(self,a):
        job=self.db.execute('SELECT data FROM book_jobs WHERE id=?',(a['job'],)).fetchone()
        if not job:raise ValueError('Чергу не знайдено.')
        config=json.loads(job['data']);options=config['options']
        validate_models(options,config.get('model_identity'))
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            task=self.db.execute('SELECT page FROM book_tasks WHERE job=? AND state="queued" ORDER BY rowid LIMIT 1',(a['job'],)).fetchone()
            if task:self.db.execute('UPDATE book_tasks SET state="running" WHERE job=? AND page=?',(a['job'],task['page']))
        if not task:return self.batch_status(a)
        duplicate=None
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='duplicate_decisions'").fetchone():
            for row in self.db.execute('SELECT data FROM duplicate_decisions'):
                decision=json.loads(row['data'])
                if decision['right']==task['page'] and decision['status']=='confirmed_full' and self.engine.page(decision['left'])['status']=='done':duplicate=decision;break
        if duplicate:
            with self.db:self.db.execute('UPDATE book_tasks SET state="skipped",error=? WHERE job=? AND page=?',('Підтверджений дублікат: '+duplicate['left'],a['job'],task['page']))
            return self.batch_status(a)
        try:
            self.engine.recognize(options|{'id':task['page']});state,error='done',''
        except Exception as ex:state,error='failed',str(ex)
        with self.db:self.db.execute('UPDATE book_tasks SET state=?,error=? WHERE job=? AND page=?',(state,error,a['job'],task['page']))
        return self.batch_status(a)
