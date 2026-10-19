"""Supplied real photo, saved line geometry and bounded image variants; no GT."""
import hashlib,json,os,sqlite3,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.layout import LayoutTools

def main():
 out=ROOT/'test-output/layout-workflow-real';lib=out/'library';lib.mkdir(parents=True,exist_ok=True)
 source=sqlite3.connect(ROOT/'test-output/region-cache-real/library/archive.sqlite');dest=sqlite3.connect(lib/'archive.sqlite');source.backup(dest);source.close();dest.close()
 os.environ['ARCHIVEREADER_MODEL_SESSION']='1';e=Engine(lib);l=LayoutTools(e);p=e.db.execute('SELECT id FROM pages LIMIT 1').fetchone()[0];lines=[r for r in l.annotations({'id':p}) if r['kind']=='line'][:3];assert len(lines)>=2
 entry=l.save_annotation({'page':p,'data':{'kind':'entry','rect':[0,0,1,1],'text':'','note':'Functional test only. Saved draft line bounds, not verified reference text.'}})['id']
 for n,row in enumerate(lines):l.save_annotation({'page':p,'annotation':row['id'],'data':row|{'parent':entry,'reading_order':n+1,'verified':False,'suggested':False}})
 before=l.annotations({'id':p});rows=[]
 for variant in ['original','upscale2','contrast']:
  start=time.perf_counter();r=l.recognize_region({'id':p,'annotation':entry,'model':str(ROOT/'models/german-handwriting/model.mlmodel'),'mode':'text','variant':variant});assert len(r['child_runs'])==len(lines);assert len(r['lines'])==len(lines);assert [x['id'] for x in r['saved_lines']]==[x['id'] for x in lines];assert l.annotations({'id':p})==before
  applied=l.region_recognition_apply({'id':p,'run':r['id']});assert applied['added']==0;assert l.annotations({'id':p})==before
  rows.append({'variant':variant,'seconds':time.perf_counter()-start,'run':r['id'],'text':r['text'],'child_runs':r['child_runs'],'conflicts':len(applied['conflicts']),'manual_geometry_reused':True});print(json.dumps(rows[-1],ensure_ascii=False),flush=True)
 originals=list(e.db.execute('SELECT path,sha FROM documents'))
 for path,sha in originals:
  with Path(path).open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==sha
 quality=l.layout_quality({'id':p});state=l.book_quality_map({'id':p});e.db.close()
 # Check status maps across all previously supplied original PDF books on an isolated snapshot.
 maps=out/'maps';maps.mkdir(exist_ok=True);source=sqlite3.connect(ROOT/'test-output/historical-all-documents/library/archive.sqlite');dest=sqlite3.connect(maps/'archive.sqlite');source.backup(dest);source.close();dest.close();e=Engine(maps);l=LayoutTools(e);books=[]
 for doc in e.db.execute("SELECT id,name,path,sha FROM documents WHERE lower(name) LIKE '%.pdf'").fetchall():
  page=e.db.execute('SELECT id FROM pages WHERE doc=? ORDER BY num LIMIT 1',(doc['id'],)).fetchone()[0];offset=0;count=0
  while True:
   report=l.book_quality_map({'id':page,'offset':offset});assert all(not r['coverage_complete'] for r in report['pages']);count+=len(report['pages'])
   if report['next_offset'] is None:break
   offset=report['next_offset']
  with Path(doc['path']).open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==doc['sha']
  books.append({'document':doc['name'],'pages':count,'original_unchanged':True});print(json.dumps(books[-1],ensure_ascii=False),flush=True)
 e.db.close();(out/'report.json').write_text(json.dumps({'variants':rows,'quality':quality,'photo_state':state,'pdf_maps':books,'annotations_unchanged':True,'ground_truth_created':False,'accuracy_measured':False,'policy':'Actual supplied photo and saved draft line bounds; recognition remains incorrect/unverified. PDF tests exercise status maps only, not new PDF transcription.'},ensure_ascii=False,indent=2),'utf-8')
if __name__=='__main__':main()
