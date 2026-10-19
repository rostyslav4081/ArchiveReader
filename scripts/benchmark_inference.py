"""Compare cold and reused local-model inference on one unchanged real line crop."""
from pathlib import Path
import argparse,json,os,subprocess,sys,time,threading
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.workbench import Workbench

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--polish',action='store_true');parser.add_argument('--persistent-only',action='store_true');args=parser.parse_args()
 out=ROOT/('test-output/performance-inference-trocr' if args.polish else 'test-output/performance-inference');out.mkdir(parents=True,exist_ok=True);e=Engine(out/'library');w=Workbench(e)
 e.import_file({'path':str(ROOT/'test-output/htr-repair-20261015/church-books.png')});page=e.list_pages({})[0]['id']
 rows=w.annotations({'id':page});region=rows[0]['id'] if rows else w.save_annotation({'page':page,'data':{'kind':'line','rect':[0,0,1,1],'text':'','verified':False}})['id'];e.db.close()
 request={'root':str(out/'library'),'command':'compare_regions','id':page,'annotation':region,'models':[{'name':'Mannheim','engine':'kraken','path':str(ROOT/'models/german-handwriting/model.mlmodel')},{'name':'Bohemica','engine':'kraken','path':str(ROOT/'models/bohemica/model.mlmodel')}]}
 if args.polish:request['models'][1]={'name':'Polish TrOCR','engine':'trocr','path':str(ROOT/'models/polish-metrical-experimental')}
 env=os.environ.copy();env['PYTHONUTF8']='1';env.pop('ARCHIVEREADER_MODEL_SESSION',None);env['TEMP']=str(out.resolve());env['TMP']=str(out.resolve())
 si=subprocess.STARTUPINFO();si.dwFlags|=subprocess.STARTF_USESHOWWINDOW;si.wShowWindow=0
 results=[]
 def reduced(reply):return [{k:v.get('text',v.get('error')) for k,v in row['results'].items()} for row in reply['result']['rows']]
 for n in range(0 if args.persistent_only else 2):
  start=time.monotonic();r=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'backend/archivereader/engine.py')],input=json.dumps(request),capture_output=True,text=True,encoding='utf8',env=env,startupinfo=si,timeout=180);reply=json.loads(r.stdout)
  if not reply['ok']:raise RuntimeError(reply['error'])
  results.append({'mode':'cold','seconds':time.monotonic()-start,'outputs':reduced(reply)})
 with (out/'session-stderr.log').open('w',encoding='utf8') as log:
  process=subprocess.Popen([sys.executable,'-X','utf8','-u',str(ROOT/'backend/archivereader/model_session.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,encoding='utf8',env=env,startupinfo=si)
  watchdog=threading.Timer(600,process.kill);watchdog.start()
  try:
   for n in range(2):
    start=time.monotonic();process.stdin.write(json.dumps(request|{'request_id':str(n)})+'\n');process.stdin.flush();reply=json.loads(process.stdout.readline())
    if not reply['ok']:raise RuntimeError(reply['error'])
    results.append({'mode':'persistent-first' if n==0 else 'persistent-warm','seconds':time.monotonic()-start,'outputs':reduced(reply)})
   process.stdin.write(json.dumps({'request_id':'stats','command':'session_status','root':request['root']})+'\n');process.stdin.flush();stats=json.loads(process.stdout.readline())
  finally:watchdog.cancel();process.stdin.close();process.wait(timeout=30);process.stdout.close()
 same=all(r['outputs']==results[0]['outputs'] for r in results);report={'scope':'One real handwriting heading crop, two local models; latency/cache test, not recognition accuracy or general throughput','runs':results,'same_outputs':same,'cache':stats['result']};(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps({'same_outputs':same,'runs':[{k:v for k,v in r.items() if k!='outputs'} for r in results],'cache':stats['result']},ensure_ascii=True))
 if not same:raise RuntimeError('Recognition changed between cold and persistent execution')

if __name__=='__main__':main()
