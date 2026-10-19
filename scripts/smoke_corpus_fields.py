"""Isolated real-photo UI checks; no historical ground truth or inference."""
import json,sqlite3,subprocess,os,sys,hashlib
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.historical_reading import HistoricalTools
from backend.archivereader.review_corpus import CorpusTools

def main():
 rows=[];app=ROOT/'bin/Release/net10.0-windows/ArchiveReader.exe'
 for locale in ['uk','en','pl','cs']:
  lib=ROOT/'test-output/corpus-fields-ui'/locale/'library';lib.mkdir(parents=True,exist_ok=True);a=sqlite3.connect(ROOT/'test-output/historical-ui'/locale/'library/archive.sqlite');b=sqlite3.connect(lib/'archive.sqlite');a.backup(b);a.close();b.close();e=Engine(lib);page=e.db.execute('SELECT id FROM pages LIMIT 1').fetchone()['id'];HistoricalTools(e).save_annotation({'page':page,'annotation':'corpus-fields-draft-entry','data':{'kind':'entry','rect':[.07,.1,.43,.125],'text':'','verified':False,'note':'Actual photo region for empty draft UI only; no reference transcription.'}});CorpusTools(e).corpus_import({'id':page});e.settings({'values':{'uiLanguage':locale}});originals={r['path']:r['sha'] for r in e.db.execute('SELECT path,sha FROM documents')};e.db.close();env=os.environ.copy();env.update(ARCHIVEREADER_DATA=str(lib),ARCHIVEREADER_LANGUAGE=locale,ARCHIVEREADER_PYTHON=sys.executable);env.pop('ARCHIVEREADER_SMOKE_COMPARE',None);startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0;run=subprocess.run([str(app),'--smoke-test','--smoke-corpus','--smoke-workbench'],env=env,startupinfo=startup,timeout=120);assert run.returncode==0
  corpus=list((lib/'corpus-ui').glob('*.png'));workbench=list((lib/'workbench-ui').glob('*.png'));assert len(corpus)==4 and len(workbench)>=9,(corpus,workbench)
  for path in corpus+workbench:
   with Image.open(path) as image:image.verify()
  for path,expected in originals.items():
   with Path(path).open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==expected
  db=sqlite3.connect(lib/'archive.sqlite');refs=[json.loads(r[0]) for r in db.execute('SELECT data FROM entry_references')];db.close();assert all(not r['human_verified'] for r in refs);rows.append({'locale':locale,'exit_code':run.returncode,'corpus_captures':len(corpus),'workbench_captures':len(workbench),'source_unchanged':True,'historical_gt_created':False});print(json.dumps(rows[-1]),flush=True)
 out=ROOT/'test-output/corpus-fields-ui/report.json';out.write_text(json.dumps({'cases':rows,'policy':'Actual supplied photograph, empty unverified entry drafts only. No ML inference, no claimed historical field accuracy.'},indent=2),'utf-8')
if __name__=='__main__':main()
