"""Whole original pages: actual inference, resumable jobs, explicit failures/time limits."""
import concurrent.futures,hashlib,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.page_review import PageReviewTools
OUT=ROOT/'test-output/full-page-review';LIB=OUT/'library'
CASES=[('handwritten','C:/Users/inst/AppData/Local/Temp/codex-clipboard-f1f3d53a-6a09-48a2-b4c8-7e377c1f5ac6.png',0,False),('table','C:/Users/inst/Desktop/родовід/output/pdf/AGAD_301_331_Lipowce_Majdan_births_1800-1834.pdf',20,False),('spread','C:/Users/inst/Desktop/родовід/Гологори_римо-католицькі_смерті_1755-1795_AGAD_301_334.pdf',4,True),('damaged','C:/Users/inst/AppData/Local/Temp/codex-clipboard-b84d97be-72f2-4546-812a-e85e7f85775d.png',0,False)]
def main():
 OUT.mkdir(parents=True,exist_ok=True);e=Engine(LIB);t=PageReviewTools(e);jobs=[]
 for name,path,index,spread in CASES:
  imported=e.import_file({'path':path});page=e.db.execute('SELECT id FROM pages WHERE doc=? AND num=?',(imported['id'],index)).fetchone()[0]
  job=t.page_review_start({'id':page,'model':str(ROOT/'models/bohemica/model.mlmodel'),'mode':'columns','spread':spread});jobs.append({'case':name,'source':path,'frame':index+1,'job':job['job'],'page':page})
 e.db.close();(OUT/'jobs.json').write_text(json.dumps(jobs,ensure_ascii=False,indent=2),'utf-8');rows=[]
 for case in jobs:
  start=time.perf_counter();timed_out=False
  with (OUT/(case['case']+'-stderr.log')).open('w',encoding='utf-8') as err:
   worker=subprocess.Popen([sys.executable,'-X','utf8','-m','backend.archivereader.model_session'],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,text=True,encoding='utf-8');pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
   try:
    for n in range(2 if case['case']=='spread' else 1):
     request={'request_id':str(time.time_ns()),'root':str(LIB),'command':'page_review_step','job':case['job']};worker.stdin.write(json.dumps(request)+'\n');worker.stdin.flush()
     try:raw=pool.submit(worker.stdout.readline).result(timeout=180)
     except concurrent.futures.TimeoutError:timed_out=True;worker.kill();worker.wait(timeout=10);break
     reply=json.loads(raw);assert reply['ok'],reply
     print(json.dumps({'case':case['case'],'step':n+1,'counts':reply['result']['counts'],'seconds':time.perf_counter()-start}),flush=True)
   finally:
    worker.stdin.close()
    try:worker.wait(timeout=10)
    except subprocess.TimeoutExpired:worker.kill();worker.wait(timeout=10)
    pool.shutdown(wait=False,cancel_futures=True)
  e=Engine(LIB);t=PageReviewTools(e);report=t.page_review_status({'job':case['job']});assert not report['coverage_complete'];actual=e.db.execute('SELECT d.sha FROM documents d JOIN pages p ON p.doc=d.id WHERE p.id=?',(case['page'],)).fetchone()[0]
  with Path(case['source']).open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==actual
  assert all(r['rect']==[0,0,1,1] for r in report['units']) if case['case']!='spread' else report['units'][0]['rect']==[0,0,.5,1] and report['units'][1]['rect']==[.5,0,.5,1]
  rows.append(case|{'counts':report['counts'],'state':report['state'],'timed_out':timed_out,'seconds':time.perf_counter()-start,'report':report['report'],'returned_boxes':len(report['boxes']),'original_unchanged':True});e.db.close();(OUT/'report.json').write_text(json.dumps({'cases':rows,'policy':'Whole original pages, no probe ROI. Full-page model inputs do not establish text completeness. Failed/interrupted/empty cases retained. No human ground truth or accuracy claim.'},ensure_ascii=False,indent=2),'utf-8');print(json.dumps(rows[-1],ensure_ascii=False),flush=True)
if __name__=='__main__':main()
