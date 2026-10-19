"""Indexed library search, review queue, reversible edits and frozen evaluations."""
import hashlib
import json
from pathlib import Path
import re
import uuid
import contextlib
import sys

try:
    from .workbench import Workbench,compare
except ImportError:
    from workbench import Workbench,compare


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


class LibraryTools(Workbench):
    def __init__(self, engine):
        super().__init__(engine)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS review_resolutions(key TEXT PRIMARY KEY, signature TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS layout_templates(id TEXT PRIMARY KEY, doc TEXT, name TEXT, data TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS search_dirty(page TEXT PRIMARY KEY);
        CREATE VIRTUAL TABLE IF NOT EXISTS library_fts USING fts5(page UNINDEXED, source UNINDEXED, entity UNINDEXED, text, tokenize='unicode61 remove_diacritics 2');
        ''')
        # FTS UNINDEXED columns cannot provide a page lookup index. Keep rowids in
        # an ordinary indexed table, so replacing one page never scans all OCR.
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='search_fts_rows'").fetchone():
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                # Another foreground/background worker may have completed the
                # migration while this connection was waiting for the writer.
                if not self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='search_fts_rows'").fetchone():
                    self.db.execute('CREATE TABLE search_fts_rows(entry INTEGER PRIMARY KEY,page TEXT NOT NULL)')
                    self.db.execute('CREATE INDEX idx_search_fts_rows_page ON search_fts_rows(page)')
                    self.db.execute('INSERT INTO search_fts_rows SELECT rowid,page FROM library_fts')
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='library_pages_update_v4'").fetchone():
            with self.db:
                self.db.execute('INSERT OR IGNORE INTO search_dirty SELECT id FROM pages')
                for table,column in [('pages','id'),('records','page'),('line_corrections','page'),('annotations','page')]:
                    for event in ['insert','update','delete']:
                        for version in ['', '_v2', '_v3', '_v4']:self.db.execute(f'DROP TRIGGER IF EXISTS library_{table}_{event}{version}')
                        refs=['old','new'] if event=='update' else ['old' if event=='delete' else 'new']
                        body=' '.join(f'INSERT INTO search_dirty(page) SELECT {ref}.{column} WHERE NOT EXISTS (SELECT 1 FROM search_dirty WHERE page={ref}.{column});' for ref in refs)
                        columns=' OF text,lines' if table=='pages' and event=='update' else ''
                        self.db.execute(f'CREATE TRIGGER library_{table}_{event}_v4 AFTER {event}{columns} ON {table} BEGIN {body} END')

    def _index_insert(self,values):
        cursor=self.db.execute('INSERT INTO library_fts VALUES (?,?,?,?)',values)
        self.db.execute('INSERT INTO search_fts_rows(entry,page) VALUES (?,?)',(cursor.lastrowid,values[0]))

    def index_status(self,a):
        remaining=self.db.execute('SELECT COUNT(*) FROM search_dirty').fetchone()[0]
        total=self.db.execute('SELECT COUNT(*) FROM pages').fetchone()[0]
        return {'remaining':remaining,'total':total,'complete':remaining==0}

    def index_step(self,a):
        import time
        started=time.monotonic();limit=max(1,min(100,int(a.get('limit',25))));budget=max(10,min(1000,int(a.get('budget_ms',150))))
        processed=0
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            dirty_pages=self.db.execute('SELECT page FROM search_dirty ORDER BY rowid LIMIT ?',(limit,)).fetchall()
            for dirty in dirty_pages:
                page=dirty['page'];self.db.execute('DELETE FROM library_fts WHERE rowid IN (SELECT entry FROM search_fts_rows WHERE page=?)',(page,))
                self.db.execute('DELETE FROM search_fts_rows WHERE page=?',(page,))
                row=self.db.execute('SELECT text FROM pages WHERE id=?',(page,)).fetchone()
                if row:
                    self._index_insert((page,'ocr','',row['text']))
                    for r in self.db.execute('SELECT id,data FROM records WHERE page=?',(page,)):
                        text='\n'.join(value for value in json.loads(r['data']).values() if isinstance(value,str))
                        self._index_insert((page,'record',r['id'],text))
                    for r in self.db.execute('SELECT line,corrected FROM line_corrections WHERE page=?',(page,)):
                        self._index_insert((page,'correction',str(r['line']),r['corrected']))
                    for r in self.db.execute('SELECT id,data FROM annotations WHERE page=?',(page,)):
                        self._index_insert((page,'region',r['id'],json.loads(r['data']).get('text','')))
                self.db.execute('DELETE FROM search_dirty WHERE page=?',(page,));processed+=1
                if (time.monotonic()-started)*1000>=budget:break
        return self.index_status({})|{'processed':processed,'elapsed_ms':round((time.monotonic()-started)*1000,3)}

    def library_search(self, a):
        tokens=re.findall(r'[^\W_]+',str(a.get('query','')),re.UNICODE)
        coverage=dict(self.db.execute("SELECT COUNT(*) AS pages,SUM(status IN ('pending','running')) AS pending,SUM(status='error') AS errors FROM pages").fetchone())
        coverage={k:(v or 0) for k,v in coverage.items()}
        if not tokens: return {'rows':[],'limited':False,'coverage':coverage}
        query=' AND '.join('"'+t+'"*' for t in tokens[:12])
        # Direct callers retain a small bounded refresh; desktop search uses only background indexing.
        refresh=max(0,min(100,int(a.get('refresh_limit',25))))
        if refresh:self.index_step({'limit':refresh,'budget_ms':100})
        coverage.update(index_remaining=self.index_status({})['remaining'])
        limit=max(1,min(200,int(a.get('limit',100))))
        scope='';params=[query]
        if a.get('book'):
            if not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='photo_books'").fetchone():return {'rows':[],'limited':False,'coverage':coverage}
            scope=' AND p.id IN (SELECT page FROM book_items WHERE book=?)';params.append(a['book'])
        params.append(limit+1)
        rows=[dict(r) for r in self.db.execute('''SELECT library_fts.page,source,entity,
          snippet(library_fts,3,'⟦','⟧',' … ',28) AS snippet,d.name,p.num+1 AS number
          FROM library_fts JOIN pages p ON p.id=library_fts.page JOIN documents d ON d.id=p.doc
          WHERE library_fts MATCH ? AND NOT EXISTS (SELECT 1 FROM search_dirty dirty WHERE dirty.page=library_fts.page)'''+scope+' ORDER BY rank LIMIT ?',params)]
        return {'rows':rows[:limit],'limited':len(rows)>limit,'coverage':coverage}

    def review_queue(self, a):
        items=[]
        def add(key,page,kind,text,region=None,predictions=None,signature_extra=None):
            item={'key':key,'page':page['id'],'name':page['name'],'number':page['num']+1,'kind':kind,
                  'text':text,'region':region,'predictions':predictions or {}}
            item['signature']=digest([item,signature_extra])
            state=self.db.execute('SELECT signature FROM review_resolutions WHERE key=?',(key,)).fetchone()
            if not state or state['signature']!=item['signature']: items.append(item)
        for p in self.engine.list_pages({}):
            if p['status']=='error': add('page:'+p['id'],p,'error',p.get('error',''))
            for r in self.annotations({'id':p['id']}):
                if r['kind'] in ['damage','missing']:
                    add('region:'+r['id'],p,r['kind'],r.get('text',''),r['id'],signature_extra=r)
        seen=set()
        for run in self.db.execute('SELECT path FROM comparison_runs ORDER BY rowid DESC'):
            report=Path(run['path'])/'report.json'
            if not report.exists(): continue
            for row in json.loads(report.read_text(encoding='utf-8')).get('rows',[]):
                ident=row['id']
                if ident in seen: continue
                seen.add(ident)
                annotation=self.db.execute('SELECT page,data FROM annotations WHERE id=?',(ident,)).fetchone()
                if not annotation: continue
                region=json.loads(annotation['data'])
                # A comparison of old boundaries is no evidence about the revised crop.
                if region['rect']!=row.get('rect'): continue
                results=row.get('results',{})
                failed=any('error' in result for result in results.values())
                if row.get('disagreement') or failed:
                    p=self.engine.page(annotation['page'])
                    add('comparison:'+ident,p,'error' if failed else 'disagreement',region.get('text',''),ident,results,region)
        return items

    def review_resolve(self,a):
        item=next((r for r in self.review_queue({}) if r['key']==a['key']),None)
        if not item or item['signature']!=a['signature']: raise ValueError('Результат змінився. Оновіть список.')
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO review_resolutions(key,signature) VALUES (?,?)',(item['key'],item['signature']))
        return {'saved':True}

    def review_context(self,a):
        rows=self.annotations({'id':a['id']})
        region=next((r for r in rows if r['id']==a.get('region')),None)
        if not region: return self.engine.render({'id':a['id'],'whole':True})
        image=self.whole_image(a['id']); x,y,w,h=region['rect']
        left=max(0,x-.05); top=max(0,y-2*h); right=min(1,x+w+.05); bottom=min(1,y+3*h)
        cropped=image.crop((round(left*image.width),round(top*image.height),round(right*image.width),round(bottom*image.height)))
        path=self.engine.root/'cache'/('context-'+uuid.uuid4().hex+'.png'); cropped.save(path)
        return {'path':str(path),'focus':[(x-left)/(right-left),(y-top)/(bottom-top),w/(right-left),h/(bottom-top)]}

    def history_list(self,a):
        page=self.engine.page(a['id']); entries=[]
        def add(kind,entity,revision,created,before,after):
            for version,snapshot in [('before',before),('after',after)]:
                if snapshot is not None:
                    entries.append({'kind':kind,'entity':str(entity),'revision':revision,'version':version,'created':created,
                                    'snapshot':json.loads(snapshot),'expected':self.current_digest(kind,str(entity),page['id'])})
        for r in self.db.execute('SELECT c.* FROM corrections c JOIN records r ON r.id=c.record WHERE r.page=?',(page['id'],)):
            add('record',r['record'],r['id'],r['created'],r['before'],r['after'])
        # Deleted region revisions retain page information in either neighboring snapshot.
        for r in self.db.execute('SELECT * FROM annotation_history'):
            snapshots=[json.loads(v) for v in [r['before'],r['after']] if v]
            current=self.db.execute('SELECT page FROM annotations WHERE id=?',(r['annotation'],)).fetchone()
            if (current and current['page']==page['id']) or any(v.get('_page')==page['id'] for v in snapshots):
                add('region',r['annotation'],r['id'],r['created'],r['before'],r['after'])
        for r in self.db.execute('SELECT * FROM line_history WHERE page=?',(page['id'],)):
            add('line',r['line'],r['id'],r['created'],r['before'],r['after'])
        for r in self.db.execute('SELECT * FROM recognition_history WHERE page=?',(page['id'],)):
            add('ocr',page['id'],r['id'],r['created'],None,json.dumps({'text':r['text']}))
        return sorted(entries,key=lambda r:(r['created'],r['revision']),reverse=True)

    def current_digest(self,kind,entity,page):
        if kind=='record': r=self.db.execute('SELECT data FROM records WHERE id=? AND page=?',(entity,page)).fetchone()
        elif kind=='region': r=self.db.execute('SELECT data FROM annotations WHERE id=? AND page=?',(entity,page)).fetchone()
        elif kind=='line':
            r=self.db.execute('SELECT corrected,verified FROM line_corrections WHERE page=? AND line=?',(page,int(entity))).fetchone()
            return digest(dict(r) if r else None)
        else: return digest(self.engine.page(page)['text'])
        return digest(json.loads(r['data']) if r else None)

    def history_restore(self,a):
        # Select the persisted revision, never accept arbitrary client snapshot contents.
        entry=next((r for r in self.history_list({'id':a['id']}) if all(r[k]==a[k] for k in ['kind','entity','revision','version'])),None)
        if not entry or entry['expected']!=a['expected']: raise ValueError('Результат змінився. Оновіть список.')
        kind=entry['kind']; snapshot=entry['snapshot']; entity=entry['entity']; page=a['id']
        if kind=='record': return self.engine.save_record(snapshot|{'page':page,'id':entity})
        if kind=='region': return self.save_annotation({'page':page,'annotation':entity,'data':snapshot})
        if kind=='line': return self.engine.save_line({'id':page,'line':int(entity)}|snapshot)
        if self.db.execute('SELECT 1 FROM line_corrections WHERE page=?',(page,)).fetchone():
            raise ValueError('Сторінка має виправлені рядки. Повторне OCR заблоковано для збереження прив’язки.')
        p=self.engine.page(page)
        with self.db:
            self.db.execute('INSERT INTO recognition_history(page,text,lines,engine) VALUES (?,?,?,?)',(page,p['text'],p['lines'],p['engine']))
            self.db.execute("UPDATE pages SET text=?,lines='[]',status='done',engine='Restored text',error='' WHERE id=?",(snapshot['text'],page))
        return {'saved':True}

    def template_save(self,a):
        page=self.engine.page(a['id']); columns=[r for r in self.annotations({'id':page['id']}) if r['kind']=='column']
        if not columns: raise ValueError('Спочатку розмітьте колонки сторінки.')
        ident=uuid.uuid4().hex
        data=[{k:r.get(k,'') for k in ['rect','label','field']} for r in columns]
        with self.db: self.db.execute('INSERT INTO layout_templates(id,doc,name,data) VALUES (?,?,?,?)',(ident,page['doc'],str(a.get('name','')).strip() or page['name'],json.dumps(data,ensure_ascii=False)))
        return {'id':ident}

    def template_list(self,a):
        page=self.engine.page(a['id'])
        return [dict(r) for r in self.db.execute('SELECT id,name,created FROM layout_templates WHERE doc=? ORDER BY rowid DESC',(page['doc'],))]

    def template_apply(self,a):
        page=self.engine.page(a['id']); template=self.db.execute('SELECT * FROM layout_templates WHERE id=? AND doc=?',(a['template'],page['doc'])).fetchone()
        if not template: raise ValueError('Шаблон належить іншій книзі.')
        # Add only on selected pages; never replace handwritten adjustments.
        targets=list(dict.fromkeys(a.get('pages',[page['id']])))
        if not targets: raise ValueError('Виберіть сторінки для шаблону.')
        for target in targets:
            if self.engine.page(target)['doc']!=page['doc']: raise ValueError('Шаблон належить іншій книзі.')
        added=skipped=0
        with self.db:
            for target in targets:
                if any(r['kind']=='column' for r in self.annotations({'id':target})): skipped+=1; continue
                for col in json.loads(template['data']):
                    self.save_annotation({'page':target,'data':col|{'kind':'column','template':template['id'],'text':'','verified':False}})
                    added+=1
        return {'added':added,'skipped':skipped}

    def benchmark_inventory(self,a):
        rows=[]
        verified_counts={row['doc']:row['n'] for row in self.db.execute("SELECT p.doc,COUNT(*) AS n FROM annotations a JOIN pages p ON p.id=a.page WHERE json_extract(a.data,'$.kind')='line' AND json_extract(a.data,'$.verified')=1 GROUP BY p.doc")}
        for doc in self.db.execute('SELECT * FROM documents ORDER BY name'):
            profile=self.db.execute('SELECT data FROM book_profiles WHERE doc=?',(doc['id'],)).fetchone()
            values=json.loads(profile['data']) if profile else {}
            rows.append({'doc':doc['id'],'name':doc['name'],'languages':values.get('languages',''),'years':values.get('years',''),
                         'script':values.get('script',''),'split':values.get('split',''),'verified_lines':verified_counts.get(doc['id'],0)})
        return rows

    def benchmark_freeze(self,a):
        inventory=self.benchmark_inventory({})
        if not any(r['split']=='test' and r['verified_lines'] for r in inventory):
            raise ValueError('Позначте окремі книги як тестові та перевірте текст їхніх рядків.')
        folder=self.engine.root/'results'/('benchmark-'+uuid.uuid4().hex)
        result=self.dataset_explicit({'path':str(folder)})
        if not result['test']: raise ValueError('Позначте окремі книги як тестові та перевірте текст їхніх рядків.')
        (folder/'books.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf-8')
        manifest=folder/'manifest.json'
        (folder/'freeze.json').write_text(json.dumps({'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),
           'policy':'Verified manual lines only; book/source-family splits; unresolved and damaged lines excluded. No automatic ground truth.'},indent=2),encoding='utf-8')
        return result|{'path':str(folder)}

    def benchmark_compare(self,a):
        source=Path(a['path']).resolve(); manifest=source/'manifest.json'
        frozen=json.loads((source/'freeze.json').read_text(encoding='utf-8'))
        if hashlib.sha256(manifest.read_bytes()).hexdigest()!=frozen['manifest_sha256']:
            raise ValueError('Збережений набір змінено. Створіть новий знімок.')
        selected=[r for r in json.loads(manifest.read_text(encoding='utf-8')) if r['split']=='test']
        if not selected: raise ValueError('Позначте окремі книги як тестові та перевірте текст їхніх рядків.')
        self.check_known_training_overlap([({'doc':r['document'],'source_sha256':r['source_sha256']},r) for r in selected],a['models'])
        folder=self.engine.root/'results'/('benchmark-comparison-'+uuid.uuid4().hex); folder.mkdir()
        cases=[]
        for i,row in enumerate(selected):
            image=(source/row['image']).resolve()
            if image.parent!=source or hashlib.sha256(image.read_bytes()).hexdigest()!=row['image_sha256']:
                raise ValueError('Збережений набір змінено. Створіть новий знімок.')
            name=str(i)+'.png'; (folder/name).write_bytes(image.read_bytes())
            cases.append(row|{'id':image.stem,'image':name,'reference':row['text'],'source':row['document']+':'+str(row['page'])})
        target=folder/'manifest.json'; target.write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
        with contextlib.redirect_stdout(sys.stderr): report=compare(target,a['models'],folder)
        (folder/'dataset-source.json').write_text(json.dumps({'path':str(source),'manifest_sha256':frozen['manifest_sha256']},indent=2),encoding='utf-8')
        return {'rows':report['rows'],'models':report['models'],'paired':report.get('paired_comparison_first_two'),'by_book':report.get('by_book',[]),'path':str(folder/'comparison.html')}
