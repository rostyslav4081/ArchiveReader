"""Resumable full-page review. Geometry and model outputs never certify coverage."""
import ctypes,hashlib,html,json,os,time,uuid,shutil,importlib.metadata,io
from pathlib import Path
try:
 from .layout import LayoutTools,content_sha,fingerprint
 from .model_identity import fingerprint_models
except ImportError:
 from layout import LayoutTools,content_sha,fingerprint
 from model_identity import fingerprint_models

def artifact(path,data):
 path=Path(path);temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
 try:
  temporary.write_bytes(data.encode('utf-8') if isinstance(data,str) else data);os.replace(temporary,path)
 finally:temporary.unlink(missing_ok=True)
def png_artifact(path,image):
 data=io.BytesIO();image.save(data,format='PNG');artifact(path,data.getvalue())

def alive(pid):
 if not isinstance(pid,int) or pid<=0:return False
 if os.name=='nt':
  kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.OpenProcess.restype=ctypes.c_void_p
  handle=kernel.OpenProcess(0x1000,False,pid)
  if not handle:return ctypes.get_last_error()==5
  code=ctypes.c_ulong();kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)];kernel.CloseHandle.argtypes=[ctypes.c_void_p]
  try:return not kernel.GetExitCodeProcess(handle,ctypes.byref(code)) or code.value==259
  finally:kernel.CloseHandle(handle)
 try:os.kill(pid,0);return True
 except ProcessLookupError:return False
 except PermissionError:return True

def runtime_identity(options):
 try:
  from importlib import resources
  default=content_sha(resources.files('kraken').joinpath('blla.mlmodel')) if not options.get('segmentation') else None
  version=importlib.metadata.version('kraken')
 except (ImportError,FileNotFoundError,importlib.metadata.PackageNotFoundError):default=None;version=None
 exe=shutil.which(options.get('executable','kraken'))
 return {'kraken':version,'default_segmentation_sha256':default,'executable_sha256':content_sha(exe) if exe else None,'implementation':{name:content_sha(Path(__file__).parent/name) for name in ['page_review.py','layout.py','recognizers.py']}}

class PageReviewTools(LayoutTools):
 def __init__(self,engine):
  super().__init__(engine);self.db.execute('CREATE TABLE IF NOT EXISTS page_review_jobs(id TEXT PRIMARY KEY,page TEXT,data TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP)');self.db.commit()
 def binding(self,page):
  p=self.engine.page(page)
  return {'source_sha256':content_sha(p['path']),'annotations':fingerprint(self.annotations({'id':page}))}
 def store(self,ident,job):
  with self.db:self.db.execute('UPDATE page_review_jobs SET data=? WHERE id=?',(json.dumps(job,ensure_ascii=False),ident))
 def load(self,ident):
  row=self.db.execute('SELECT data FROM page_review_jobs WHERE id=?',(ident,)).fetchone()
  if not row:raise ValueError('Завдання не знайдено.')
  return json.loads(row['data'])
 def page_review_start(self,a):
  page=self.engine.page(a['id']);options={k:a[k] for k in ['model','segmentation','executable','threads','timeout','mode'] if k in a};options.setdefault('mode','columns');models=fingerprint_models(options)
  if not models['recognition']:raise ValueError('Виберіть локальну модель Kraken (.mlmodel або .safetensors).')
  if content_sha(page['path'])!=self.db.execute('SELECT sha FROM documents WHERE id=?',(page['doc'],)).fetchone()[0]:raise ValueError('Оригінал джерела змінився. Оновіть бібліотеку.')
  saved=self.annotations({'id':page['id']});units=[]
  if a.get('use_saved') is True:
   candidates=[r for r in saved if r['kind'] in ['entry','column','line'] and not r.get('page_review_scope')]
   ids={r['id'] for r in candidates}
   units=[r for r in candidates if r.get('parent') not in ids]
   units.sort(key=lambda r:(r.get('reading_order',100000),r['rect'][0] if r['kind']=='column' else r['rect'][1],r['rect'][1],r['rect'][0]))
   if not units:raise ValueError('Спочатку збережіть межі записів або колонок.')
  else:
   scopes=[[0,0,.5,1],[.5,0,.5,1]] if a.get('spread') is True else [[0,0,1,1]]
   for i,rect in enumerate(scopes):
    ident=self.save_annotation({'page':page['id'],'data':{'kind':'entry','rect':rect,'text':'','verified':False,'reading_order':i+1,'page_review_scope':True,'label':str(i+1)}})['id'];units.append(next(r for r in self.annotations({'id':page['id']}) if r['id']==ident))
  if len(units)>500:raise ValueError('Забагато ділянок для одного завдання.')
  ident=uuid.uuid4().hex;job={'page':page['id'],'options':options,'models':models,'runtime':runtime_identity(options),'binding':self.binding(page['id']),'units':[{'annotation':r['id'],'rect':r['rect'],'state':'pending','attempts':0} for r in units],'verified':False,'created':time.time(),'spread':a.get('spread') is True,'manual_plan':a.get('use_saved') is True}
  with self.db:self.db.execute('INSERT INTO page_review_jobs(id,page,data) VALUES (?,?,?)',(ident,page['id'],json.dumps(job,ensure_ascii=False)))
  return self.page_review_status({'job':ident})
 def page_review_fork(self,a):
  previous=self.load(a['job'])
  if self.binding(previous['page'])!=previous['binding']:raise ValueError('Результат змінився. Оновіть список.')
  if any(r['state'] not in ['done','empty'] for r in previous['units']):raise ValueError('Finish the source page job before comparing models.')
  options=previous['options']|{'model':a['model']};models=fingerprint_models(options)
  if not models['recognition']:raise ValueError('Виберіть локальну модель Kraken (.mlmodel або .safetensors).')
  if models['recognition']['sha256']==previous['models']['recognition']['sha256']:raise ValueError('Для порівняння виберіть різні моделі.')
  job=previous|{'options':options,'models':models,'runtime':runtime_identity(options),'created':time.time(),'comparison_parent':a['job'],'units':[{'annotation':r['annotation'],'rect':r['rect'],'state':'pending','attempts':0,'layout_run':r['run']} for r in previous['units']]}
  ident=uuid.uuid4().hex
  with self.db:self.db.execute('INSERT INTO page_review_jobs(id,page,data) VALUES (?,?,?)',(ident,job['page'],json.dumps(job,ensure_ascii=False)))
  return self.page_review_status({'job':ident})
 def page_review_step(self,a):
  ident=a['job'];old=self.db.execute('SELECT data FROM page_review_jobs WHERE id=?',(ident,)).fetchone()
  if not old:raise ValueError('Завдання не знайдено.')
  old=old[0];job=json.loads(old)
  if self.binding(job['page'])!=job['binding'] or fingerprint_models(job['options'])!=job['models'] or runtime_identity(job['options'])!=job['runtime']:raise ValueError('Джерело, розмітка, модель або версія обробки змінилися. Створіть новий план сторінки.')
  for row in job['units']:
   if row['state']=='running':
    if alive(row.get('pid')):raise ValueError('Цю ділянку вже обробляє інший процес.')
    row.update(state='pending',error='Interrupted process; safe to resume.')
   if a.get('retry_failed') is True and row['state']=='failed':row['state']='pending'
  unit=next((r for r in job['units'] if r['state']=='pending'),None)
  if unit is None:return self.page_review_status({'job':ident})
  unit.update(state='running',pid=os.getpid(),attempts=unit['attempts']+1)
  with self.db:
   changed=self.db.execute('UPDATE page_review_jobs SET data=? WHERE id=? AND data=?',(json.dumps(job,ensure_ascii=False),ident,old)).rowcount
   if not changed:raise ValueError('Стан завдання змінився. Оновіть список.')
  started=time.perf_counter()
  try:
   options=job['options']|{'id':job['page'],'annotation':unit['annotation'],'use_saved_lines':True}
   if unit.get('layout_run'):options.update(reuse_layout_run=unit['layout_run'],use_saved_lines=False)
   result=self.recognize_region(options)
   unit.update(state='done' if result['text'].strip() else 'empty',run=result['id'],text=result['text'],lines=result['lines'],review_flags=result.get('review_flags',[]));unit.pop('error',None)
  except Exception as exc:unit.update(state='failed',error=str(exc))
  unit.update(seconds=time.perf_counter()-started);unit.pop('pid',None);self.store(ident,job)
  return self.page_review_status({'job':ident})
 def page_review_status(self,a):
  if not a.get('job'):
   row=self.db.execute('SELECT id FROM page_review_jobs WHERE page=? ORDER BY rowid DESC LIMIT 1',(a['id'],)).fetchone()
   if not row:return {'job':None,'units':[],'state':'none'}
   a=a|{'job':row['id']}
  job=self.load(a['job']);counts={s:sum(r['state']==s for r in job['units']) for s in ['pending','running','done','empty','failed']}
  stale=self.binding(job['page'])!=job['binding'];interrupted=sum(r['state']=='running' and not alive(r.get('pid')) for r in job['units']);state='stale' if stale else 'interrupted' if interrupted else 'processing' if counts['pending'] or counts['running'] else 'review'
  from PIL import Image,ImageDraw
  page=self.engine.page(job['page']);render=self.engine.render({'id':job['page'],'whole':True,'full':True});scale=min(768/render['width'],1600/render['height']);size=(max(1,round(render['width']*scale)),max(1,round(render['height']*scale)));mask=Image.new('RGBA',size,(65,65,65,65));draw=ImageDraw.Draw(mask);boxes=[]
  for unit in job['units']:
   for line in unit.get('lines',[]):
    rect=line['rect'];x,y,w,h=rect;draw.rectangle((round(x*size[0]),round(y*size[1]),round((x+w)*size[0]),round((y+h)*size[1])),fill=(0,0,0,0));boxes.append({'rect':rect,'state':'text' if line.get('text','').strip() else 'empty'})
  folder=self.engine.root/'results'/('page-review-'+a['job']);folder.mkdir(exist_ok=True);maskpath=folder/'coverage.png';png_artifact(maskpath,mask)
  text='\n\n'.join(r.get('text','') for r in job['units'])
  # Independent report with whole-page pixels beside all raw output and errors.
  image=folder/'page.png'
  if not image.exists():
   with Image.open(render['path']) as im:im.thumbnail((1400,2200));png_artifact(image,im)
  esc=html.escape;items=[]
  for i,unit in enumerate(job['units']):items.append('<h3>'+str(i+1)+' · '+esc(unit['state'])+'</h3><pre>'+esc(unit.get('error',unit.get('text','')) or '(empty)')+'</pre>')
  report=folder/'report.html';artifact(report,'<!doctype html><meta charset="utf-8"><title>Page review</title><style>body{font:16px system-ui;margin:24px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:24px}img{max-width:100%}pre{white-space:pre-wrap}</style><h1>Повна сторінка: неперевірені результати</h1><p>Сіре поза повернутими межами рядків не означає відсутності тексту. Порожні й невдалі ділянки показано явно. Цей звіт не засвідчує повноту або точність.</p><p>'+esc(state)+' · '+esc(Path(job['options']['model']).parent.name+'/'+Path(job['options']['model']).name)+' · '+esc(job['options']['mode'])+'</p><div class="grid"><div><img src="page.png"></div><div>'+''.join(items)+'</div></div>')
  result=job|{'job':a['job'],'state':state,'counts':counts,'interrupted_units':interrupted,'text':text,'boxes':boxes,'coverage_path':str(maskpath),'report':str(report),'coverage_complete':False,'stale':stale,'policy':'Input scopes and returned line boxes are distinct. Outside returned boxes is unassessed; full-page input does not prove full transcription. Raw results never overwrite manual text.'}
  artifact(folder/'report.json',json.dumps(result,ensure_ascii=False,indent=2));return result
