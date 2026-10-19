"""Recoverable card edits, source crops, conservative chronology and book vocabularies."""
from datetime import date
import hashlib
import json
import re
import uuid
try:
    from .genealogy import GenealogyTools
    from .workbench import name_key,validate_rect
except ImportError:
    from genealogy import GenealogyTools
    from workbench import name_key,validate_rect


def date_bounds(text):
    """Only explicitly Gregorian exact/year/range dates; ambiguous calendars remain unknown."""
    text=text.strip().upper()
    if any(word in text for word in ['JULIAN','ЮЛІАН','JULIÁN','ABT','BEF','AFT','CAL','EST','БЛИЗ','ПРИБЛ']):return None
    if text.startswith('GREGORIAN '):text=text[10:]
    if re.fullmatch(r'\d{4}',text):return (date(int(text),1,1),date(int(text),12,31)) if int(text)>0 else None
    match=re.fullmatch(r'BET (\d{4}) AND (\d{4})',text)
    if match and 0<int(match[1])<=int(match[2]):return date(int(match[1]),1,1),date(int(match[2]),12,31)
    match=re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})',text)
    if match:
        try:value=date(*map(int,match.groups()));return value,value
        except ValueError:return None
    # Historical slash/dot dates and unmarked calendars are intentionally not converted.
    return None


class ResearchTools(GenealogyTools):
    TABLES=['persons','person_members','family_links']
    def __init__(self,engine):
        super().__init__(engine)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS card_operations(id TEXT PRIMARY KEY,before TEXT,after TEXT,note TEXT,undone INTEGER DEFAULT 0,created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS fact_crops(mention TEXT PRIMARY KEY,data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS book_words(id TEXT PRIMARY KEY,doc TEXT REFERENCES documents(id),data TEXT NOT NULL);
        ''')

    def snapshot(self):
        return {table:[dict(r) for r in self.db.execute('SELECT * FROM '+table+' ORDER BY 1')] for table in self.TABLES}

    @staticmethod
    def encoded(data):return json.dumps(data,ensure_ascii=False,sort_keys=True)

    def card_operations(self,a):
        return [dict(r) for r in self.db.execute('SELECT id,note,undone,created FROM card_operations ORDER BY rowid DESC LIMIT 30')]

    def card_change(self,a):
        if not a.get('note','').strip():raise ValueError('Додайте пояснення рішення.')
        source=a['source'];self.require_person(source);before=self.snapshot();after=json.loads(json.dumps(before))
        source_row=next(r for r in after['persons'] if r['id']==source);source_data=json.loads(source_row['data'])
        if source_data.get('merged_into'):raise ValueError('Картка вже об’єднана.')
        if a['mode']=='merge':
            target=a['target'];self.require_person(target)
            if source==target:raise ValueError('Оберіть різні картки.')
            target_row=next(r for r in after['persons'] if r['id']==target);target_data=json.loads(target_row['data'])
            if target_data.get('merged_into'):raise ValueError('Картка вже об’єднана.')
            left=[json.loads(r['data'])['mention'] for r in after['person_members'] if r['person']==source]
            right=[json.loads(r['data'])['mention'] for r in after['person_members'] if r['person']==target]
            for x in left:
                for y in right:
                    rejected=self.db.execute('SELECT data FROM person_links WHERE pair=?',(self.pair_key(x,y),)).fetchone()
                    if rejected and json.loads(rejected['data'])['status']=='rejected':raise ValueError('Є рішення «Різні особи». Спершу перегляньте його.')
            for member in after['person_members']:
                if member['person']==source:member['person']=target
            for family in after['family_links']:
                values=json.loads(family['data'])
                for side in ['left','right']:
                    if values[side]==source:values[side]=target
                family['data']=json.dumps(values,ensure_ascii=False)
            target_data['aliases']=sorted(set(target_data.get('aliases',[])+source_data.get('aliases',[])+[source_data['name']]))
            target_data['events']=target_data.get('events',[])+source_data.get('events',[])
            target_data['notes']=target_data.get('notes','')+'\n'+source_data['name']+': '+source_data.get('notes','')
            target_row['data']=json.dumps(target_data,ensure_ascii=False);source_data['merged_into']=target;source_row['data']=json.dumps(source_data,ensure_ascii=False)
        elif a['mode']=='split':
            keys=set(a.get('mentions',[]));members=[r for r in after['person_members'] if r['person']==source and r['mention'] in keys]
            if not keys or len(members)!=len(keys) or not a.get('name','').strip():raise ValueError('Оберіть згадки та ім’я нової картки.')
            target=uuid.uuid4().hex;after['persons'].append({'id':target,'data':json.dumps({'name':a['name'].strip(),'notes':a['note']},ensure_ascii=False)})
            for member in members:member['person']=target
            # Relationships remain on the original card; no guessed reassignment.
        else:raise ValueError('Неправильна дія з картками.')
        active=[json.loads(r['data']) for r in after['family_links'] if json.loads(r['data'])['status']=='confirmed']
        seen=set();edges=[]
        for link in active:
            if link['left']==link['right']:raise ValueError('Об’єднання створює зв’язок людини із собою.')
            pair=(link['kind'],link['left'],link['right']) if link['kind']=='parent' else ('spouse',*sorted([link['left'],link['right']]))
            if pair in seen:raise ValueError('Об’єднання дублює родинний зв’язок. Спершу перегляньте зв’язки.')
            seen.add(pair)
            if link['kind']=='parent':edges.append((link['left'],link['right']))
        for origin,_ in edges:
            reached=set();frontier={origin}
            while frontier:
                next_nodes={child for parent,child in edges if parent in frontier}
                if origin in next_nodes:raise ValueError('Зв’язок створює цикл предків.')
                frontier=next_nodes-reached;reached|=next_nodes
        ident=uuid.uuid4().hex
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.encoded(self.snapshot())!=self.encoded(before):raise ValueError('Картки змінилися. Оновіть вікно.')
            for row in after['persons']:self.db.execute('INSERT INTO persons VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(row['id'],row['data']))
            for row in after['person_members']:self.db.execute('UPDATE person_members SET person=? WHERE mention=?',(row['person'],row['mention']))
            for row in after['family_links']:self.db.execute('UPDATE family_links SET data=? WHERE id=?',(row['data'],row['id']))
            self.db.execute('INSERT INTO card_operations(id,before,after,note) VALUES (?,?,?,?)',(ident,self.encoded(before),self.encoded(self.snapshot()),a['note']))
        return {'id':ident,'person':target}

    def card_undo(self,a):
        row=self.db.execute('SELECT * FROM card_operations WHERE id=?',(a['id'],)).fetchone()
        if not row or row['undone']:raise ValueError('Дію вже скасовано або не знайдено.')
        if self.encoded(self.snapshot())!=row['after']:raise ValueError('Картки змінилися після дії. Автоматичне скасування заблоковано.')
        before=json.loads(row['before'])
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.encoded(self.snapshot())!=row['after']:raise ValueError('Картки змінилися після дії. Автоматичне скасування заблоковано.')
            self.db.execute('DELETE FROM person_members');self.db.execute('DELETE FROM family_links');self.db.execute('DELETE FROM persons')
            for table in self.TABLES:
                for item in before[table]:
                    columns=list(item);self.db.execute('INSERT INTO '+table+' ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',tuple(item[c] for c in columns))
            self.db.execute('UPDATE card_operations SET undone=1 WHERE id=?',(a['id'],))
        return {'restored':True}

    def fact_crop(self,a):
        mention=self.find(a['mention'],self.mentions());fact=a.get('fact','record')
        if fact not in ['record','person','date','place','house','age','related1','related2']:raise ValueError('Неправильне поле факту.')
        key=self.key(mention)+':'+fact
        if a.get('whole'):return self.engine.render({'id':mention['page']})|{'whole_page':True,'stale':False}
        if 'rect' in a:
            validate_rect(a['rect'])
            with self.db:self.db.execute('INSERT INTO fact_crops VALUES (?,?) ON CONFLICT(mention) DO UPDATE SET data=excluded.data',(key,json.dumps({'page':mention['page'],'rect':a['rect'],'signature':mention['signature']})))
        stored=self.db.execute('SELECT data FROM fact_crops WHERE mention=?',(key,)).fetchone();data=json.loads(stored['data']) if stored else None
        annotations=[r for r in self.annotations({'id':mention['page']}) if r.get('record')==mention['record']]
        if not data and annotations:
            rects=[r['rect'] for r in annotations];x=min(r[0] for r in rects);y=min(r[1] for r in rects)
            data={'page':mention['page'],'rect':[x,y,max(r[0]+r[2] for r in rects)-x,max(r[1]+r[3] for r in rects)-y]}
        if not data:return self.engine.render({'id':mention['page']})|{'whole_page':True,'stale':False}
        image=self.whole_image(mention['page']);x,y,w,h=data['rect'];image=image.crop((round(x*image.width),round(y*image.height),round((x+w)*image.width),round((y+h)*image.height)))
        path=self.engine.root/'cache'/('fact-'+uuid.uuid4().hex+'.png');image.save(path)
        return {'path':str(path),'whole_page':False,'stale':data.get('signature',mention['signature'])!=mention['signature']}

    def chronology_hints(self,a):
        cards=[self.person_card({'id':p['id']}) for p in self.person_list({})];events={};hints=[];uncompared=0
        for card in cards:
            rows=[]
            for member in card['members']:
                mention=member['mention']
                if mention['field']!='person' or member['stale']:continue
                evidence=mention['evidence'];raw_date=evidence.get('date','');calendar=self.book_profile({'id':mention['page']}).get('calendar','')
                bounds=date_bounds(raw_date) if calendar=='gregorian' or raw_date.strip().upper().startswith('GREGORIAN ') else None
                if raw_date and not bounds:uncompared+=1
                if bounds:rows.append({'kind':evidence['kind'],'bounds':bounds,'citation':mention['citation'],'key':member['key']})
            events[card['id']]=rows
            deaths=[r for r in rows if r['kind']=='Смерті']
            for death in deaths:
                for event in rows:
                    if event['bounds'][0]>death['bounds'][1]:hints.append({'person':card['id'],'kind':'after_death','sources':[death['citation'],event['citation']],'mentions':[death['key'],event['key']]})
        for link in self.family_list({}):
            if link['kind']!='parent' or link['status']!='confirmed' or link['stale']:continue
            parents=[r for r in events.get(link['left'],[]) if r['kind']=='Народження'];children=[r for r in events.get(link['right'],[]) if r['kind']=='Народження']
            for parent in parents:
                for child in children:
                    if child['bounds'][1]<parent['bounds'][0] or (child['bounds'][1]-parent['bounds'][0]).days<10*365 or (child['bounds'][0]-parent['bounds'][1]).days>100*366:
                        hints.append({'person':link['right'],'kind':'parent_age_review','sources':[parent['citation'],child['citation'],link['citation']],'mentions':[parent['key'],child['key']]})
        return {'hints':hints,'uncompared':uncompared,'policy':'Only explicitly Gregorian book profiles or GREGORIAN-prefixed dates; approximate, slash and unsupported calendar dates are not diagnosed.'}

    def book_dictionary(self,a):
        page=self.engine.page(a['page']);doc=page['doc']
        scope=self.photo_book_docs(doc)
        if a.get('delete'):
            with self.db:
                for member in scope:self.db.execute('DELETE FROM book_words WHERE id=? AND doc=?',(a['delete'],member))
        if a.get('term'):
            if not a.get('verified'):raise ValueError('Підтвердьте перевірку слова за оригіналом.')
            term=a['term'].strip();kind=a.get('kind','name')
            if kind not in ['name','place','abbreviation'] or not term or not a.get('meaning','').strip():raise ValueError('Вкажіть слово, тип і пояснення.')
            values={'term':term,'kind':kind,'meaning':a['meaning'].strip(),'page':page['id'],'citation':self.source_card({'id':page['id']})['citation']}
            ident=uuid.uuid4().hex
            with self.db:self.db.execute('INSERT INTO book_words VALUES (?,?,?)',(ident,doc,json.dumps(values,ensure_ascii=False)))
        query=name_key(a.get('query',''))
        from difflib import SequenceMatcher
        result=[]
        for row in self.db.execute('SELECT * FROM book_words'):
            if row['doc'] not in scope:continue
            value=json.loads(row['data']);score=SequenceMatcher(None,query,name_key(value['term'])).ratio() if query else 1
            if not query or score>=.5 or query in name_key(value['term']):result.append(value|{'id':row['id'],'similarity':round(score,3)})
        return sorted(result,key=lambda r:-r['similarity'])[:100]
