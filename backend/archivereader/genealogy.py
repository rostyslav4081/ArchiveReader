"""Explicit person cards and evidence-backed family relationships."""
import hashlib
import json
import re
import uuid
try:
    from .people import PeopleTools
except ImportError:
    from people import PeopleTools


class GenealogyTools(PeopleTools):
    def __init__(self,engine):
        super().__init__(engine)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS persons(id TEXT PRIMARY KEY,data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS person_members(mention TEXT PRIMARY KEY,person TEXT REFERENCES persons(id),data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS family_links(id TEXT PRIMARY KEY,data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS genealogy_history(id INTEGER PRIMARY KEY,entity TEXT,before TEXT,after TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')
        try:
            from .schema_indexes import ensure_indexes
        except ImportError:from schema_indexes import ensure_indexes
        ensure_indexes(self.db)

    def write(self,table,ident,values):
        assert table in ['persons','family_links']
        old=self.db.execute(f'SELECT data FROM {table} WHERE id=?',(ident,)).fetchone()
        encoded=json.dumps(values,ensure_ascii=False)
        with self.db:
            self.db.execute('INSERT INTO genealogy_history(entity,before,after) VALUES (?,?,?)',(table+':'+ident,old['data'] if old else None,encoded))
            self.db.execute(f'INSERT INTO {table} VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(ident,encoded))

    def person_list(self,a):
        return [json.loads(row['data'])|{'id':row['id']} for row in self.db.execute('SELECT * FROM persons ORDER BY rowid') if not json.loads(row['data']).get('merged_into')]

    def genealogy_mentions(self,a):
        if a.get('query'):
            matches={(r['record'],r['field']) for r in self.similar_names({'query':a['query']})}
            mentions=[m for m in self.mentions(records={record for record,field in matches}) if (m['record'],m['field']) in matches]
        elif a.get('page'):mentions=self.mentions(page=a['page'])
        else:mentions=[]
        return [self.enrich(m) for m in mentions[:100]]

    def require_person(self,ident):
        row=self.db.execute('SELECT data FROM persons WHERE id=?',(ident,)).fetchone()
        if not row: raise ValueError('Картку людини не знайдено.')
        return json.loads(row['data'])|{'id':ident}

    def person_save(self,a):
        name=a.get('name','').strip()
        if not name: raise ValueError('Вкажіть ім’я для картки.')
        ident=a.get('id') or uuid.uuid4().hex
        if a.get('id'): self.require_person(ident)
        old=self.require_person(ident) if a.get('id') else {};old.pop('id',None)
        self.write('persons',ident,old|{'name':name,'notes':a.get('notes','')})
        return self.require_person(ident)

    def person_attach(self,a):
        person=a['person'];self.require_person(person);mention=self.find(a['mention'],self.mentions(records=[a['mention']['record']]));key=self.key(mention)
        if a.get('signature')!=mention['signature']: raise ValueError('Запис змінився. Оновіть можливі збіги.')
        if not a.get('note','').strip(): raise ValueError('Додайте пояснення рішення.')
        old=self.db.execute('SELECT person,data FROM person_members WHERE mention=?',(key,)).fetchone()
        if old and old['person']!=person: raise ValueError('Згадка вже належить іншій картці. Спершу від’єднайте її.')
        # A known active rejection cannot silently be overridden by card membership.
        for member in self.db.execute('SELECT data FROM person_members WHERE person=?',(person,)):
            existing=json.loads(member['data'])['mention'];pair=self.pair_key(existing,mention)
            link=self.db.execute('SELECT data FROM person_links WHERE pair=?',(pair,)).fetchone()
            if link and json.loads(link['data'])['status']=='rejected': raise ValueError('Є рішення «Різні особи». Спершу перегляньте його.')
        values={'mention':self.enrich(mention),'note':a['note'].strip()};encoded=json.dumps(values,ensure_ascii=False)
        with self.db:
            self.db.execute('INSERT INTO genealogy_history(entity,before,after) VALUES (?,?,?)',('member:'+key,old['data'] if old else None,encoded))
            self.db.execute('INSERT INTO person_members VALUES (?,?,?) ON CONFLICT(mention) DO UPDATE SET data=excluded.data',(key,person,encoded))
        return self.person_card({'id':person})

    def person_detach(self,a):
        row=self.db.execute('SELECT * FROM person_members WHERE mention=? AND person=?',(a['mention'],a['person'])).fetchone()
        if not row: raise ValueError('Згадку особи не знайдено.')
        with self.db:
            self.db.execute('INSERT INTO genealogy_history(entity,before,after) VALUES (?,?,NULL)',('member:'+a['mention'],row['data']))
            self.db.execute('DELETE FROM person_members WHERE mention=?',(a['mention'],))
        return self.person_card({'id':a['person']})

    def person_card(self,a):
        person=self.require_person(a['id']);saved_members=list(self.db.execute('SELECT * FROM person_members WHERE person=? ORDER BY rowid',(a['id'],)));records={json.loads(row['data'])['mention']['record'] for row in saved_members};live={self.key(m):m for m in self.mentions(records=records)};members=[]
        for row in saved_members:
            saved=json.loads(row['data']);current=live.get(row['mention'])
            members.append(saved|{'key':row['mention'],'stale':current is None or current['signature']!=saved['mention']['signature'],
                                 'current':self.enrich(current) if current else None})
        variants=sorted({m['mention']['name'] for m in members}|set(person.get('aliases',[])))
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='fact_crops'").fetchone():
            for member in members:
                member['fact_bounds']=[json.loads(r['data'])|{'fact':r['mention'].rsplit(':',1)[-1]} for r in self.db.execute("SELECT mention,data FROM fact_crops WHERE substr(mention,1,length(?)+1)=?||':'",(member['key'],member['key']))]
        variations={field:sorted({str(m['mention']['evidence'].get(field,'')) for m in members if m['mention']['evidence'].get(field)}) for field in ['place','house','age']}
        # Original dates remain intact. Ordering is explicitly a coarse year hint.
        def year(member):
            found=re.search(r'(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)',member['mention']['evidence'].get('date',''))
            return int(found[0]) if found else 9999
        return person|{'members':sorted(members,key=year),'variants':variants,'variations':variations,
                       'relationships':self.family_list({'person':a['id']})}

    def family_list(self,a):
        sql='SELECT * FROM family_links';params=()
        if a.get('person'):sql+=" WHERE json_extract(data,'$.left')=? OR json_extract(data,'$.right')=?";params=(a['person'],a['person'])
        rows=list(self.db.execute(sql+' ORDER BY rowid',params));links=[json.loads(row['data']) for row in rows]
        identifiers=sorted({link.get('record') for link in links if link.get('record')});records={}
        for offset in range(0,len(identifiers),400):
            part=identifiers[offset:offset+400]
            records.update({row['id']:json.loads(row['data']) for row in self.db.execute('SELECT id,data FROM records WHERE id IN ('+','.join('?' for _ in part)+')',part)})
        result=[]
        for row,data in zip(rows,links):
            current=records.get(data.get('record'));stale=current is None or hashlib.sha256(json.dumps(current,ensure_ascii=False).encode('utf8')).hexdigest()!=data['signature']
            result.append(data|{'id':row['id'],'stale':stale})
        return result

    def family_tree(self,a):
        try:from .genealogy_layout import layout_tree
        except ImportError:from genealogy_layout import layout_tree
        # "root" is reserved for the library directory in the worker protocol.
        return layout_tree(self.person_list({}),self.family_list({}),a.get('focus_person'))

    def family_save(self,a):
        left,right=a['left'],a['right'];self.require_person(left);self.require_person(right)
        if left==right or a.get('kind') not in ['parent','spouse']: raise ValueError('Неправильний родинний зв’язок.')
        status=a.get('status','confirmed')
        if status not in ['confirmed','withdrawn']: raise ValueError('Неправильний стан зв’язку.')
        if not a.get('note','').strip(): raise ValueError('Додайте пояснення рішення.')
        if status=='withdrawn':
            old=next((link for link in self.family_list({}) if link['id']==a.get('id')),None)
            if old is None: raise ValueError('Родинний зв’язок не знайдено.')
            old.pop('stale',None);ident=old.pop('id');old.update({'status':'withdrawn','note':a['note']})
            self.write('family_links',ident,old);return old|{'id':ident}
        row=self.db.execute('SELECT * FROM records WHERE id=?',(a['record'],)).fetchone()
        if not row: raise ValueError('Запис-доказ не знайдено.')
        signature=hashlib.sha256(row['data'].encode('utf8')).hexdigest()
        if signature!=a.get('signature'): raise ValueError('Запис змінився. Оновіть можливі збіги.')
        links=self.family_list({});ident=a.get('id') or uuid.uuid4().hex
        if a.get('id') and not any(r['id']==ident for r in links): raise ValueError('Родинний зв’язок не знайдено.')
        if status=='confirmed':
            for link in links:
                if link['id']==ident or link['status']!='confirmed': continue
                same=(link['left']==left and link['right']==right) if a['kind']=='parent' else set([link['left'],link['right']])==set([left,right])
                if link['kind']==a['kind'] and same: raise ValueError('Такий родинний зв’язок уже збережено.')
            if a['kind']=='parent':
                edges=[(r['left'],r['right']) for r in links if r['id']!=ident and r['kind']=='parent' and r['status']=='confirmed']
                reached={right}
                while True:
                    extended=reached|{child for parent,child in edges if parent in reached}
                    if left in extended: raise ValueError('Зв’язок створює цикл предків.')
                    if extended==reached:break
                    reached=extended
        data={k:a[k] for k in ['left','right','kind','record','note']}
        data.update({'status':status,'signature':signature,'evidence':json.loads(row['data']),'page':row['page'],'citation':self.source_card({'id':row['page']})['citation']})
        self.write('family_links',ident,data);return data|{'id':ident}

    def genealogy_export(self,a):
        from pathlib import Path
        destination=Path(a['path']);destination.parent.mkdir(parents=True,exist_ok=True)
        payload={'version':1,'people':[self.person_card({'id':p['id']}) for p in self.person_list({})],'relationships':self.family_list({})}
        temporary=destination.with_name(destination.name+'.'+uuid.uuid4().hex+'.partial')
        try:
            temporary.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8');temporary.replace(destination)
        finally:temporary.unlink(missing_ok=True)
        return {'path':str(destination),'people':len(payload['people'])}
