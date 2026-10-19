"""Engine-independent review hints; never corrections, labels or model training."""
import importlib.util,json,re,shutil
from pathlib import Path
from collections import Counter

def review_flags(value,fields=None):
 text=str(value or '')[:16000];flags=[]
 if not text.strip():return ['empty_output']
 words=re.findall(r'\w+',text.casefold())[:2000]
 if len(text.strip())<3:flags.append('short_fragment')
 if any(count>=3 for count in Counter(tuple(words[n:n+3]) for n in range(max(0,len(words)-2))).values()) or any(len(word)>2 and count>=6 for word,count in Counter(words).items()):flags.append('repeated_text')
 if re.search(r'\d',text):flags.append('check_dates_numbers')
 for field in ['person','related1','related2','house','date']:
  value=(fields or {}).get(field)
  if value and str(value).strip().casefold() in text.casefold():flags.append('check_'+field)
 return sorted(set(flags))

CAPABILITIES={
 'kraken':{'training':'kraken_copy','line_geometry':True,'comparison':True},
 'trocr':{'training':'export_only','line_geometry':True,'comparison':True},
 'tesseract':{'training':'export_only','line_geometry':True,'comparison':False},
 'paddle':{'training':'export_only','line_geometry':True,'comparison':False}}

class RecognitionWorkflow:
 def __init__(self,engine):self.engine=engine
 def workflow_model_status(self,a):
  engine=a.get('engine','kraken');path=Path(a['model']);roots=[path];components=[]
  if engine not in CAPABILITIES:raise ValueError('Unsupported recognition engine.')
  if engine=='paddle' and path.is_file():
   try:from .paddle_local import package
   except ImportError:from paddle_local import package
   config,root=package(path);roots.extend(root/config[k] for k in ['detector_path','recognizer_path']);components.append({'name':'Paddle Python','available':(root/config['runtime']).is_file()})
  elif engine=='tesseract':components.append({'name':'Tesseract','available':bool(shutil.which(a.get('executable','tesseract')))})
  else:
   for name in (['kraken'] if engine=='kraken' else ['torch','transformers']):components.append({'name':name,'available':importlib.util.find_spec(name) is not None})
  files={}
  for root in roots:
   for file in ([root] if root.is_file() else root.rglob('*') if root.is_dir() else []):
    if file.is_file():files[str(file.resolve())]=file.stat().st_size
    if len(files)>10000:break
  return {'installed':path.exists(),'configured':path.exists() and all(c['available'] for c in components) and all(r.exists() for r in roots),'local_bytes':sum(files.values()),'size_truncated':len(files)>10000,'components':components,'capabilities':CAPABILITIES[engine],'book_validation':'not_assessed_here','policy':'Configured files/components do not establish successful inference or accuracy. No model is loaded.'}
 def workflow_status(self,a):
  try:
   from .historical_reading import HistoricalTools
   from .tutor import TutorTools
  except ImportError:
   from historical_reading import HistoricalTools
   from tutor import TutorTools
  page=self.engine.details({'id':a['id']});historical=HistoricalTools(self.engine).historical_get({'page':a['id']});tutor=TutorTools(self.engine);lessons=tutor.tutor_lessons({'id':a['id']})
  rows=[];records=page['records'];fields={key:r[key] for r in records for key in ['person','related1','related2','house','date'] if r.get(key)}
  for n,line in enumerate(page['lines'][:500]):
   flags=review_flags(line.get('text'),fields)
   if flags:rows.append({'kind':'page_line','index':n,'text':line.get('text',''),'flags':flags,'human_verified':bool(line.get('verified'))})
  for region in historical['regions'][:500]:
   if region.get('kind') not in ['line','entry','column']:continue
   flags=review_flags(region.get('text'),fields) if str(region.get('text','')).strip() else ['untranscribed_annotation']
   if flags:rows.append({'kind':'annotation','annotation':region['id'],'text':region.get('text',''),'flags':flags,'human_verified':bool(region.get('verified'))})
  tables={r[0] for r in self.engine.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  if 'region_recognition' in tables:
   try:from .layout import fingerprint
   except ImportError:from layout import fingerprint
   regions={r['id']:{k:v for k,v in r.items() if k!='region_signature'} for r in historical['regions']}
   for stored in self.engine.db.execute('SELECT id,annotation,data FROM region_recognition WHERE page=? ORDER BY rowid DESC LIMIT 50',(page['id'],)):
    data=json.loads(stored['data'])
    if data.get('source_sha256')!=historical['source']['source_sha256'] or stored['annotation'] not in regions or data.get('snapshot')!=fingerprint(regions[stored['annotation']]):continue
    flags=review_flags(data.get('text'),fields)
    if flags:rows.append({'kind':'model_result','annotation':stored['annotation'],'run':stored['id'],'text':data.get('text',''),'flags':flags,'human_verified':False})
  return {'page':page['id'],'profile':historical['profile'],'writer_exemplars':sum(not r['stale'] and r.get('checked',False) for r in historical['exemplars']),'examples':{'confirmed':sum(r['verified'] and not r['stale'] for r in lessons),'drafts':sum(not r['verified'] for r in lessons),'stale':sum(r['stale'] for r in lessons)},'split':tutor.tutor_role({'id':a['id']}).get('split',''),'capabilities':CAPABILITIES,'risks':rows,'truncated':len(page['lines'])>500 or len(historical['regions'])>500,'policy':'Advisory review only. Shared book/source annotations and human examples are independent of recognition models. No inference, promotion, text replacement or training.'}
