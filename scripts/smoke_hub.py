"""Synthetic five-tab research hub smoke in all four UI languages."""
import json,os,subprocess,sys
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.research_hub import HubTools
if __name__=='__main__':
 output=ROOT/'test-output/ui-research-hub';output.mkdir(parents=True,exist_ok=True)
 source=output/'synthetic.png';im=Image.new('RGB',(1000,1400),'#fffdf0');ImageDraw.Draw(im).text((90,160),'SYNTHETIC TEST\nJoannes Skowyra\n14 Martii 1838, domus 34\nNot an archival document.',fill='black',font=ImageFont.truetype('C:/Windows/Fonts/times.ttf',38),spacing=20);im.save(source)
 for language in ['uk','en','pl','cs']:
  folder=output/language;e=Engine(folder);e.import_file({'path':str(source)});page=e.list_pages({})[0]['id'];h=HubTools(e)
  line=h.save_annotation({'page':page,'annotation':'synthetic-hub-line','data':{'kind':'line','rect':[.08,.1,.8,.15],'field':'person'}})['id']
  h.book_save({'book':'synthetic-book','name':'Synthetic test book','items':[{'page':page},{'label':'folio 2 missing','note':'Synthetic explicit gap'}]})
  h.book_profile({'id':page,'values':{'languages':'Latin','years':'1838','script':'synthetic','split':'test','notes':'UI test only'}})
  e.db.execute('INSERT OR REPLACE INTO records VALUES (?,?,?)',('synthetic-record',page,json.dumps({'person':'Joannes Skowyra','place':'Lipivtsi','date':'1838','house':'34','related1':'Paulus','verified':False})))
  report=folder/'results/hub-synthetic';report.mkdir(parents=True,exist_ok=True);(report/'report.json').write_text(json.dumps({'rows':[{'id':line,'rect':[.08,.1,.8,.15],'results':{'A':{'text':'Joannes Skowyra'},'B':{'text':'Joannes Skowira'}},'disagreement':True}]}),'utf-8')
  e.db.execute('INSERT OR REPLACE INTO comparison_runs(id,doc,path) VALUES (?,?,?)',('synthetic-hub',e.page(page)['doc'],str(report.resolve())));e.db.commit();e.db.close()
  env=os.environ.copy();env.update(ARCHIVEREADER_DATA=str(folder),ARCHIVEREADER_LANGUAGE=language,ARCHIVEREADER_PYTHON=sys.executable)
  startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
  subprocess.run([str(ROOT/'bin/Release/net10.0-windows/ArchiveReader.exe'),'--smoke-test','--smoke-hub'],env=env,startupinfo=startup,check=True,timeout=90)
  if not all((folder/'hub-ui'/f'tab-{i}.png').is_file() for i in range(5)):raise RuntimeError('Missing hub UI capture: '+language)
  print(language,'OK',flush=True)
