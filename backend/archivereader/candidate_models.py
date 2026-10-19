"""Train a separate candidate on human examples and compare on frozen held-out books."""
import json
import re
from pathlib import Path
import uuid
import sys
try:
    from .library import LibraryTools
    from .agents import file_hash
except ImportError:
    from library import LibraryTools
    from agents import file_hash


def candidate_verdict(rows):
    common=[];failures={'base':0,'candidate':0}
    for row in rows:
        for name in failures:
            if 'text' not in row.get('results',{}).get(name,{}):failures[name]+=1
        results=row.get('results',{})
        a,b=results.get('base',{}).get('score',{}),results.get('candidate',{}).get('score',{})
        if a.get('characters',0)>0 and a.get('characters')==b.get('characters') and a.get('character_errors') is not None and b.get('character_errors') is not None:
            common.append((a,b))
    chars=sum(a['characters'] for a,b in common)
    totals={name:sum(pair[index]['character_errors'] for pair in common) for index,name in enumerate(['base','candidate'])}
    status='inconclusive'
    if chars:
        status='improved' if totals['candidate']<totals['base'] and failures['candidate']<=failures['base'] else 'rejected'
    return {'status':status,'common_lines':len(common),'characters':chars,'character_errors':totals,'failures':failures,
            'cer':{name:value/chars if chars else None for name,value in totals.items()},'provisional':True,'promoted':False,
            'policy':'Same successful frozen rows only. Lower CER and no additional failed lines required. Human-approved references only; no automatic promotion.'}


class CandidateTools(LibraryTools):
    def __init__(self,engine):
        super().__init__(engine)
        self.db.execute('CREATE TABLE IF NOT EXISTS candidate_models(id TEXT PRIMARY KEY,data TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP)')

    def candidate_list(self,a):
        return [dict(id=r['id'],**json.loads(r['data'])) for r in self.db.execute('SELECT * FROM candidate_models ORDER BY rowid DESC LIMIT 50')]

    def candidate_save(self,ident,data):
        with self.db:self.db.execute('INSERT INTO candidate_models(id,data) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(ident,json.dumps(data,ensure_ascii=False)))
        return data|{'id':ident}

    def candidate_train_check(self,a):
        model=Path(a['model']).resolve()
        if not model.is_file():raise ValueError('Виберіть локальну модель Kraken.')
        epochs=int(a.get('epochs',1))
        if not 1<=epochs<=100:raise ValueError('Epochs must be between 1 and 100')
        inventory=self.benchmark_inventory({})
        counts={role:sum(r['verified_lines'] for r in inventory if r['split']==role) for role in ['train','validation','test']}
        if not all(counts.values()):return {'status':'preflight_failed','counts':counts,'promoted':False,'message':'Потрібні перевірені рядки окремих книг train, validation і test. Пошкоджені та непевні рядки не підходять.'}
        frozen=self.benchmark_freeze({})
        valid={role:frozen.get(role,0) for role in counts}
        if not all(valid.values()):return {'status':'preflight_failed','counts':valid,'promoted':False,'message':'Після виключення пошкоджень бракує перевірених рядків train, validation або test.'}
        folder=Path(frozen['path']);manifest=folder/'manifest.json'
        rows=json.loads(manifest.read_text(encoding='utf8'))
        documents={role:{r['document'] for r in rows if r['split']==role} for role in counts}
        # The dataset exporter enforces book families; recheck before training.
        for role,docs in documents.items():
            for doc in docs:
                family=self.document_family(doc)
                if any(family&other for otherrole,other in documents.items() if otherrole!=role):raise ValueError('Навчальні й тестові книги перетинаються.')
        ident=uuid.uuid4().hex;record={'status':'training','base':str(model),'base_sha256':file_hash(model),'frozen_path':str(folder),'manifest_sha256':file_hash(manifest),'counts':valid,'epochs':epochs,'promoted':False}
        self.candidate_save(ident,record)
        try:
            trained=self.engine.train_model({'model':str(model),'explicit':True,'epochs':epochs,'executable':a.get('executable') or str(Path(sys.executable).parent/('ketos.exe' if sys.platform=='win32' else 'ketos'))})
            actual=json.loads((Path(trained['path'])/'dataset'/'manifest.json').read_text(encoding='utf8'))
            def training_rows(items):
                return sorted((r['document'],r['split'],r['image_sha256'],r['text']) for r in items if r['split'] in ['train','validation'])
            if training_rows(actual)!=training_rows(rows):raise ValueError('Навчальні приклади змінилися після фіксації набору. Створіть нову перевірку.')
            candidates=[Path(p).resolve() for p in trained['models'] if Path(p).is_file()]
            if not candidates:raise ValueError('Навчання не створило контрольної моделі.')
            def rank(path):
                digits=re.findall(r'\d+',path.stem)
                return ('best' in path.stem.casefold(),int(digits[-1]) if digits else -1,path.name)
            candidate=max(candidates,key=rank)
            if candidate==model or file_hash(model)!=record['base_sha256']:raise ValueError('Базова модель змінилася. Перевірку зупинено.')
            record.update(candidate=str(candidate),candidate_sha256=file_hash(candidate),training_path=trained['path'],status='evaluating')
            self.candidate_save(ident,record)
            report=self.benchmark_compare({'path':str(folder),'models':[{'name':'base','engine':'kraken','path':str(model)},{'name':'candidate','engine':'kraken','path':str(candidate)}]})
            record.update(candidate_verdict(report['rows']),report=report)
        except Exception as exc:record.update(status='failed',error=str(exc))
        return self.candidate_save(ident,record)
