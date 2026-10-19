"""Ordered photo books, research tasks and structured record search.

Book positions are separate from immutable source frame numbers.
"""
import io
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
try:
    from .library import LibraryTools
    from .workbench import validate_rect, name_key
except ImportError:
    from library import LibraryTools
    from workbench import validate_rect, name_key


class BookTools(LibraryTools):
    def __init__(self, engine):
        super().__init__(engine)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS photo_books(id TEXT PRIMARY KEY,name TEXT NOT NULL,data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS book_items(id TEXT PRIMARY KEY,book TEXT REFERENCES photo_books(id),position INTEGER,page TEXT REFERENCES pages(id),label TEXT,note TEXT);
        CREATE TABLE IF NOT EXISTS research_tasks(id TEXT PRIMARY KEY,page TEXT REFERENCES pages(id),data TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')
        try:
            from .schema_indexes import ensure_indexes
        except ImportError:from schema_indexes import ensure_indexes
        ensure_indexes(self.db)

    def books(self, a):
        return [dict(r) for r in self.db.execute('SELECT b.id,b.name,COUNT(i.id) AS count FROM photo_books b LEFT JOIN book_items i ON i.book=b.id GROUP BY b.id ORDER BY b.rowid DESC')]

    def book_get(self, a):
        book=self.db.execute('SELECT * FROM photo_books WHERE id=?',(a['book'],)).fetchone()
        if not book:raise ValueError('Книгу не знайдено.')
        items=[dict(r) for r in self.db.execute('''SELECT i.*,d.name AS source,p.num+1 AS source_number,p.status
          FROM book_items i LEFT JOIN pages p ON p.id=i.page LEFT JOIN documents d ON d.id=p.doc
          WHERE i.book=? ORDER BY i.position,i.rowid''',(a['book'],))]
        return dict(book)|{'data':json.loads(book['data']),'items':items}

    def book_save(self, a):
        ident=a.get('book') or uuid.uuid4().hex
        name=str(a.get('name','')).strip()
        if not name:raise ValueError('Вкажіть назву книги.')
        old=self.db.execute('SELECT data FROM photo_books WHERE id=?',(ident,)).fetchone()
        items=a.get('items',[])
        if not items:raise ValueError('Додайте сторінки книги.')
        seen=set(); encoded=[]
        for pos,item in enumerate(items):
            page=item.get('page') or None
            if page:
                self.engine.page(page)
                if page in seen:raise ValueError('Сторінка вже є в цій книзі.')
                seen.add(page)
            label=str(item.get('label','')).strip()
            if not page and not label:raise ValueError('Опишіть пропущений аркуш.')
            encoded.append((uuid.uuid4().hex,ident,pos,page,label,str(item.get('note',''))))
        data=a.get('data',json.loads(old['data']) if old else {})
        docs={self.engine.page(page)['doc'] for page in seen}
        for doc in docs:
            existing=self.photo_book(doc)
            if existing and existing['id']!=ident:raise ValueError('Фото вже належить іншій збірці книги.')
        roles={json.loads(r['data']).get('split') for r in self.db.execute('SELECT * FROM book_profiles') if r['doc'] in docs}
        roles.discard('');roles.discard(None)
        if data.get('profile',{}).get('split'):roles.add(data['profile']['split'])
        if len(roles)>1:raise ValueError('Не можна змішувати навчальні й тестові книги.')
        if not old:
            profiles=[json.loads(r['data']) for r in self.db.execute('SELECT * FROM book_profiles') if r['doc'] in docs]
            if roles and profiles:data=dict(data)|{'profile':next(p for p in profiles if p.get('split') in roles)}
        with self.db:
            self.db.execute('INSERT INTO photo_books VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,data=excluded.data',(ident,name,json.dumps(data,ensure_ascii=False)))
            self.db.execute('DELETE FROM book_items WHERE book=?',(ident,))
            self.db.executemany('INSERT INTO book_items VALUES (?,?,?,?,?,?)',encoded)
            if 'profile' in data:
                for doc in docs:self.db.execute('INSERT OR REPLACE INTO book_profiles VALUES (?,?)',(doc,json.dumps(data['profile'],ensure_ascii=False)))
        return self.book_get({'book':ident})

    def book_import_folder(self,a):
        folder=Path(a['path']).resolve()
        files=[p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in {'.jpg','.jpeg','.png','.tif','.tiff','.webp','.bmp'}]
        def natural(p):return [(1,int(t)) if t.isdigit() else (0,t.casefold()) for t in re.split('(\\d+)',p.name)]
        files.sort(key=natural)
        if not files:raise ValueError('У папці немає підтримуваних фото.')
        items=[];failures=[];seen=set()
        for path in files:
            try:
                doc=self.engine.import_file({'path':str(path)})['id']
                for p in self.db.execute('SELECT id FROM pages WHERE doc=? ORDER BY num',(doc,)):
                    if p['id'] not in seen:items.append({'page':p['id'],'label':path.name});seen.add(p['id'])
            except Exception as exc:failures.append({'file':path.name,'error':str(exc)})
        if not items:raise ValueError('Не вдалося імпортувати фото: '+json.dumps(failures,ensure_ascii=False))
        return self.book_save({'name':a.get('name') or folder.name,'items':items})|{'failures':failures}

    def book_index(self,a):
        book=self.book_get(a); items=book['items']
        return {'pages':sum(bool(i['page']) for i in items),'gaps':sum(not i['page'] for i in items),
                'recognized':sum(i['status']=='done' for i in items),
                'pending':[i['page'] for i in items if i['page'] and i['status']!='done'],
                'errors':[i['page'] for i in items if i['status']=='error']}

    def record_search(self,a):
        filters={k:str(a.get(k,'')).strip() for k in ['person','place','house','year_from','year_to']}
        years={k:int(v) for k,v in filters.items() if k.startswith('year_') and v}
        if years.get('year_from',0)>years.get('year_to',9999):raise ValueError('Неправильний діапазон років.')
        book_pages=None
        if a.get('book'):book_pages={i['page'] for i in self.book_get(a)['items'] if i['page']}
        rows=[];limit=max(1,min(500,int(a.get('limit',200))))
        for row in self.db.execute('SELECT r.*,d.name,p.num+1 AS number FROM records r JOIN pages p ON p.id=r.page JOIN documents d ON d.id=p.doc ORDER BY d.name,p.num'):
            if book_pages is not None and row['page'] not in book_pages:continue
            values=json.loads(row['data'])
            if any(name_key(v) not in name_key(str(values.get(k,''))) for k,v in filters.items() if k in ['person','place'] and v):continue
            if filters['house'] and name_key(filters['house'])!=name_key(str(values.get('house',''))):continue
            date=str(values.get('date','')); found=re.findall(r'(?<!\d)(\d{4})(?!\d)',date)
            # A range or ambiguous date is not silently converted into an exact year.
            if years and (len(found)!=1 or not years.get('year_from',0)<=int(found[0])<=years.get('year_to',9999)):continue
            rows.append(dict(row)|{'data':values})
            if len(rows)>limit:break
        return {'rows':rows[:limit],'limited':len(rows)>limit,'policy':'Saved record fields; uncertain/range years excluded when filtering by year.'}

    def research_task(self,a):
        if 'data' in a:
            self.engine.page(a['page']);data=dict(a['data'])
            if data.get('rect') is not None:data['rect']=validate_rect(data['rect'])
            if not str(data.get('text','')).strip():raise ValueError('Вкажіть завдання.')
            ident=a.get('id') or uuid.uuid4().hex
            old=self.db.execute('SELECT page FROM research_tasks WHERE id=?',(ident,)).fetchone()
            if old and old['page']!=a['page']:raise ValueError('Завдання належить іншій сторінці.')
            with self.db:self.db.execute('INSERT INTO research_tasks(id,page,data) VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(ident,a['page'],json.dumps(data,ensure_ascii=False)))
        rows=[dict(r)|{'data':json.loads(r['data'])} for r in self.db.execute('SELECT t.*,d.name,p.num+1 AS number FROM research_tasks t JOIN pages p ON p.id=t.page JOIN documents d ON d.id=p.doc ORDER BY t.rowid DESC')]
        return [r for r in rows if (not a.get('page') or r['page']==a['page']) and (not a.get('open_only') or not r['data'].get('done'))]

    def book_template(self,a):
        book=self.book_get(a)
        if 'columns' in a:
            columns=[]
            for c in a['columns']:
                if not c.get('field'):c=dict(c,field='text')
                if c.get('field') not in ['number','date','person','related1','related2','age','cause','notes','place','house','text']:raise ValueError('Неправильне поле колонки.')
                columns.append({'rect':validate_rect(c['rect']),'field':c['field'],'label':str(c.get('label','')),'meaning':str(c.get('meaning',''))})
            book['data']['columns']=columns
            self.book_save({'book':book['id'],'name':book['name'],'items':book['items'],'data':book['data']})
        if a.get('apply'):
            targets=a.get('pages') or [i['page'] for i in book['items'] if i['page']]
            allowed={i['page'] for i in book['items']}
            if any(p not in allowed or not p for p in targets):raise ValueError('Сторінка належить іншій книзі.')
            added=skipped=0
            with self.db:
                for page in targets:
                    if any(r['kind']=='column' for r in self.annotations({'id':page})):skipped+=1;continue
                    for c in book['data'].get('columns',[]):self.save_annotation({'page':page,'data':c|{'kind':'column','text':'','verified':False}});added+=1
            return {'added':added,'skipped':skipped}
        return book['data'].get('columns',[])

    def book_pdf(self,a):
        import pymupdf as fitz
        book=self.book_get(a);target=Path(a['path']).resolve()
        if target.suffix.lower()!='.pdf':raise ValueError('Виберіть файл PDF.')
        # Never replace an imported source, even when a caller selects it as output.
        if target.is_relative_to(self.engine.root/'originals') or any(target==Path(r['path']).resolve() for r in self.db.execute('SELECT path FROM documents')):raise ValueError('Не можна перезаписати оригінал.')
        if target.is_file():
            with target.open('rb') as existing:sha=hashlib.file_digest(existing,'sha256').hexdigest()
            if self.db.execute('SELECT 1 FROM documents WHERE sha=?',(sha,)).fetchone():raise ValueError('Не можна перезаписати оригінал.')
        font_path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/arial.ttf'
        font=fitz.Font(fontfile=str(font_path)) if font_path.is_file() else fitz.Font('cjk')
        pdf=fitz.open();report=[];toc=[]
        try:
            for position,item in enumerate(book['items'],1):
                label=item['label'] or str(position);toc.append([1,label,position])
                if not item['page']:
                    page=pdf.new_page();writer=fitz.TextWriter(page.rect);writer.fill_textbox(fitz.Rect(36,36,550,800),label+'\n'+item['note'],font=font,fontsize=14);writer.write_text(page)
                    report.append({'position':position,'gap':True});continue
                p=self.engine.page(item['page']);image=self.whole_image(p['id']);stream=io.BytesIO();image.save(stream,format='JPEG',quality=95)
                w,h=image.size;scale=600/w;page=pdf.new_page(width=600,height=h*scale);page.insert_image(page.rect,stream=stream.getvalue())
                lines=json.loads(p['lines']); saved_corrections={r['line']:dict(r) for r in self.db.execute('SELECT line,corrected,verified FROM line_corrections WHERE page=?',(p['id'],))}
                corrections={n:r['corrected'] for n,r in saved_corrections.items()}
                rendering=self.engine.render({'id':p['id'],'full':True});rw,rh=rendering['width'],rendering['height'];roi=json.loads(p['roi']) or [0,0,1,1]
                if not lines and p['engine']=='PDF text layer' and Path(p['path']).suffix.lower()=='.pdf':
                    with fitz.open(p['path']) as original:
                        native=original[p['num']]
                        for block in native.get_text('dict')['blocks']:
                            for line in block.get('lines',[]):
                                x0,y0,x1,y1=line['bbox']
                                lines.append({'text':''.join(s['text'] for s in line['spans']),'box':[x0/native.rect.width*rw,y0/native.rect.height*rh,(x1-x0)/native.rect.width*rw,(y1-y0)/native.rect.height*rh]})
                manual=[r for r in self.annotations({'id':p['id']}) if r['kind']=='line' and r.get('verified') and r.get('text','').strip()]
                manual.sort(key=lambda r:(r.get('reading_order',100000),r['rect'][1],r['rect'][0]))
                placed=verified=0;unplaced=[]
                for i,line in enumerate(lines):
                    text=corrections.get(i,line.get('text','')).strip();box=line.get('box')
                    if not text:continue
                    if not box:unplaced.append(text);continue
                    x,y,bw,bh=box
                    rect=fitz.Rect((roi[0]+x/rw*roi[2])*page.rect.width,(roi[1]+y/rh*roi[3])*page.rect.height,(roi[0]+(x+bw)/rw*roi[2])*page.rect.width,(roi[1]+(y+bh)/rh*roi[3])*page.rect.height)&page.rect
                    if rect.is_empty:unplaced.append(text);continue
                    if any((rect & fitz.Rect(r['rect'][0]*page.rect.width,r['rect'][1]*page.rect.height,(r['rect'][0]+r['rect'][2])*page.rect.width,(r['rect'][1]+r['rect'][3])*page.rect.height)).get_area() > rect.get_area()*.5 for r in manual):continue
                    size=min(rect.height*.65,rect.width/max(font.text_length(text,fontsize=1),1))
                    writer=fitz.TextWriter(page.rect);writer.append((rect.x0,rect.y0+rect.height*.8),text,font=font,fontsize=max(.1,size));writer.write_text(page,render_mode=3);placed+=1
                    verified+=bool(saved_corrections.get(i,{}).get('verified'))
                # Verified manual regions carry their own geometry, independently of page OCR.
                for region in manual:
                    x,y,bw,bh=region['rect'];text=region['text'];size=min(bh*page.rect.height*.65,bw*page.rect.width/max(font.text_length(text,fontsize=1),1))
                    writer=fitz.TextWriter(page.rect);writer.append((x*page.rect.width,(y+bh*.8)*page.rect.height),text,font=font,fontsize=max(.1,size));writer.write_text(page,render_mode=3);placed+=1;verified+=1
                report.append({'position':position,'page':p['id'],'source':p['name'],'source_page':p['num']+1,'label':label,'engine':p['engine'],'status':p['status'],'placed_lines':placed,'verified_lines':verified,'unverified_lines':placed-verified,'unplaced_lines':len(unplaced),'text_without_geometry':bool(p['text'].strip() and not lines and not placed)})
            pdf.set_toc(toc);pdf.set_metadata({'title':book['name'],'creator':'ArchiveReader','subject':'Recognition layer may contain unverified OCR/HTR; see export report.'})
            temp=target.with_name(target.name+'.'+uuid.uuid4().hex+'.partial');pdf.save(temp,garbage=4,deflate=True);os.replace(temp,target)
        finally:pdf.close()
        report_path=target.with_suffix('.pdf.report.json');report_path.write_text(json.dumps({'book':book['name'],'pages':report},ensure_ascii=False,indent=2),encoding='utf8')
        return {'path':str(target),'report':str(report_path),'pages':report}
