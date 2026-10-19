"""Human historical-reading context; raw spellings are never rewritten.

This bounded first layer links explicit lexical mappings, source crops and saved
model alternatives. It is not a learned grammar/semantic model or training system.
"""
import contextlib,hashlib,io,json,math,re,unicodedata,uuid
from pathlib import Path
from urllib.parse import urlsplit
try:
 from .library import LibraryTools,digest
 from .workbench import overlaps
 from .engine import uncertain_text
except ImportError:
 from library import LibraryTools,digest
 from workbench import overlaps
 from engine import uncertain_text
FIELDS=('origin','period','institution','rite','script','writer','languages','notes')
ROLES={'text','table','illustration','caption','unknown','damage'}
KINDS={'word','name','place','abbreviation','ligature','calendar','other','orthography','grammar','paleography'}
REFERENCE_FIELDS=('title','url','locator','resource_type','work_period','witness_period','edition_period','scope','authenticity')

def aligned_span(literal,hypothesis,start,end):
 """Bounded textual alignment only. Never estimates image coordinates or correctness."""
 from difflib import SequenceMatcher
 left=list(re.finditer(r'\S+',literal));right=list(re.finditer(r'\S+',hypothesis))
 if len(left)>600 or len(right)>600:return {'status':'limit','text':None,'pixel_geometry':False}
 selected=[i for i,m in enumerate(left) if m.start()<end and m.end()>start]
 if not selected:return {'status':'no_token','text':None,'pixel_geometry':False}
 low,high=min(selected),max(selected)+1;parts=[]
 for tag,i,j,k,l in SequenceMatcher(None,[m.group() for m in left],[m.group() for m in right],autojunk=False).get_opcodes():
  if tag=='insert':
   if low<i<high:parts.extend(right[k:l])
  elif i<high and j>low:
   if tag=='equal':parts.extend(right[k+max(low-i,0):k+min(high-i,j-i)])
   else:parts.extend(right[k:l])
 if not parts:return {'status':'deleted_or_unresolved','text':'','pixel_geometry':False}
 a,b=parts[0].start(),parts[-1].end()
 return {'status':'textual_candidate','text':hypothesis[a:b],'start':a,'end':b,'pixel_geometry':False,'verified':False}


def reference(value):
 if value is None:return {}
 if not isinstance(value,dict):raise ValueError('Неправильне посилання на довідкове джерело.')
 clean={f:text(value.get(f,''),4000 if f in ['title','locator','scope','authenticity'] else 2000) for f in REFERENCE_FIELDS}
 if not any(clean.values()):return {}
 if not all(clean[f].strip() for f in ['title','url','locator']) or value.get('checked') is not True:raise ValueError('Вкажіть назву, посилання, місце у джерелі та підтвердьте його перевірку.')
 try:
  url=urlsplit(clean['url']);valid=url.scheme.lower() in ['http','https'] and bool(url.hostname) and url.username is None and url.password is None and not any(c.isspace() or ord(c)<32 for c in clean['url']);url.port
 except ValueError:valid=False
 if not valid:raise ValueError('Дозволено лише HTTP або HTTPS посилання без облікових даних.')
 return clean|{'checked':True}

def reference_sources():
 """Local discovery hints only; catalog inclusion never means human verification."""
 try:
  path=Path(__file__).with_name('historical_sources.json')
  if path.stat().st_size>1024*1024:raise ValueError('catalog size')
  data=json.loads(path.read_text('utf-8'))
  if not isinstance(data,dict) or data.get('version')!=1 or not isinstance(data.get('sources'),list) or len(data['sources'])>200:raise ValueError('catalog format')
  sources=[];ids=set()
  for item in data['sources']:
   if not isinstance(item,dict):raise ValueError('catalog source')
   ident=text(item.get('id',''),200,True)
   if ident in ids:raise ValueError('catalog duplicate id')
   ids.add(ident)
   # A catalog is not a checked citation: locator and explicit confirmation are
   # still required when the user creates a lexical reference.
   checked=reference({**{f:item.get(f,'') for f in REFERENCE_FIELDS},'locator':'catalog listing only','checked':True})
   checked['locator']=text(item.get('locator',''),4000)
   metadata={}
   for field in ['languages','scripts']:
    values=item.get(field,[])
    if not isinstance(values,list) or len(values)>100:raise ValueError('catalog language/script metadata')
    metadata[field]=[text(value,300,True) for value in values]
   sources.append(checked|metadata|{'id':ident,'category':text(item.get('category',''),300),'verification':text(item.get('verification',''),4000),'access_status':text(item.get('access_status','not_confirmed'),300),'checked':False,'listing_only':True,'auto_apply':False,'gt_eligible':False,'training_eligible':False})
  return sources,[]
 except (OSError,ValueError,TypeError,RecursionError):return [],['reference_catalog_unavailable_or_invalid']

def file_hash(path):
 with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def text(value,limit=4000,required=False):
 if not isinstance(value,str) or len(value)>limit or (required and not value.strip()):raise ValueError('Введіть текст допустимої довжини.')
 return value

def box(rect):
 if not isinstance(rect,list) or len(rect)!=4 or any(type(v) not in [float,int] or not math.isfinite(v) for v in rect):raise ValueError('Неправильні межі ділянки.')
 x,y,w,h=rect
 if not(0<=x<1 and 0<=y<1 and w>0 and h>0 and x+w<=1.000001 and y+h<=1.000001):raise ValueError('Неправильні межі ділянки.')
 return rect

def inside(inner,outer):return inner[0]>=outer[0]-1e-6 and inner[1]>=outer[1]-1e-6 and inner[0]+inner[2]<=outer[0]+outer[2]+1e-6 and inner[1]+inner[3]<=outer[1]+outer[3]+1e-6

def key(value):return unicodedata.normalize('NFC',value).casefold()
def edit_distance(a,b,maximum=2):
 if abs(len(a)-len(b))>maximum:return maximum+1
 previous=list(range(len(b)+1))
 for i,ca in enumerate(a,1):
  current=[maximum+1]*(len(b)+1);current[0]=i
  for j in range(max(1,i-maximum),min(len(b),i+maximum)+1):current[j]=min(current[j-1]+1,previous[j]+1,previous[j-1]+(ca!=b[j-1]))
  if min(current)>maximum:return maximum+1
  previous=current
 return previous[-1]

class HistoricalTools(LibraryTools):
 def __init__(self,engine):
  super().__init__(engine)
  self.db.executescript('''
   CREATE TABLE IF NOT EXISTS historical_profiles(doc TEXT PRIMARY KEY REFERENCES documents(id),data TEXT NOT NULL);
   CREATE TABLE IF NOT EXISTS historical_packages(doc TEXT PRIMARY KEY REFERENCES documents(id),data TEXT NOT NULL);
   CREATE TABLE IF NOT EXISTS historical_terms(id TEXT PRIMARY KEY,doc TEXT REFERENCES documents(id),page TEXT REFERENCES pages(id),annotation TEXT,data TEXT NOT NULL);
   CREATE INDEX IF NOT EXISTS idx_historical_terms_doc ON historical_terms(doc);
   CREATE TABLE IF NOT EXISTS historical_decisions(id TEXT PRIMARY KEY,page TEXT REFERENCES pages(id),annotation TEXT,data TEXT NOT NULL);
   CREATE INDEX IF NOT EXISTS idx_historical_decisions_page ON historical_decisions(page);
   CREATE TABLE IF NOT EXISTS historical_layout(id TEXT PRIMARY KEY,page TEXT REFERENCES pages(id),data TEXT NOT NULL);
   CREATE INDEX IF NOT EXISTS idx_historical_layout_page ON historical_layout(page);
   CREATE TABLE IF NOT EXISTS historical_exemplars(id TEXT PRIMARY KEY,page TEXT REFERENCES pages(id),annotation TEXT,data TEXT NOT NULL,png BLOB NOT NULL);
   CREATE INDEX IF NOT EXISTS idx_historical_exemplars_page ON historical_exemplars(page);
   CREATE TABLE IF NOT EXISTS historical_audit(id INTEGER PRIMARY KEY,kind TEXT,entity TEXT,page TEXT,before TEXT,after TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
  ''')
 def _page(self,a):return a.get('page') or a.get('id')
 def _source(self,page):
  p=self.engine.page(page);doc=dict(self.db.execute('SELECT * FROM documents WHERE id=?',(p['doc'],)).fetchone());actual=file_hash(doc['path'])
  if actual!=doc['sha']:raise ValueError('Оригінал джерела змінився. Оновіть бібліотеку.')
  return {'page':page,'doc':p['doc'],'name':p['name'],'frame':p['num'],'source_sha256':actual}
 def _docs(self,doc):
  docs=sorted(self.photo_book_docs(doc))
  if len(docs)>5000:raise ValueError('Книга завелика для цієї операції.')
  return docs
 def _profile(self,doc,docs):
  rows=[dict(r) for r in self.db.execute('SELECT doc,data FROM historical_profiles WHERE doc IN ('+','.join('?' for _ in docs)+')',docs)];stored=next((json.loads(r['data']) for r in rows if r['doc']==doc),json.loads(rows[0]['data']) if rows else {})
  values={f:([] if f=='languages' else '') for f in FIELDS};values.update(stored.get('values',{}))
  return {'values':values,'signature':digest({'docs':docs,'profiles':sorted((r['doc'],r['data']) for r in rows)}),'conflicting_book_values':len({digest(json.loads(r['data']).get('values',{})) for r in rows})>1,'scope_documents':len(docs)}
 def _reports(self,doc):
  result=[]
  for row in self.db.execute('SELECT * FROM comparison_runs WHERE doc=? ORDER BY rowid DESC LIMIT 12',(doc,)):
   folder=Path(row['path']).resolve();manifest=folder/'manifest.json';report=folder/'report.json'
   if not folder.is_relative_to((self.engine.root/'results').resolve()):continue
   try:
    if manifest.stat().st_size>8*1024*1024 or report.stat().st_size>8*1024*1024:continue
    manifest_bytes=manifest.read_bytes();report_bytes=report.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest()!=row['manifest_sha']:continue
    manifest_data=json.loads(manifest_bytes);report_data=json.loads(report_bytes)
    if not isinstance(manifest_data,list) or len(manifest_data)>10000 or any(not isinstance(r,dict) for r in manifest_data) or not isinstance(report_data,dict) or not isinstance(report_data.get('rows'),list) or len(report_data['rows'])>10000 or any(not isinstance(r,dict) for r in report_data['rows']):continue
    result.append({'id':row['id'],'folder':folder,'report_sha256':hashlib.sha256(report_bytes).hexdigest(),'manifest_sha256':row['manifest_sha'],'manifest':manifest_data,'data':report_data})
   except (OSError,ValueError):continue
  return result
 def _state(self,page):
  source=self._source(page);docs=self._docs(source['doc']);profile=self._profile(source['doc'],docs)
  package=self._package(source['doc'],docs)
  regions=[json.loads(r['data'])|{'id':r['id']} for r in self.db.execute('SELECT id,data FROM annotations WHERE page=? ORDER BY rowid LIMIT 1001',(page,))]
  term_rows=list(self.db.execute('SELECT * FROM historical_terms WHERE doc IN ('+','.join('?' for _ in docs)+') ORDER BY rowid DESC LIMIT 501',docs));terms=self._validated_terms(term_rows[:500])
  layout=[json.loads(r['data'])|{'id':r['id']} for r in self.db.execute('SELECT id,data FROM historical_layout WHERE page=? ORDER BY rowid DESC LIMIT 201',(page,))]
  exemplars=[json.loads(r['data'])|{'id':r['id'],'annotation':r['annotation']} for r in self.db.execute('SELECT id,annotation,data FROM historical_exemplars WHERE page=? ORDER BY rowid DESC LIMIT 201',(page,))]
  reports=self._reports(source['doc']);signature=digest({'source':source,'profile':profile,'package':package,'regions':regions,'terms':terms,'layout':layout,'exemplars':exemplars,'reports':[{k:r[k] for k in ['id','report_sha256','manifest_sha256']} for r in reports]})
  return {'source':source,'docs':docs,'profile':profile,'package':package,'regions':regions[:1000],'terms':terms,'layout':layout[:200],'exemplars':exemplars[:200],'reports':reports,'signature':signature,'limits':{'regions':len(regions)>1000,'terms':len(term_rows)>500,'layout':len(layout)>200,'exemplars':len(exemplars)>200}}
 def _package(self,doc,docs):
  rows=[dict(r) for r in self.db.execute('SELECT doc,data FROM historical_packages WHERE doc IN ('+','.join('?' for _ in docs)+')',docs)]
  stored=next((json.loads(r['data']) for r in rows if r['doc']==doc),json.loads(rows[0]['data']) if rows else {})
  catalog,warnings=reference_sources();selected=set(stored.get('source_ids',[]));sources=[s for s in catalog if s['id'] in selected]
  if selected-{s['id'] for s in sources}:warnings.append('package_reference_source_missing')
  return {'configured':stored.get('configured',False),'term_ids':stored.get('term_ids',[]),'source_ids':stored.get('source_ids',[]),'notes':stored.get('notes',''),'checked':stored.get('checked',False),'revision':stored.get('revision'),'selected_sources':sources,'warnings':warnings,'conflicting_book_values':len({r['data'] for r in rows})>1,'revision_signature':digest({'docs':docs,'packages':sorted((r['doc'],r['data']) for r in rows)})}
 def historical_package_get(self,a):
  state=self._state(self._page(a));catalog,warnings=reference_sources()
  return state['package']|{'signature':state['signature'],'profile':state['profile']['values'],'available_terms':state['terms'],'reference_sources':catalog,'warnings':list(dict.fromkeys(state['package']['warnings']+warnings)),'policy':'Explicit book selection only. Catalog sources are discovery references, not applied rules or verified citations.'}
 def historical_package_save(self,a):
  page=self._page(a);state=self._state(page)
  if a.get('checked') is not True or type(a.get('configured',True)) is not bool:raise ValueError('Підтвердьте власний вибір пакета знань книги.')
  term_ids=a.get('term_ids',[]);source_ids=a.get('source_ids',[])
  for values,maximum in [(term_ids,500),(source_ids,200)]:
   if not isinstance(values,list) or len(values)>maximum or any(not isinstance(v,str) or not v or len(v)>200 for v in values) or len(set(values))!=len(values):raise ValueError('Неправильний перелік складових пакета знань.')
  catalog,_=reference_sources()
  if set(term_ids)-{t['id'] for t in state['terms']} or set(source_ids)-{s['id'] for s in catalog}:raise ValueError('Вибраний відповідник або довідкове джерело недоступні для цієї книги.')
  data={'configured':a.get('configured',True),'term_ids':term_ids,'source_ids':source_ids,'notes':text(a.get('notes',''),8000),'checked':True,'revision':uuid.uuid4().hex}
  with self._locked():
   self._recheck(page,state,a.get('expected'))
   if a.get('expected')!=state['signature']:raise ValueError('Пакет або контекст книги змінилися. Оновіть перегляд.')
   self.db.executemany('INSERT INTO historical_packages VALUES (?,?) ON CONFLICT(doc) DO UPDATE SET data=excluded.data',[(doc,json.dumps(data,ensure_ascii=False)) for doc in state['docs']]);self._audit('package',state['source']['doc'],page,state['package'],data)
  return self.historical_package_get({'page':page})
 def _region(self,state,annotation,kinds=('line','entry')):
  row=next((r for r in state['regions'] if r['id']==annotation),None)
  if not row or row['kind'] not in kinds:raise ValueError('Виберіть збережену ділянку рядка цієї сторінки.' if kinds==('line',) else 'Виберіть збережений рядок або запис цієї сторінки.')
  return row
 def _validated_terms(self,rows):
  sources={};regions={};terms=[]
  for row in rows:
   data=json.loads(row['data']);reasons=[];page=row['page'];annotation=row['annotation']
   doc=row['doc']
   if doc not in sources:
    original=self.db.execute('SELECT path,sha FROM documents WHERE id=?',(doc,)).fetchone()
    try:sources[doc]=file_hash(original['path']) if original else None
    except OSError:sources[doc]=None
    if original and sources[doc]!=original['sha']:sources[doc]=None
   source=sources[doc];bound_page=self.db.execute('SELECT doc FROM pages WHERE id=?',(page,)).fetchone()
   if not source or not bound_page or bound_page['doc']!=doc or source!=data.get('source_sha256'):reasons.append('source_changed')
   if annotation:
    ident=(page,annotation)
    if ident not in regions:
     raw=self.db.execute('SELECT data FROM annotations WHERE id=? AND page=?',(annotation,page)).fetchone();regions[ident]=json.loads(raw['data'])|{'id':annotation} if raw else None
    if not regions[ident] or digest(regions[ident])!=data.get('region_signature'):reasons.append('bound_region_changed')
   terms.append(data|{'id':row['id'],'page':page,'annotation':annotation,'stale':bool(reasons),'stale_reasons':reasons,'applicable':not reasons})
  return terms
 def _hand_exemplars(self,state):
  hand=state['profile']['values'].get('writer','');result=[]
  if not hand.strip():return result
  rows=self.db.execute('SELECT e.id,e.page,e.annotation,e.data,p.doc FROM historical_exemplars e JOIN pages p ON p.id=e.page WHERE p.doc IN ('+','.join('?' for _ in state['docs'])+') ORDER BY e.rowid DESC LIMIT 100',state['docs'])
  sources={};profiles={}
  for row in rows:
   data=json.loads(row['data'])
   if not data.get('checked') or data.get('hand_label')!=hand:continue
   reasons=[]
   if row['doc'] not in profiles:profiles[row['doc']]=self._profile(row['doc'],state['docs'])['values']
   if data.get('profile_values_sha256')!=digest(profiles[row['doc']]):reasons.append('profile_changed')
   if row['page'] not in sources:
    try:sources[row['page']]=self._source(row['page'])['source_sha256']
    except (OSError,ValueError):sources[row['page']]=None
   if sources[row['page']]!=data.get('source_sha256'):reasons.append('source_changed')
   region=self.db.execute('SELECT data FROM annotations WHERE id=? AND page=?',(row['annotation'],row['page'])).fetchone()
   if not region or digest(json.loads(region['data'])|{'id':row['annotation']})!=data.get('region_signature'):reasons.append('parent_line_changed')
   path=self.engine.root/'cache'/('historical-exemplar-'+row['id']+'.png')
   if not path.is_file() or file_hash(path)!=data['crop_sha256']:
    png=self.db.execute('SELECT png FROM historical_exemplars WHERE id=?',(row['id'],)).fetchone()['png']
    if hashlib.sha256(png).hexdigest()!=data['crop_sha256']:reasons.append('crop_changed')
    else:path.write_bytes(png)
   result.append(data|{'id':row['id'],'page':row['page'],'annotation':row['annotation'],'path':str(path),'stale':bool(reasons),'stale_reasons':reasons,'applicable':not reasons,'match_basis':'explicit_same_book_and_manual_hand_label','policy':'Advisory visual exemplar only; no automatic glyph classification or text replacement.'})
  return result
 def _audit(self,kind,ident,page,before,after):self.db.execute('INSERT INTO historical_audit(kind,entity,page,before,after) VALUES (?,?,?,?,?)',(kind,ident,page,json.dumps(before,ensure_ascii=False) if before is not None else None,json.dumps(after,ensure_ascii=False)))
 @contextlib.contextmanager
 def _locked(self):
  with self.db:
   if not self.db.in_transaction:self.db.execute('BEGIN IMMEDIATE')
   yield
 def _recheck(self,page,state,expected=None):
  current=self._state(page)
  if current['signature']!=state['signature'] or (expected is not None and expected!=current['signature']):raise ValueError('Джерело або історичний контекст змінилися. Оновіть перегляд.')
  return current
 def historical_get(self,a):
  page=self._page(a);state=self._state(page);decisions=[]
  for row in self.db.execute('SELECT id,annotation,data FROM historical_decisions WHERE page=? ORDER BY rowid DESC LIMIT 200',(page,)):
   data=json.loads(row['data']);decisions.append(data|{'id':row['id'],'annotation':row['annotation'],'stale':data['source_signature']!=state['signature']})
  exemplars=[]
  for row in state['exemplars']:
   region=next((r for r in state['regions'] if r['id']==row['annotation']),None);stale=not region or digest(region)!=row['region_signature'] or row['source_sha256']!=state['source']['source_sha256'] or row.get('profile_values_sha256')!=digest(state['profile']['values'])
   path=self.engine.root/'cache'/('historical-exemplar-'+row['id']+'.png')
   if not path.is_file() or file_hash(path)!=row['crop_sha256']:
    stored=self.db.execute('SELECT png FROM historical_exemplars WHERE id=?',(row['id'],)).fetchone()['png']
    if hashlib.sha256(stored).hexdigest()!=row['crop_sha256']:raise ValueError('Збережений зразок пошкоджено.')
    path.write_bytes(stored)
   exemplars.append(row|{'path':str(path),'stale':stale})
  layout=[r|{'stale':r['source_sha256']!=state['source']['source_sha256']} for r in state['layout']]
  catalog,catalog_warnings=reference_sources()
  return {'page':page,'source':state['source'],'source_sha256':state['source']['source_sha256'],'signature':state['signature'],'profile':state['profile'],'regions':[r|{'region_signature':digest(r)} for r in state['regions']],'terms':state['terms'],'decisions':decisions,'exemplars':exemplars,'layout':layout,'limits':state['limits'],'reference_sources':catalog,'warnings':catalog_warnings,'policy':'Historical forms and interpretations remain separate; no OCR/annotation overwrite, model learning or ground-truth creation.'}
 def historical_profile(self,a):
  page=self._page(a);state=self._state(page);values=a.get('values',{})
  if not isinstance(values,dict):raise ValueError('Неправильний історичний профіль.')
  clean={f:text(values.get(f,''),8000 if f=='notes' else 500) for f in FIELDS if f!='languages'};languages=values.get('languages',[])
  if isinstance(languages,str):languages=[v.strip() for v in re.split('[,;]',languages) if v.strip()]
  if not isinstance(languages,list) or len(languages)>20:raise ValueError('Вкажіть перелік мов.')
  clean['languages']=[text(v,100,True) for v in languages]
  with self._locked():
   current=self._recheck(page,state)
   if a.get('expected')!=current['profile']['signature']:raise ValueError('Історичний профіль змінився. Оновіть перегляд.')
   data={'values':clean,'revision':uuid.uuid4().hex,'source_sha256':state['source']['source_sha256']}
   self.db.executemany('INSERT INTO historical_profiles VALUES (?,?) ON CONFLICT(doc) DO UPDATE SET data=excluded.data',[(doc,json.dumps(data,ensure_ascii=False)) for doc in state['docs']]);self._audit('profile',state['source']['doc'],page,current['profile']['values'],clean)
  return self.historical_get({'page':page})['profile']
 def historical_term(self,a):
  page=self._page(a);state=self._state(page)
  if a.get('checked') is not True:raise ValueError('Підтвердьте власну перевірку історичного відповідника.')
  annotation=a.get('annotation');region=self._region(state,annotation) if annotation else None
  data={f:text(a.get(f,''),4000 if f in ['meaning','note'] else 300,f in ['form','lemma','meaning','language','note']) for f in ['form','lemma','meaning','language','period','writer','note','concept']};data['kind']=a.get('kind','word')
  if data['kind'] not in KINDS:raise ValueError('Неправильний тип історичного відповідника.')
  data['reference']=reference(a.get('reference'))
  data.update(human_checked=True,verified=False,gt_eligible=False,source_sha256=state['source']['source_sha256'],region_signature=digest(region) if region else None)
  ident=a.get('term') or uuid.uuid4().hex
  with self._locked():
   self._recheck(page,state,a.get('expected'));old=self.db.execute('SELECT * FROM historical_terms WHERE id=?',(ident,)).fetchone()
   if old and old['doc'] not in state['docs']:raise ValueError('Відповідник належить іншій книзі.')
   self.db.execute('INSERT INTO historical_terms VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET doc=excluded.doc,page=excluded.page,annotation=excluded.annotation,data=excluded.data',(ident,state['source']['doc'],page,annotation,json.dumps(data,ensure_ascii=False)));self._audit('term',ident,page,(json.loads(old['data'])|{'page':old['page'],'annotation':old['annotation']}) if old else None,data)
  return data|{'id':ident,'page':page,'annotation':annotation}
 def _alternatives(self,state,region):
  alternatives=[];warnings=[];current_crop=None
  for report in state['reports']:
   row=next((r for r in report['data'].get('rows',[]) if r.get('id')==region['id']),None);manifest=next((r for r in report['manifest'] if r.get('id')==region['id']),None)
   if not row or not manifest:continue
   if row.get('rect')!=region['rect'] or manifest.get('rect')!=region['rect'] or manifest.get('document')!=state['source']['doc'] or manifest.get('page')!=state['source']['frame']+1:warnings.append('stale_comparison_ignored');continue
   if current_crop is None:current_crop=file_hash(self.region_crop({'id':state['source']['page'],'annotation':region['id']})['path'])
   if not isinstance(manifest.get('image'),str):warnings.append('stale_comparison_ignored');continue
   image=(report['folder']/manifest['image']).resolve()
   if not image.is_relative_to(report['folder']) or not image.is_file() or file_hash(image)!=manifest.get('image_sha256') or current_crop!=manifest.get('image_sha256') or row.get('image_sha256')!=manifest.get('image_sha256'):warnings.append('stale_comparison_ignored');continue
   for model,prediction in list(row.get('results',{}).items())[:12]:
    if not isinstance(prediction,dict):continue
    alternatives.append({'model':model,'text':text(prediction.get('text',''),20000),'error':prediction.get('error'),'source_kind':'saved_source_bound_comparison','run':report['id'],'report_sha256':report['report_sha256'],'image_sha256':current_crop,'raw_prediction':prediction})
   break
  return alternatives,warnings
 def _analyze(self,page,annotation,state=None):
  state=state or self._state(page);region=self._region(state,annotation);literal=text(region.get('text',''),20000);alternatives,warnings=self._alternatives(state,region)
  profile=state['profile']['values'];tokens=[];terms=[t for t in state['terms'] if t['applicable'] and (not state['package']['configured'] or t['id'] in state['package']['term_ids'])]
  def tokenize(literal,budget):
   tokens=[]
   for token in list(re.finditer(r"[^\W_]+(?:['’\-][^\W_]+)*",literal,re.UNICODE))[:budget]:
    word=token.group();matches=[]
    if len(word)<=128:
     for term in terms:
      form=term['form'];dist=0 if key(form)==key(word) else edit_distance(key(form),key(word)) if min(len(form),len(word))>=4 and max(len(form),len(word))<=128 else 3
      if term['kind'] in ['orthography','grammar','paleography'] and form!=word:continue
      if dist>2:continue
      applicability={f:('unspecified' if not term.get(f) or not profile.get(f) else 'matches_declared_context' if key(term[f])==key(profile[f]) else 'different_declared_context') for f in ['period','writer']}
      equivalents=[]
      for other in terms:
       if other['id']==term['id']:continue
       concept=term.get('concept','');other_concept=other.get('concept','')
       shared_concept=bool(concept and other_concept and unicodedata.normalize('NFC',concept)==unicodedata.normalize('NFC',other_concept))
       same_language_lemma=key(other['language'])==key(term['language']) and key(other['lemma'])==key(term['lemma']) and not (concept and other_concept and not shared_concept)
       if shared_concept or same_language_lemma:equivalents.append({'term_id':other['id'],'form':other['form'],'lemma':other['lemma'],'language':other['language'],'meaning':other['meaning'],'concept':other_concept,'reference':other.get('reference',{}),'kind':other['kind'],'basis':'human_shared_concept' if shared_concept else 'same_language_lemma'})
      equivalents=equivalents[:12]
      matches.append({'term_id':term['id'],'form':form,'lemma':term['lemma'],'meaning':term['meaning'],'language':term['language'],'concept':term.get('concept',''),'reference':term.get('reference',{}),'kind':term['kind'],'match_type':'exact_form' if form==word else 'case_variant' if dist==0 else 'fuzzy_form_suggestion','distance':dist,'context_applicability':applicability,'equivalents':equivalents,'policy':'Explicit human lexical mapping only; spelling/morphology differences are not proven errors or automatic corrections.'})
    matches.sort(key=lambda m:(m['distance'],m['term_id']));tokens.append({'literal':word,'start':token.start(),'end':token.end(),'matches':matches[:8],'unknown_is_error':False})
   return tokens
  budget=max(1,400//(len(alternatives)+1));tokens=tokenize(literal,budget)
  for alternative in alternatives:alternative['tokens']=tokenize(alternative['text'],budget)
  if any(m.get('reference') or any(e.get('reference') for e in m['equivalents']) for t in tokens+[t for v in alternatives for t in v['tokens']] for m in t['matches']):warnings.append('reference_scope_requires_human_review')
  context=sorted([r for r in state['regions'] if r['kind']=='line' and r['id']!=annotation],key=lambda r:(abs(r['rect'][1]-region['rect'][1]),abs(r['rect'][0]-region['rect'][0])))[:4]
  context=[{'id':r['id'],'text':r.get('text',''),'rect':r['rect'],'reading_order':r.get('reading_order'),'relation':'same_saved_parent' if r.get('parent') and r.get('parent')==region.get('parent') else 'nearby_geometry_unverified_order'} for r in context]
  damaged=any(r['kind'] in ['damage','missing'] and overlaps(region['rect'],r['rect']) for r in state['regions']) or any(r['role']=='damage' and overlaps(region['rect'],r['rect']) for r in state['layout'])
  if damaged:warnings.append('damage_overlap_no_ground_truth')
  if len({r['text'] for r in alternatives if not r.get('error')})>1:warnings.append('saved_model_variants_disagree')
  warnings+=['context_is_human_lexicon_not_learned_grammar','unknown_words_are_not_errors','no_inferred_nationality_or_language']
  exemplars=self._hand_exemplars(state)
  signature=digest({'source_signature':state['signature'],'annotation':annotation,'alternatives':alternatives,'exemplars':exemplars})
  return {'signature':signature,'source_signature':state['signature'],'original':region,'alternatives':alternatives,'tokens':tokens,'context':context,'exemplars':exemplars,'warnings':list(dict.fromkeys(warnings)),'passes':2 if terms else 1,'damaged':damaged,'gt_eligible':False,'policy':'At most two bounded passes: retain visual/model evidence, then explicit local lexical suggestions. No sentence-semantic AI, calibrated probabilities, modern spelling correction or automatic training.'}
 def historical_analyze(self,a):return self._analyze(self._page(a),a['annotation'])
 def historical_word(self,a):
  page=self._page(a);state=self._state(page);analysis=self._analyze(page,a['annotation'],state);original=analysis['original'];literal=original.get('text','');start=a.get('start');end=a.get('end')
  if type(start) is not int or type(end) is not int or not 0<=start<end<=len(literal) or end-start>500:raise ValueError('Виберіть дійсний фрагмент тексту до 500 символів.')
  parent=self.region_crop({'id':page,'annotation':a['annotation']});crop=dict(parent,geometry_basis='whole_saved_region',word_geometry_known=False)
  if a.get('rect') is not None:
   rect=box(a['rect'])
   if not inside(rect,original['rect']):raise ValueError('Ручні межі слова мають бути всередині вибраного рядка або запису.')
   image=self.whole_image(page);x,y,w,h=rect;pixels=[round(x*image.width),round(y*image.height),round((x+w)*image.width),round((y+h)*image.height)]
   if pixels[2]<=pixels[0] or pixels[3]<=pixels[1]:raise ValueError('Ручний фрагмент слова надто малий.')
   fragment=image.crop(tuple(pixels));encoded=io.BytesIO();fragment.save(encoded,format='PNG');raw=encoded.getvalue();sha=hashlib.sha256(raw).hexdigest();path=self.engine.root/'cache'/('historical-word-'+sha+'.png');path.write_bytes(raw)
   crop={'path':str(path),'rect':rect,'width':fragment.width,'height':fragment.height,'crop_sha256':sha,'geometry_basis':'human_manual_word_rect','word_geometry_known':False,'policy':'Manual crop supplied by user; correspondence to selected text is not automatically verified.'}
  self._recheck(page,state)
  return {'signature':analysis['signature'],'literal':literal[start:end],'start':start,'end':end,'original':original,'parent_crop':parent,'crop':crop,'tokens':[t for t in analysis['tokens'] if t['start']<end and t['end']>start],'alternatives':[v|{'alignment':'textual_only_no_pixel_alignment','selected_span':aligned_span(literal,v['text'],start,end) if not v.get('error') else {'status':'model_failed','text':None,'pixel_geometry':False}} for v in analysis['alternatives']],'context':analysis['context'],'exemplars':analysis['exemplars'],'package':state['package'],'warnings':analysis['warnings'],'saved':False,'policy':'Character span inspection only; Textual alignment is a review candidate, may include several words, and never establishes pixel word geometry. Full raw readings are retained. No decision, source text, ground truth or model weights changed.'}
 def historical_decide(self,a):
  page=self._page(a);state=self._state(page);analysis=self._analyze(page,a['annotation'],state);reading=text(a.get('reading',''),20000,True);interpretation=text(a.get('interpretation',''),8000);note=text(a.get('note',''),4000,True)
  if a.get('checked') is not True:raise ValueError('Підтвердьте власну перевірку прочитання.')
  if type(a.get('uncertain',False)) is not bool:raise ValueError('Позначте непевність прочитання.')
  uncertain=a.get('uncertain',False)
  if (analysis['damaged'] or uncertain_text(reading)) and not uncertain:raise ValueError('Пошкоджений або непевний фрагмент збережіть як непевний.')
  spans=a.get('spans',[])
  if not isinstance(spans,list) or len(spans)>100:raise ValueError('Забагато мовних фрагментів.')
  clean=[]
  for span in spans:
   if not isinstance(span,dict) or type(span.get('start')) is not int or type(span.get('end')) is not int or not 0<=span['start']<span['end']<=len(reading):raise ValueError('Межі мовного фрагмента виходять за текст.')
   clean.append({'start':span['start'],'end':span['end'],'literal':reading[span['start']:span['end']],'language':text(span.get('language',''),100),'note':text(span.get('note',''),2000)})
  ident=uuid.uuid4().hex;data={'reading':reading,'interpretation':interpretation,'note':note,'checked':True,'uncertain':uncertain,'spans':clean,'verified':False,'gt_eligible':False,'source_sha256':state['source']['source_sha256'],'source_signature':state['signature'],'analysis_signature':analysis['signature'],'damaged':analysis['damaged']}
  with self._locked():
   current=self._recheck(page,state);again=self._analyze(page,a['annotation'],current)
   if a.get('signature')!=again['signature']:raise ValueError('Прочитання або контекст змінилися. Повторіть аналіз.')
   self.db.execute('INSERT INTO historical_decisions VALUES (?,?,?,?)',(ident,page,a['annotation'],json.dumps(data,ensure_ascii=False)));self._audit('decision',ident,page,None,data)
  return data|{'id':ident,'annotation':a['annotation'],'annotation_changed':False,'weights_changed':False}
 def historical_layout(self,a):
  page=self._page(a);state=self._state(page);role=a.get('role')
  if role not in ROLES:raise ValueError('Неправильна роль ділянки.')
  if a.get('checked') is not True:raise ValueError('Підтвердьте ручну перевірку структури сторінки.')
  data={'role':role,'rect':box(a['rect']),'note':text(a.get('note',''),4000,True),'checked':True,'source_sha256':state['source']['source_sha256'],'automatic_ocr_exclusion':False,'gt_eligible':False};ident=a.get('layout') or uuid.uuid4().hex
  with self._locked():
   self._recheck(page,state,a.get('expected'));old=self.db.execute('SELECT page,data FROM historical_layout WHERE id=?',(ident,)).fetchone()
   if old and old['page']!=page:raise ValueError('Структурна ділянка належить іншій сторінці.')
   self.db.execute('INSERT INTO historical_layout VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(ident,page,json.dumps(data,ensure_ascii=False)));self._audit('layout',ident,page,json.loads(old['data']) if old else None,data)
  return data|{'id':ident,'annotation_changed':False}
 def historical_exemplar(self,a):
  from PIL import Image
  page=self._page(a);state=self._state(page);region=self._region(state,a['annotation'],('line',));rect=box(a['rect'])
  if not inside(rect,region['rect']):raise ValueError('Зразок літери має бути всередині вибраного рядка.')
  if a.get('checked') is not True:raise ValueError('Підтвердьте перевірку зразка літери.')
  label=text(a.get('label',''),200,True);note=text(a.get('note',''),4000,True);image=self.whole_image(page);x,y,w,h=rect;pixels=[round(x*image.width),round(y*image.height),round((x+w)*image.width),round((y+h)*image.height)]
  if pixels[2]<=pixels[0] or pixels[3]<=pixels[1]:raise ValueError('Зразок літери надто малий.')
  crop=image.crop(tuple(pixels));encoded=io.BytesIO();crop.save(encoded,format='PNG');png=encoded.getvalue();ident=uuid.uuid4().hex
  data={'rect':rect,'pixel_box':pixels,'label':label,'note':note,'checked':True,'source_sha256':state['source']['source_sha256'],'region_signature':digest(region),'crop_sha256':hashlib.sha256(png).hexdigest(),'width':crop.width,'height':crop.height,'verified':False,'gt_eligible':False,'automatic_training':False,'damaged':any(r['kind'] in ['damage','missing'] and overlaps(rect,r['rect']) for r in state['regions']) or any(r['role']=='damage' and overlaps(rect,r['rect']) for r in state['layout'])}
  data.update(hand_label=state['profile']['values'].get('writer',''),profile_values_sha256=digest(state['profile']['values']))
  with self._locked():
   self._recheck(page,state,a.get('expected'));self.db.execute('INSERT INTO historical_exemplars VALUES (?,?,?,?,?)',(ident,page,a['annotation'],json.dumps(data,ensure_ascii=False),png));self._audit('exemplar',ident,page,None,data)
  path=self.engine.root/'cache'/('historical-exemplar-'+ident+'.png');path.write_bytes(png)
  return data|{'id':ident,'annotation':a['annotation'],'path':str(path),'weights_changed':False}

 def historical_structure_propose(self,a):
  try:
   from .structure_proposals import cached_structure
  except ImportError:from structure_proposals import cached_structure
  page=self._page(a);state=self._state(page);render=self.engine.render({'id':page,'whole':True,'full':True,'preprocess':'original'});image_sha=file_hash(render['path']);result=cached_structure(render['path'],self.engine.root/'cache',a.get('force') is True)
  self._recheck(page,state)
  candidates=[dict(candidate,proposal_id=digest({'source':state['source'],'image_sha256':image_sha,'candidate':candidate}),source_sha256=state['source']['source_sha256']) for candidate in result['candidates']]
  return result|{'signature':state['signature'],'source_sha256':state['source']['source_sha256'],'image_sha256':image_sha,'image':render,'candidates':candidates,'saved':False,'policy':result.get('policy','')+' Source-bound preview only; explicit human layout review is required. No OCR exclusion or annotation mutation.'}
