"""Book productivity views over existing evidence, profiles and saved results.

This module never links people, invents semantic fields, runs OCR in reports,
or overwrites source photos. Review priorities are explicit human decisions.
"""
import hashlib
import json
import math
from pathlib import Path
import re
import uuid
try:
    from .books import BookTools
    from .library import digest
    from .workbench import name_key
except ImportError:
    from books import BookTools
    from library import digest
    from workbench import name_key


class HubTools(BookTools):
    def __init__(self,engine):
        super().__init__(engine)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS hub_review_actions(key TEXT PRIMARY KEY,signature TEXT,data TEXT);
        CREATE TABLE IF NOT EXISTS hub_review_history(id INTEGER PRIMARY KEY,key TEXT,before TEXT,after TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')

    def _scope(self,a):
        group=None
        if a.get('book'):group=self.book_get({'book':a['book']})
        elif a.get('id'):
            page=self.engine.page(a['id']);found=self.photo_book(page['doc'])
            if found:group=self.book_get({'book':found['id']})
        query='SELECT p.id,p.doc,p.num,p.status,p.error,d.name,d.sha FROM pages p JOIN documents d ON d.id=p.doc'
        if group:
            query+=' WHERE p.id IN (SELECT page FROM book_items WHERE book=?)';params=(group['id'],)
        elif a.get('id'):
            query+=' WHERE p.doc=?';params=(self.engine.page(a['id'])['doc'],)
        else:params=()
        rows=[dict(r) for r in self.db.execute(query+' ORDER BY p.num,p.rowid',params)]
        return rows,group

    def hub_photo(self,a):
        mode=a.get('mode','contrast')
        if mode not in ['original','contrast','binary','lighting']:raise ValueError('Невідомий режим обробки.')
        angle=float(a.get('angle',0))
        if not math.isfinite(angle) or not -180<=angle<=180:raise ValueError('Неправильний кут повороту.')
        # Existing rendered preview pipeline retains immutable original mapping.
        before=self.engine.render({'id':a['id'],'whole':True,'preprocess':'original'})
        after=self.engine.render({'id':a['id'],'whole':True,'preprocess':mode})
        if angle:
            from PIL import Image
            with Image.open(after['path']) as image:
                preview=image.rotate(angle,resample=Image.Resampling.BICUBIC,expand=True,fillcolor='white')
                path=self.engine.root/'cache'/('hub-preview-'+uuid.uuid4().hex+'.png');preview.save(path)
                after={'path':str(path),'width':preview.width,'height':preview.height}
        return {'original':before,'processed':after,'preview_only':True,'mode':mode,'angle':angle,
                'policy':'Preview copies only; OCR, annotations and source files are unchanged.'}

    def _field(self,region,page):
        fields={'person','date','house','related1','related2'}
        if region.get('field') in fields:return region['field'],'annotation'
        if region.get('parent'):
            row=self.db.execute('SELECT data FROM annotations WHERE id=? AND page=?',(region['parent'],page)).fetchone()
            parent=json.loads(row['data']) if row else {}
            if parent.get('field') in fields:return parent['field'],'parent_column'
        return 'unknown','unbound'

    def hub_queue(self,a):
        pages,_=self._scope(a);scope={p['id']:p for p in pages};docs={p['doc'] for p in pages};items=[];seen=set()
        limit=max(1,min(500,int(a.get('limit',200))))
        def add(key,page,region,results,old_rect=None,extra=None,error=''):
            if page not in scope:return
            info=scope[page];field,binding=self._field(region,page) if region else ('unknown','unbound')
            stale=bool(old_rect is not None and (not region or region.get('rect')!=old_rect))
            payload={'key':key,'page':page,'annotation':region.get('id') if region else None,'record':region.get('record') if region else None,
                     'name':info['name'],'number':info['num']+1,'field':field,'field_binding':binding,'results':results,
                     'error':error,'stale':stale,'rect':old_rect or region.get('rect') if region else old_rect,'source':extra or ''}
            signature=digest({'source_sha256':info['sha'],'region':region,'comparison':payload})
            action=self.db.execute('SELECT * FROM hub_review_actions WHERE key=?',(key,)).fetchone();saved=json.loads(action['data']) if action and action['signature']==signature else {}
            payload.update(signature=signature,priority=saved.get('priority',0),note=saved.get('note',''),done=saved.get('done',False),action_stale=bool(action and not saved))
            if saved.get('field') in ['person','date','house','related1','related2','unknown']:
                payload.update(field=saved['field'],field_binding='human_label')
            if not a.get('include_done') and payload['done']:return
            if a.get('field') and payload['field']!=a['field']:return
            items.append(payload)
        # Only inspect persisted reports; never launch recognition to populate a queue.
        runs=list(self.db.execute('SELECT * FROM comparison_runs WHERE doc IN (SELECT DISTINCT p.doc FROM pages p WHERE p.id IN ('+','.join('?' for _ in scope)+')) ORDER BY rowid DESC LIMIT 100',tuple(scope))) if scope else []
        for run in runs:
            if run['doc'] not in docs:continue
            folder=Path(run['path']).resolve();report=folder/'report.json'
            if not folder.is_relative_to(self.engine.root/'results') or not report.is_file() or report.stat().st_size>20*1024*1024:continue
            try:rows=json.loads(report.read_text('utf-8')).get('rows',[])
            except (ValueError,OSError):continue
            for result in rows:
                ident=result.get('id')
                if ident in seen:continue
                seen.add(ident)
                raw=self.db.execute('SELECT page,data FROM annotations WHERE id=?',(ident,)).fetchone()
                if not raw:continue
                region=json.loads(raw['data'])|{'id':ident};results=result.get('results',{})
                failed=any('error' in r for r in results.values())
                alternatives={str(r['text']).strip() for r in results.values() if 'text' in r}
                if result.get('disagreement') or failed or len(alternatives)>1:
                    add('comparison:'+ident,raw['page'],region,results,result.get('rect'),run['id'])
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='agent_jobs'").fetchone():
            for row in self.db.execute('SELECT id,page,data FROM agent_jobs WHERE page IN ('+','.join('?' for _ in scope)+') ORDER BY rowid DESC LIMIT 500',tuple(scope)) if scope else []:
                if row['page'] not in scope:continue
                job=json.loads(row['data'])
                if job.get('state')!='failed' or job.get('annotation') in seen:continue
                ident=job.get('annotation');raw=self.db.execute('SELECT data FROM annotations WHERE id=? AND page=?',(ident,row['page'])).fetchone();region=(json.loads(raw['data'])|{'id':ident}) if raw else {}
                old=job.get('stages',{}).get('layout',{}).get('region',{})
                add('agent:'+row['id'],row['page'],region,{},old.get('rect'),row['id'],job.get('error',''))
                if items and items[-1]['key']=='agent:'+row['id'] and digest({'source_sha256':scope[row['page']]['sha'],'region':region})!=job.get('snapshot'):items[-1]['stale']=True
        items.sort(key=lambda r:(-r['priority'],r['stale'],r['name'],r['number'],r['key']))
        return {'rows':items[:limit],'limited':len(items)>limit,'reports_considered':len(runs),'policy':'Fields come only from saved annotation bindings or explicit human labels. No inferred names/dates/house numbers.'}

    def hub_review(self,a):
        current=next((r for r in self.hub_queue({'id':a['id'],'include_done':True,'limit':500})['rows'] if r['key']==a['key']),None)
        if not current or current['signature']!=a.get('signature') or current['stale']:raise ValueError('Результат або розмітка змінилися. Оновіть порівняння.')
        if type(a.get('priority')) is not int or a['priority'] not in range(4):raise ValueError('Виберіть пріоритет від 0 до 3.')
        field=a.get('field','unknown')
        if field not in ['person','date','house','related1','related2','unknown']:raise ValueError('Неправильне поле перевірки.')
        note=str(a.get('note','')).strip()
        if not note:raise ValueError('Поясніть пріоритет або рішення перевірки.')
        values={'priority':a['priority'],'field':field,'note':note,'done':a.get('done') is True}
        old=self.db.execute('SELECT data FROM hub_review_actions WHERE key=?',(a['key'],)).fetchone()
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO hub_review_actions VALUES (?,?,?)',(a['key'],current['signature'],json.dumps(values,ensure_ascii=False)))
            self.db.execute('INSERT INTO hub_review_history(key,before,after) VALUES (?,?,?)',(a['key'],old['data'] if old else None,json.dumps(values,ensure_ascii=False)))
        return {'saved':True,'source_changed':False}

    def hub_family_search(self,a):
        queries={k:str(a.get(k,'')).strip() for k in ['person','place','house','year_from','year_to','related1','related2']}
        if not any(queries.values()):raise ValueError('Вкажіть хоча б одну ознаку для пошуку.')
        if any(v and not re.fullmatch(r'\d{4}',v) for k,v in queries.items() if k.startswith('year_')):raise ValueError('Вкажіть рік чотирма цифрами.')
        scope,group=self._scope(a);allowed={r['id'] for r in scope} if a.get('current_book') else None
        options={k:v for k,v in queries.items() if k not in ['related1','related2'] and v}
        include=a.get('include_differences') is True
        if include:
            options={k:options[k] for k in next(([key] for key in ['person','place','house'] if key in options),[])}
        options['limit']=500
        if a.get('current_book') and group:options['book']=group['id']
        found=self.record_search(options);rows=[]
        years={k:int(v) for k,v in queries.items() if k.startswith('year_') and v}
        if years.get('year_from',0)>years.get('year_to',9999):raise ValueError('Неправильний діапазон років.')
        for row in found['rows']:
            if allowed is not None and row['page'] not in allowed:continue
            values=row['data'];explanation=[]
            for key in ['person','place','house','related1','related2']:
                if not queries[key]:continue
                actual=str(values.get(key,''));query=queries[key];matches=name_key(query)==name_key(actual) if key=='house' else name_key(query) in name_key(actual)
                explanation.append({'field':key,'query':query,'actual':actual,'status':'match' if matches else 'missing' if not actual else 'different'})
            if years:
                actual=str(values.get('date',''));found_years=re.findall(r'(?<!\d)(\d{4})(?!\d)',actual)
                matches=len(found_years)==1 and years.get('year_from',0)<=int(found_years[0])<=years.get('year_to',9999)
                explanation.append({'field':'date','query':queries['year_from']+'…'+queries['year_to'],'actual':actual,'status':'match' if matches else 'uncertain' if len(found_years)!=1 else 'different'})
            differences=sum(e['status']!='match' for e in explanation)
            if differences and not include:continue
            rows.append(row|{'explanation':explanation,'differences':differences,'matched':len(explanation)-differences,'automatic_link':False})
        rows.sort(key=lambda r:(r['differences'],-r['matched'],r['name'],r['number']))
        return {'rows':rows[:200],'limited':found['limited'] or len(rows)>200,'policy':'Saved fields only. Relative1/2 retain the record meaning; matches never create people or family links.'}

    def hub_gaps(self,a):
        pages,group=self._scope(a);by_id={p['id']:p for p in pages};scope=set(by_id)
        counts={r['page']:dict(r) for r in self.db.execute("SELECT page,COUNT(*) AS records,SUM(CASE WHEN json_extract(data,'$.verified')=1 THEN 0 ELSE 1 END) AS unverified FROM records GROUP BY page") if r['page'] in scope}
        gaps=[{'kind':'missing_folio','position':i['position']+1,'label':i['label'],'note':i['note'],'page':None} for i in group['items'] if not i['page']] if group else []
        issues=gaps+[{'kind':p['status'],'page':p['id'],'name':p['name'],'number':p['num']+1,'error':p['error']} for p in pages if p['status']!='done']
        fingerprints={};decisions={};duplicates=[]
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='page_fingerprints'").fetchone():
            for row in self.db.execute('SELECT * FROM page_fingerprints'):
                if row['page'] not in scope or row['sha']!=by_id[row['page']]['sha']:continue
                full=next((r['hash'] for r in json.loads(row['data']) if r['rect']==[0,0,1,1]),None)
                if full:fingerprints[row['page']]=int(full,16)
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='duplicate_decisions'").fetchone():
            for row in self.db.execute('SELECT * FROM duplicate_decisions'):
                pair=json.loads(row['pair']);value=json.loads(row['data'])
                if len(pair)==2 and all(p in scope for p in pair):decisions[tuple(sorted(pair))]=value
        selected=list(fingerprints)[:2000];seen=set()
        for i,left in enumerate(selected):
            for right in selected[i+1:]:
                similarity=1-(fingerprints[left]^fingerprints[right]).bit_count()/64
                if similarity<.94:continue
                pair=tuple(sorted([left,right]));seen.add(pair);decision=decisions.get(pair)
                if decision and decision['status']=='rejected':continue
                duplicates.append({'left':left,'right':right,'similarity':round(similarity,3),'status':decision['status'] if decision else 'candidate','note':decision.get('note','') if decision else ''})
        for pair,decision in decisions.items():
            if pair not in seen and decision['status']!='rejected':duplicates.append({'left':pair[0],'right':pair[1],'similarity':None,'status':decision['status'],'note':decision.get('note','')})
        for row in duplicates:
            row.update(left_name=by_id[row['left']]['name'],left_number=by_id[row['left']]['num']+1,right_name=by_id[row['right']]['name'],right_number=by_id[row['right']]['num']+1)
        return {'book':group['name'] if group else pages[0]['name'] if pages else '',
                'counts':{'pages':len(pages),'explicit_gaps':len(gaps),'pending':sum(p['status']=='pending' for p in pages),'running':sum(p['status']=='running' for p in pages),'errors':sum(p['status']=='error' for p in pages),'recognized':sum(p['status']=='done' for p in pages),'records':sum(r['records'] for r in counts.values()),'unverified_records':sum(r['unverified'] for r in counts.values()),'pages_without_records':len(pages)-len(counts),'duplicate_candidates':sum(r['status']=='candidate' for r in duplicates),'confirmed_duplicates':sum(r['status']=='confirmed_full' for r in duplicates),'related_fragments':sum(r['status']=='related_fragment' for r in duplicates),'indexed_pages':len(fingerprints)},
                'issues':issues,'duplicates':duplicates[:200],'duplicates_limited':len(fingerprints)>2000 or len(duplicates)>200,
                'policy':'Explicit missing folios only; no missing page is inferred. Existing full-page fingerprints within this book only; no OCR or image indexing is run. Empty/unindexed pages remain unknown.'}

    def hub_profile(self,a):
        page=self.engine.page(a['id']);profile=self.book_profile({'id':a['id']});group=self.photo_book(page['doc']);docs=self.photo_book_docs(page['doc'])
        templates=self.template_list({'id':a['id']});words=[]
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='book_words'").fetchone():
            words=[json.loads(r['data'])|{'id':r['id']} for r in self.db.execute('SELECT * FROM book_words') if r['doc'] in docs]
        columns=self.book_template({'book':group['id']}) if group else []
        existing=sum(r['kind']=='column' for r in self.annotations({'id':a['id']}))
        return {'profile':profile,'book':{'id':group['id'],'name':group['name']} if group else None,'templates':templates,'columns':columns,'dictionary':words,'current_page_columns':existing,'apply_policy':'Existing page columns are preserved. Apply saved templates explicitly to selected pages; edit exceptions in the layout workbench.'}
