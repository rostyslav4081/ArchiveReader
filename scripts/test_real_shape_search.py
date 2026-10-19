"""Real user photo diagnostic; no OCR inference or reference transcription."""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine,parse_alto
from backend.archivereader.shape_search import ShapeSearch
from PIL import Image
source=Path('C:/Users/inst/AppData/Local/Temp/codex-clipboard-bf4c0450-6a75-45b7-8ea7-c15752145102.png')
out=ROOT/'test-output/shape-search-real';e=Engine(out/'library');doc=e.import_file({'path':str(source)});page=e.db.execute('select id from pages where doc=?',(doc['id'],)).fetchone()[0];s=ShapeSearch(e)
with Image.open(source) as image:width,height=image.size
if not s.annotations({'id':page}):
 for n,line in enumerate(parse_alto(ROOT/'test-output/accuracy-improvement/polish-other-page-medium.alto.xml')):
  x,y,w,h=line['box']
  if w>5 and h>5:s.save_annotation({'page':page,'data':{'kind':'line','rect':[x/width,y/height,min(w,width-x)/width,min(h,height-y)/height],'text':line['text'],'verified':False,'reading_order':n+1}})
before=s.annotations({'id':page});start=time.perf_counter();r=s.shape_search({'id':page,'rect':[326/width,171/height,48/width,42/height]});assert s.annotations({'id':page})==before
(out/'summary.json').write_text(json.dumps({'seconds':time.perf_counter()-start,'scanned_regions':r['scanned_regions'],'windows':r['windows'],'matches':len(r['results']),'report':r['report'],'original_annotations_unchanged':True,'accuracy_measured':False},ensure_ascii=False,indent=2),'utf-8');print((out/'summary.json').read_text('utf-8'))
