"""Individual fact assessments, immutable evidence snapshots and cautious neighbors."""
import json
import re
import uuid
from difflib import SequenceMatcher
try:
    from .people import PeopleTools
    from .sources import signature
    from .workbench import name_key,validate_rect
except ImportError:
    from people import PeopleTools
    from sources import signature
    from workbench import name_key,validate_rect

FIELDS=['person','date','place','house','age','related1','related2','text','kinship']
STATES=['document_observation','transcription','hypothesis','corroborated']


class FactReviewTools(PeopleTools):
    def __init__(self,engine):
        super().__init__(engine)
        self.db.executescript('''CREATE TABLE IF NOT EXISTS fact_reviews(record TEXT REFERENCES records(id),field TEXT,data TEXT,PRIMARY KEY(record,field));
        CREATE TABLE IF NOT EXISTS fact_review_history(id INTEGER PRIMARY KEY,record TEXT,field TEXT,before TEXT,after TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);''')

    def fact_source(self,record,rect=None):
        row=self.db.execute('SELECT r.*,p.doc,p.num,d.sha,d.name FROM records r JOIN pages p ON p.id=r.page JOIN documents d ON d.id=p.doc WHERE r.id=?',(record,)).fetchone()
        if not row:raise ValueError('Запис-доказ не знайдено.')
        card=self.source_card({'id':row['page']});regions=[r for r in self.annotations({'id':row['page']}) if r.get('record')==record]
        result={'record':record,'page':row['page'],'doc':row['doc'],'number':row['num']+1,'name':row['name'],'values':json.loads(row['data']),'source_sha256':row['sha'],'citation':card['citation'],'source_card_signature':card['signature'],'regions':regions}
        result['signature']=signature(result)
        if rect is not None:result['rect']=validate_rect(rect)
        return result

    def fact_reviews(self,a):
        source=self.fact_source(a['record']);result=[]
        for field in FIELDS:
            row=self.db.execute('SELECT data FROM fact_reviews WHERE record=? AND field=?',(a['record'],field)).fetchone()
            saved=json.loads(row['data']) if row else None
            stale=False
            if saved:
                for proof in [saved['source']]+saved['supports']:
                    try:stale|=self.fact_source(proof['record'])['signature']!=proof['signature']
                    except ValueError:stale=True
            result.append({'field':field,'value':source['values'].get(field,''),'assessment':saved,'stale':stale})
        return {'source':source,'facts':result,'policy':'Fact assessment does not change record verification or original text.'}

    def fact_save(self,a):
        field=a['field'];state=a['status']
        if field not in FIELDS or state not in STATES:raise ValueError('Неправильне поле або стан факту.')
        source=self.fact_source(a['record'],a.get('rect'))
        if a.get('signature')!=source['signature']:raise ValueError('Запис або джерело змінилися. Оновіть докази.')
        if not str(a.get('value','')).strip() or not a.get('note','').strip():raise ValueError('Вкажіть значення та пояснення оцінки.')
        old=self.db.execute('SELECT data FROM fact_reviews WHERE record=? AND field=?',(a['record'],field)).fetchone();previous=json.loads(old['data']) if old else None
        if a.get('revision')!=(previous or {}).get('revision'):raise ValueError('Оцінка факту змінилася. Оновіть список.')
        supports=[];seen={a['record']}
        for item in a.get('supports',[]):
            if item['record'] in seen:continue
            proof=self.fact_source(item['record'],item.get('rect'))
            if proof['signature']!=item.get('signature'):raise ValueError('Запис або джерело змінилися. Оновіть докази.')
            seen.add(item['record']);supports.append(proof)
        if state=='corroborated':
            docs=[r['doc'] for r in [source]+supports]
            if not a.get('reviewed') or len(docs)<2 or any(self.document_family(doc)&set(docs[:i]) for i,doc in enumerate(docs)):
                raise ValueError('Підтвердження потребує щонайменше двох незалежних документів і ручної перевірки.')
        data={'value':str(a['value']).strip(),'status':state,'note':a['note'].strip(),'source':source,'supports':supports,'reviewed':bool(a.get('reviewed')),'revision':uuid.uuid4().hex}
        encoded=json.dumps(data,ensure_ascii=False)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            actual=self.db.execute('SELECT data FROM fact_reviews WHERE record=? AND field=?',(a['record'],field)).fetchone()
            if (actual['data'] if actual else None)!=(old['data'] if old else None):raise ValueError('Оцінка факту змінилася. Оновіть список.')
            for proof in [source]+supports:
                if self.fact_source(proof['record'])['signature']!=proof['signature']:raise ValueError('Запис або джерело змінилися. Оновіть докази.')
            self.db.execute('INSERT INTO fact_review_history(record,field,before,after) VALUES (?,?,?,?)',(a['record'],field,old['data'] if old else None,encoded))
            self.db.execute('INSERT INTO fact_reviews VALUES (?,?,?) ON CONFLICT(record,field) DO UPDATE SET data=excluded.data',(a['record'],field,encoded))
        return self.fact_reviews({'record':a['record']})

    def fact_history(self,a):
        self.fact_source(a['record'])
        return [dict(r)|{'before':json.loads(r['before']) if r['before'] else None,'after':json.loads(r['after'])} for r in self.db.execute('SELECT * FROM fact_review_history WHERE record=? AND field=? ORDER BY id DESC',(a['record'],a['field']))]

    def fact_supports(self,a):
        query=name_key(a.get('query',''));result=[]
        for row in self.db.execute('SELECT id,data FROM records ORDER BY rowid DESC'):
            if row['id']==a['record']:continue
            if query and query not in name_key(row['data']):continue
            result.append(self.fact_source(row['id']))
            if len(result)>=100:break
        return result

    def neighbor_candidates(self,a):
        source=self.fact_source(a['record']);page=self.engine.page(source['page']);radius=max(1,min(20,int(a.get('radius',3))))
        group=self.photo_book(page['doc']);positions={}
        if group:
            ordered=[r['page'] for r in self.db.execute('SELECT page FROM book_items WHERE book=? ORDER BY position',(group['id'],))]
            origin=ordered.index(page['id']);positions={p:i-origin for i,p in enumerate(ordered) if p and abs(i-origin)<=radius}
        else:positions={r['id']:r['num']-page['num'] for r in self.db.execute('SELECT id,num FROM pages WHERE doc=? AND num BETWEEN ? AND ?',(page['doc'],page['num']-radius,page['num']+radius))}
        result=[];left=source['values']
        placeholders=','.join('?' for _ in positions)
        for row in self.db.execute('SELECT id,page,data FROM records WHERE page IN ('+placeholders+')',tuple(positions)):
            if row['id']==a['record'] or row['page'] not in positions:continue
            right=json.loads(row['data']);signals=[];differences=[];score=0
            x,y=name_key(left.get('person','')),name_key(right.get('person',''))
            similarity=SequenceMatcher(None,x,y).ratio() if x and y else 0
            if similarity>=.65:signals.append({'field':'person','kind':'similar','similarity':round(similarity,3)});score+=similarity
            elif x and y:differences.append({'field':'person','left':left.get('person'),'right':right.get('person')})
            for field in ['house','place','date']:
                x,y=name_key(str(left.get(field,''))),name_key(str(right.get(field,'')))
                if x and y:
                    if x==y:signals.append({'field':field,'kind':'exact'});score+=1
                    else:differences.append({'field':field,'left':left.get(field),'right':right.get(field)})
            if not signals:continue
            result.append({'source':self.fact_source(row['id']),'distance':positions[row['page']],'signals':signals,'differences':differences,'score':round(score,3),'linked':False,'policy':'Differences may describe different events or people. No automatic identity link.'})
        return sorted(result,key=lambda r:(-r['score'],abs(r['distance'])))[:100]
