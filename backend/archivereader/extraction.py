"""Conservative, source-bound proposals from explicit labels; never automatic facts."""
import hashlib
import json
import re
import uuid
try:
    from .engine import FIELDS,KINDS
    from .sources import SourceTools
except ImportError:
    from engine import FIELDS,KINDS
    from sources import SourceTools


class ExtractionTools(SourceTools):
    def __init__(self,engine):
        super().__init__(engine)
        self.db.execute('CREATE TABLE IF NOT EXISTS field_proposal_runs(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
        self.db.commit()

    def source(self,a):
        page=self.engine.page(a['page'])
        if a.get('record'):
            row=self.db.execute('SELECT data,page FROM records WHERE id=?',(a['record'],)).fetchone()
            if not row or row['page']!=page['id']: raise ValueError('Запис-доказ не знайдено.')
            values=json.loads(row['data']);text=values.get('text','');signature=hashlib.sha256(row['data'].encode('utf8')).hexdigest()
        else:
            values={};text=page['text'];signature=hashlib.sha256(text.encode('utf8')).hexdigest()
        return text,values,signature

    def field_propose(self,a):
        text,values,signature=self.source(a);candidates=[]
        rules={
            'date':r'(?<!\d)(\d{4}-\d{2}-\d{2}|\d{1,2}[./-]\d{1,2}[./-]\d{4})(?!\d)',
            'house':r'(?:domus|nr\.?\s*domu|номер\s*будинку|číslo\s*domu|№)\s*[:.]?\s*(\d+[a-zа-я]?)',
            'age':r'(?:aetatis|вік|wiek|věk|age)\s*[:.]?\s*(\d+)',
            'person':r'(?:nomen|imię|jméno|ім[’\x27]я)\s*:\s*([^;\n]+)',
            'related1':r'(?:pater|ojciec|батько|otec)\s*:\s*([^;\n]+)',
            'related2':r'(?:mater|matka|мати)\s*:\s*([^;\n]+)',
            'place':r'(?:locus|miejsce|místo|населений\s*пункт|місце)\s*:\s*([^;\n]+)',
        }
        for field,rule in rules.items():
            for match in re.finditer(rule,text,re.IGNORECASE):
                start,end=match.span(1);value=match[1].strip()
                candidates.append({'field':field,'value':value,'start':start,'end':end,'evidence':text[max(0,start-60):min(len(text),end+60)],'existing':values.get(field,'')})
        ident=uuid.uuid4().hex
        payload={'id':ident,'page':a['page'],'record':a.get('record'),'signature':signature,'text':text,'candidates':candidates,'citation':self.source_card({'id':a['page']})['citation']}
        with self.db:self.db.execute('INSERT INTO field_proposal_runs VALUES (?,?)',(ident,json.dumps(payload,ensure_ascii=False)))
        return payload

    def field_apply(self,a):
        row=self.db.execute('SELECT data FROM field_proposal_runs WHERE id=?',(a['run'],)).fetchone()
        if not row: raise ValueError('Пропозиції не знайдено.')
        run=json.loads(row['data'])
        if run.get('applied_record'): raise ValueError('Пропозиції вже збережено. Створіть нові.')
        _,values,signature=self.source(run)
        if signature!=run['signature']: raise ValueError('Запис змінився. Оновіть можливі збіги.')
        indices=a.get('selected',[])
        if not indices or any(type(i)!=int or i<0 or i>=len(run['candidates']) for i in indices): raise ValueError('Виберіть пропозиції для збереження.')
        selected=[run['candidates'][i] for i in set(indices)]
        if len({r['field'] for r in selected})!=len(selected): raise ValueError('Оберіть лише одне значення для кожного поля.')
        for candidate in selected:
            field=candidate['field']
            if values.get(field) and values[field]!=candidate['value'] and not a.get('replace'): raise ValueError('Поле вже заповнене. Дозвольте заміну явно.')
            values[field]=candidate['value']
        values.update({'page':run['page'],'text':run['text'],'kind':values.get('kind') or KINDS[0],'verified':False})
        if run.get('record'):values['id']=run['record']
        result=self.engine.save_record(values)
        # Retain exact character evidence in the proposal run and link it to the applied record.
        run['applied_record']=result['id'];run['selected']=indices
        with self.db:self.db.execute('UPDATE field_proposal_runs SET data=? WHERE id=?',(json.dumps(run,ensure_ascii=False),run['id']))
        return result
