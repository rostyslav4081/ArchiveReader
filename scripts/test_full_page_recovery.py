"""Genuine interruption of an owned OCR worker, then resume without redoing left half."""
import concurrent.futures,json,sqlite3,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.page_review import PageReviewTools
OUT=ROOT/'test-output/full-page-recovery';LIB=OUT/'library';LIB.mkdir(parents=True,exist_ok=True)
def main():
 src=sqlite3.connect(ROOT/'test-output/full-page-review/library/archive.sqlite');dst=sqlite3.connect(LIB/'archive.sqlite');src.backup(dst);src.close();dst.close();e=Engine(LIB);t=PageReviewTools(e);cases=json.loads((ROOT/'test-output/full-page-review/jobs.json').read_text('utf-8'));page=next(c['page'] for c in cases if c['case']=='spread');job=t.page_review_start({'id':page,'model':str(ROOT/'models/bohemica/model.mlmodel'),'mode':'columns','spread':True});ident=job['job'];e.db.close()
 err=(OUT/'worker.log').open('w',encoding='utf-8');pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
 def worker():return subprocess.Popen([sys.executable,'-X','utf8','-m','backend.archivereader.model_session'],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,text=True,encoding='utf-8')
 def send(w):w.stdin.write(json.dumps({'request_id':str(time.time_ns()),'root':str(LIB),'command':'page_review_step','job':ident})+'\n');w.stdin.flush()
 first=worker()
 try:
  send(first);reply=json.loads(pool.submit(first.stdout.readline).result(timeout=180));assert reply['ok'],reply;left=reply['result']['units'][0]['run'];assert reply['result']['counts']['done']==1;print('Left half saved; starting and interrupting right half.',flush=True)
  send(first);time.sleep(5);first.kill();first.wait(timeout=10)
 finally:
  first.stdin.close()
  if first.poll() is None:first.kill();first.wait(timeout=10)
 e=Engine(LIB);t=PageReviewTools(e);interrupted=t.page_review_status({'job':ident});assert interrupted['counts']['done']==1 and interrupted['interrupted_units']==1;assert interrupted['units'][0]['run']==left;e.db.close();second=worker()
 try:
  send(second);reply=json.loads(pool.submit(second.stdout.readline).result(timeout=180));assert reply['ok'],reply;final=reply['result'];assert final['counts']['done']==2;assert final['units'][0]['run']==left;assert final['units'][0]['attempts']==1 and final['units'][1]['attempts']==2
  (OUT/'report.json').write_text(json.dumps({'job':ident,'interrupted_state':interrupted['state'],'left_run_preserved':True,'attempts':[r['attempts'] for r in final['units']],'counts':final['counts'],'report':final['report'],'accuracy_measured':False},ensure_ascii=False,indent=2),'utf-8');print(json.dumps({'counts':final['counts'],'attempts':[r['attempts'] for r in final['units']],'left_run_preserved':True}),flush=True)
 finally:
  second.stdin.close()
  try:second.wait(timeout=10)
  except subprocess.TimeoutExpired:second.kill();second.wait(timeout=10)
  err.close();pool.shutdown(wait=False,cancel_futures=True)
if __name__=='__main__':main()
