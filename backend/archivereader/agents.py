"""Persistent local specialists. Consensus is never ground truth or automatic training."""
import hashlib
import json
from pathlib import Path
import uuid
try:
    from .library import LibraryTools, digest
    from .htr_compare import ensemble_vote
except ImportError:
    from library import LibraryTools, digest
    from htr_compare import ensemble_vote


def file_hash(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


class AgentTools(LibraryTools):
    def __init__(self, engine):
        super().__init__(engine)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS agent_jobs(id TEXT PRIMARY KEY,page TEXT REFERENCES pages(id),data TEXT);
        CREATE TABLE IF NOT EXISTS agent_history(id INTEGER PRIMARY KEY,job TEXT,data TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS agent_feedback(id TEXT PRIMARY KEY,job TEXT,data TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')

    def source_state(self,page,annotation):
        p=self.engine.page(page)
        region=next((r for r in self.annotations({'id':page}) if r['id']==annotation),None)
        if not region or region['kind']!='line':raise ValueError('Виберіть збережену ділянку рядка.')
        document=self.db.execute('SELECT * FROM documents WHERE id=?',(p['doc'],)).fetchone()
        return {'source_sha256':document['sha'],'region':region}

    def agent_jobs(self,a):
        return [json.loads(r['data'])|{'id':r['id']} for r in self.db.execute('SELECT * FROM agent_jobs WHERE page=? ORDER BY rowid DESC',(a['page'],))]

    def write_job(self,ident,job,event):
        with self.db:
            self.db.execute('INSERT INTO agent_jobs VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(ident,job['page'],json.dumps(job,ensure_ascii=False)))
            self.db.execute('INSERT INTO agent_history(job,data) VALUES (?,?)',(ident,json.dumps({'event':event,'state':job['state']},ensure_ascii=False)))
        return job|{'id':ident}

    def agent_create(self,a):
        models=a['models']
        if len(models)<2 or len(models)>4 or len({m['name'] for m in models})!=len(models):raise ValueError('Виберіть від двох до чотирьох моделей з різними назвами.')
        identities=[]
        for model in models:
            if model['engine'] not in ['kraken','trocr']:raise ValueError('Непідтримуваний рушій.')
            path=Path(model['path']).resolve()
            if not path.exists():raise ValueError('Файл моделі не знайдено.')
            files=[path] if path.is_file() else sorted(p for p in path.rglob('*') if p.is_file())
            identities.append({'name':model['name'],'files':{str(p.relative_to(path)) if path.is_dir() else p.name:file_hash(p) for p in files}})
        if len({digest(sorted(i['files'].values())) for i in identities})<2:raise ValueError('Порівняння потребує різних моделей.')
        state=self.source_state(a['page'],a['annotation'])
        job={'page':a['page'],'annotation':a['annotation'],'snapshot':digest(state),'models':models,'identities':identities,'state':'layout','stages':{},'verified':False}
        return self.write_job(uuid.uuid4().hex,job,'created')

    def job(self,ident):
        row=self.db.execute('SELECT data FROM agent_jobs WHERE id=?',(ident,)).fetchone()
        if not row:raise ValueError('Завдання не знайдено.')
        return json.loads(row['data'])

    def agent_step(self,a):
        ident=a['job'];job=self.job(ident)
        if job['state'] in ['cancelled','review','complete']:return job|{'id':ident}
        if digest(self.source_state(job['page'],job['annotation']))!=job['snapshot']:raise ValueError('Джерело або ділянка змінилися. Створіть нове завдання.')
        try:
            stage=job['state']
            if stage=='layout':
                job['stages']['layout']={'region':self.source_state(job['page'],job['annotation'])['region'],'policy':'Saved human-bounded line; no automatic ground truth'}
                job['state']='recognition'
            elif stage in ['recognition','failed']:
                job['state']='recognition'
                for model,identity in zip(job['models'],job['identities']):
                    root=Path(model['path']).resolve()
                    for relative,expected in identity['files'].items():
                        path=root/relative if root.is_dir() else root
                        if not path.is_file() or file_hash(path)!=expected:raise ValueError('Модель змінилася. Створіть нове завдання.')
                job['stages']['recognition']=self.compare_regions({'id':job['page'],'annotation':job['annotation'],'models':job['models']})
                job['state']='comparison'
            elif stage=='comparison':
                report=job['stages']['recognition'];job['stages']['comparison']=[{'id':r['id'],'results':r['results'],'ensemble':ensemble_vote(r['results'],job['models'])} for r in report['rows']]
                job['state']='review'
            job.pop('error',None)
        except Exception as exc:
            job['state']='failed';job['error']=str(exc)
        return self.write_job(ident,job,'step')

    def agent_cancel(self,a):
        job=self.job(a['job']);job['state']='cancelled'
        return self.write_job(a['job'],job,'cancelled')

    def agent_review(self,a):
        job=self.job(a['job'])
        if job['state']!='review':raise ValueError('Спочатку завершіть порівняння.')
        if digest(self.source_state(job['page'],job['annotation']))!=job['snapshot']:raise ValueError('Джерело або ділянка змінилися. Створіть нове завдання.')
        text=a.get('text','').strip()
        if not text or not a.get('checked'):raise ValueError('Прочитайте оригінал і підтвердьте виправлення.')
        # Explicit human feedback remains separate: applying GT is a separate tutor action.
        feedback={'text':text,'snapshot':job['snapshot'],'page':job['page'],'annotation':job['annotation'],'human_checked':True,'training_candidate':True,'applied_to_source':False}
        with self.db:self.db.execute('INSERT INTO agent_feedback VALUES (?,?,?,CURRENT_TIMESTAMP)',(uuid.uuid4().hex,a['job'],json.dumps(feedback,ensure_ascii=False)))
        job['feedback']=feedback;job['state']='complete'
        return self.write_job(a['job'],job,'human_review')

    def agent_history(self,a):
        self.job(a['job'])
        return [dict(r)|{'data':json.loads(r['data'])} for r in self.db.execute('SELECT * FROM agent_history WHERE job=? ORDER BY id',(a['job'],))]
