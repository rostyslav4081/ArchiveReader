"""Reviewable identity links between explicit person mentions, never automatic merges."""
import hashlib
import json
from difflib import SequenceMatcher
try:
    from .sources import SourceTools
    from .workbench import name_key
except ImportError:
    from sources import SourceTools
    from workbench import name_key


class PeopleTools(SourceTools):
    def __init__(self,engine):
        super().__init__(engine)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS person_links(pair TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS person_link_history(id INTEGER PRIMARY KEY, pair TEXT, before TEXT, after TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')

    def mentions(self,page=None,records=None):
        result=[];base='SELECT r.rowid AS record_order,r.id,r.data,r.page,p.num,d.name FROM records r JOIN pages p ON p.id=r.page JOIN documents d ON d.id=p.doc';rows=[]
        if records is not None:
            identifiers=sorted(set(records))
            if not identifiers:return []
            for offset in range(0,len(identifiers),400):
                part=identifiers[offset:offset+400];where=' WHERE r.id IN ('+','.join('?' for _ in part)+')';params=list(part)
                if page is not None:where+=' AND r.page=?';params.append(page)
                rows.extend(self.db.execute(base+where+' ORDER BY r.rowid',params))
            rows.sort(key=lambda row:row['record_order'])
        else:rows=self.db.execute(base+(' WHERE r.page=?' if page is not None else '')+' ORDER BY r.rowid',(page,) if page is not None else ())
        for row in rows:
            data=json.loads(row['data'])
            for field in ['person','related1','related2']:
                name=data.get(field,'').strip()
                if not name: continue
                evidence={k:data.get(k,'') for k in ['kind','date','person','place','house','age','related1','related2','text','notes','verified']}
                result.append({'record':row['id'],'field':field,'name':name,'page':row['page'],'document':row['name'],'number':row['num']+1,'evidence':evidence,
                               'signature':hashlib.sha256(row['data'].encode('utf8')).hexdigest()})
        return result

    @staticmethod
    def key(mention): return mention['record']+':'+mention['field']

    def find(self,ref,mentions):
        found=next((m for m in mentions if m['record']==ref.get('record') and m['field']==ref.get('field')),None)
        if found is None: raise ValueError('Згадку особи не знайдено.')
        return found

    @staticmethod
    def pair_key(left,right): return json.dumps(sorted([PeopleTools.key(left),PeopleTools.key(right)]))

    def enrich(self,mention):
        return mention|{'citation':self.source_card({'id':mention['page']})['citation'],
                        'regions':[r for r in self.annotations({'id':mention['page']}) if r.get('record')==mention['record']]}

    def person_mentions(self,a):
        self.engine.page(a['id'])
        return self.mentions(page=a['id'])

    def person_candidates(self,a):
        mentions=self.mentions(); left=self.find(a['left'],mentions); results=[]
        for right in mentions:
            if right['record']==left['record']: continue
            score=SequenceMatcher(None,name_key(left['name']),name_key(right['name'])).ratio()
            pair=self.pair_key(left,right)
            stored=self.db.execute('SELECT data FROM person_links WHERE pair=?',(pair,)).fetchone()
            decision=json.loads(stored['data']) if stored else None
            if score<.6 and not decision: continue
            agreements=[]; differences=[]
            for field in ['place','house']:
                x,y=left['evidence'].get(field),right['evidence'].get(field)
                if x and y: (agreements if name_key(x)==name_key(y) else differences).append(field)
            stale=bool(decision and any(decision['signatures'].get(self.key(m))!=m['signature'] for m in [left,right]))
            results.append({'left':left,'right':right,'similarity':round(score,3),'agreements':agreements,'differences':differences,
                            'decision':decision,'expected':hashlib.sha256(stored['data'].encode('utf8')).hexdigest() if stored else None,'stale':stale})
        results.sort(key=lambda r:(-r['similarity'],r['right']['document'],r['right']['number']))
        selected=[r for r in results if r['decision']]+[r for r in results if not r['decision']][:100]
        enriched_left=self.enrich(left)
        return [r|{'left':enriched_left,'right':self.enrich(r['right'])} for r in selected]

    def person_link(self,a):
        mentions=self.mentions(records=[a['left']['record'],a['right']['record']]); left=self.find(a['left'],mentions); right=self.find(a['right'],mentions)
        if left['record']==right['record']: raise ValueError('Виберіть згадки з різних записів.')
        status=a.get('status')
        if status not in ['confirmed','rejected','withdrawn']: raise ValueError('Неправильний стан зв’язку.')
        if not a.get('note','').strip(): raise ValueError('Додайте пояснення рішення.')
        if any(a.get('signatures',{}).get(self.key(m))!=m['signature'] for m in [left,right]):
            raise ValueError('Запис змінився. Оновіть можливі збіги.')
        pair=self.pair_key(left,right); old=self.db.execute('SELECT data FROM person_links WHERE pair=?',(pair,)).fetchone()
        previous=old['data'] if old else None
        if a.get('expected')!=(hashlib.sha256(previous.encode('utf8')).hexdigest() if previous else None): raise ValueError('Рішення змінилося. Оновіть можливі збіги.')
        data={'left':self.enrich(left),'right':self.enrich(right),'status':status,'note':a['note'].strip(),
              'signatures':{self.key(m):m['signature'] for m in [left,right]}}
        encoded=json.dumps(data,ensure_ascii=False)
        with self.db:
            self.db.execute('INSERT INTO person_link_history(pair,before,after) VALUES (?,?,?)',(pair,previous,encoded))
            self.db.execute('INSERT INTO person_links VALUES (?,?) ON CONFLICT(pair) DO UPDATE SET data=excluded.data',(pair,encoded))
        return data

    def link_inventory(self,record=None):
        sql='SELECT data FROM person_links';params=()
        if record is not None:sql+=" WHERE json_extract(data,'$.left.record')=? OR json_extract(data,'$.right.record')=?";params=(record,record)
        links=[json.loads(row['data']) for row in self.db.execute(sql,params)]
        records={link[side]['record'] for link in links for side in ['left','right']}
        mentions={self.key(m):m for m in self.mentions(records=records)};result=[]
        for link in links:
            stale=any(key not in mentions or mentions[key]['signature']!=signature for key,signature in link['signatures'].items())
            result.append(link|{'stale':stale})
        return result

    def record_links(self,record):
        return self.link_inventory(record=record)
