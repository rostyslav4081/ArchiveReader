"""Isolated real-library compatibility sweep, never an accuracy benchmark."""
import hashlib,html,json,sqlite3,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.historical_reading import HistoricalTools

def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
 source=ROOT/'test-output/htr-lab-20261015/library';out=ROOT/'test-output/historical-all-documents';out.mkdir(parents=True,exist_ok=True);target=out/'library';target.mkdir(exist_ok=True)
 original=sqlite3.connect(source/'archive.sqlite');copy=sqlite3.connect(target/'archive.sqlite');original.backup(copy);copy.close();original.close()
 e=Engine(target);h=HistoricalTools(e);docs=[dict(r) for r in e.db.execute('SELECT * FROM documents')];before={d['id']:sha(d['path']) for d in docs};pages=[dict(r) for r in e.db.execute('SELECT id,doc,num FROM pages ORDER BY doc,num')];rows=[];started=time.monotonic()
 for i,p in enumerate(pages):
  row=dict(page=p['id'],document=p['doc'],source_page=p['num']+1);t=time.monotonic()
  try:
   state=h.historical_get({'page':p['id']});render=e.render({'id':p['id'],'whole':True,'preprocess':'original'});row['render']=render['path']
   regions=[r for r in state['regions'] if r['kind'] in ('line','entry')];row['existing_reading_regions']=len(regions)
   if not regions:
    ident=h.save_annotation({'page':p['id'],'data':{'kind':'line','rect':[.1,.1,.8,.1],'text':'','verified':False,'note':'Compatibility probe only: arbitrary rectangle, not detected text or ground truth.'}})['id'];regions=[{'id':ident}];row['test_rectangle_only']=True
   results=[h.historical_analyze({'page':p['id'],'annotation':r['id']}) for r in regions];row['analyzed_regions']=len(results);assert all(r['gt_eligible'] is False for r in results)
   structure=h.historical_structure_propose({'page':p['id']});row['grid_proposals']=len(structure['candidates']);assert structure['saved'] is False;row['status']='ok'
  except Exception as ex:row.update(status='error',error=repr(ex))
  row['seconds']=round(time.monotonic()-t,3);rows.append(row)
  if (i+1)%20==0 or i+1==len(pages):
   (out/'checkpoint.json').write_text(json.dumps({'processed':i+1,'total':len(pages),'rows':rows},ensure_ascii=False,indent=2),'utf-8');print(json.dumps({'processed':i+1,'total':len(pages),'errors':sum(r['status']=='error' for r in rows)}),flush=True)
 checks=[{'id':d['id'],'name':Path(d['path']).name,'unchanged':sha(d['path'])==before[d['id']]} for d in docs];report={'policy':'Compatibility only. Arbitrary empty probe rectangles are NOT detected lines, transcriptions or accuracy references. No inference/model training. Original library DB untouched; isolated SQLite snapshot and caches only.','documents':len(docs),'pages':len(pages),'errors':sum(r['status']=='error' for r in rows),'seconds':time.monotonic()-started,'sources':checks,'rows':rows};(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
 text='<meta charset="utf-8"><title>Перевірка всіх документів</title><h1>Сумісність історичного читання</h1><p>Це перевірка роботи, а не точності прочитання. Порожні тестові ділянки не є розпізнаними рядками.</p><pre>'+html.escape(json.dumps({k:v for k,v in report.items() if k not in ('rows','sources')},ensure_ascii=False,indent=2))+'</pre><table><tr><th>Документ</th><th>Сторінка PDF (позиція)</th><th>Стан</th><th>Помилка</th></tr>'
 names={d['id']:Path(d['path']).name for d in docs}
 for r in rows:
  preview='<a href="'+html.escape(Path(r['render']).as_uri(),quote=True)+'">Скан</a>' if r.get('render') else ''
  text+='<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in (names[r['document']],r['source_page'],r['status'],r.get('error','')))+'<td>'+preview+'</td></tr>'
 (out/'report.html').write_text(text+'</table>','utf-8');e.db.close();print(json.dumps({k:v for k,v in report.items() if k not in ('rows','sources')}),flush=True)
if __name__=='__main__':main()
