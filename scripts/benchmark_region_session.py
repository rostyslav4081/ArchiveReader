"""Actual persistent JSONL worker, supplied source crop, forced inference twice."""
import json,subprocess,sys,time,sqlite3,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 lib=ROOT/'test-output/region-cache-real/library';db=sqlite3.connect(lib/'archive.sqlite');r=next(r for r in db.execute('select page,id,data from annotations') if json.loads(r[2]).get('kind')=='line');before=list(db.execute('select * from annotations'));sources=list(db.execute('select path,sha from documents'));db.close()
 folder=ROOT/'test-output/region-cache-real';rows=[]
 with (folder/'persistent-stderr.log').open('w',encoding='utf-8') as err:
  worker=subprocess.Popen([sys.executable,'-m','backend.archivereader.model_session'],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,text=True,encoding='utf-8')
  def call(command,**args):
   request={'request_id':str(time.time_ns()),'root':str(lib),'command':command,**args};worker.stdin.write(json.dumps(request)+'\n');worker.stdin.flush();reply=json.loads(worker.stdout.readline());assert reply['ok'],reply;return reply
  try:
   for n in range(2):
    start=time.perf_counter();reply=call('recognize_region',id=r[0],annotation=r[1],model=str(ROOT/'models/german-handwriting/model.mlmodel'),force=True,mode='text');result=reply['result'];rows.append({'seconds':time.perf_counter()-start,'text':result['text'],'run':result['id'],'transport':result['identity']['transport'],'pid':reply['session']['pid']});print(json.dumps(rows[-1]),flush=True)
   stats=call('session_status')['result'];assert rows[0]['pid']==rows[1]['pid'];assert rows[0]['run']!=rows[1]['run'];assert rows[0]['text']==rows[1]['text'];assert stats['cache']['hits']>=1
   old=json.loads((folder/'report.json').read_text('utf-8'))['result']['text'];assert rows[0]['text']==old,(rows[0]['text'],old)
   db=sqlite3.connect(lib/'archive.sqlite');assert before==list(db.execute('select * from annotations'));db.close()
   for path,sha in sources:
    with Path(path).open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==sha
   report={'forced_inference':rows,'worker':stats,'same_text_as_previous_cli':True,'annotations_unchanged':True,'originals_unchanged':True,'accuracy_measured':False};(folder/'persistent-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
  finally:
   worker.stdin.close()
   try:worker.wait(timeout=15)
   except subprocess.TimeoutExpired:worker.terminate();worker.wait(timeout=10)
if __name__=='__main__':main()
