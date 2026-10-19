"""Run latest desktop import/view on the user's real PDFs and PERO photo XML.
Only isolated test-output libraries are used; source checksums must stay unchanged.
No OCR/HTR model is executed by these UI smoke checks.
"""
import hashlib,json,os,sqlite3,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(path):
 with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
if __name__=='__main__':
 app=ROOT/'bin/Release/net10.0-windows/ArchiveReader.exe';report={'app_sha256':sha(app),'dll_sha256':sha(app.with_suffix('.dll')),'cases':[]};stamp=time.strftime('%Y%m%d-%H%M%S')
 cases=[('pdf-18',Path.home()/'Downloads/19-18-69_001.pdf',18,None),('pdf-59',Path.home()/'Downloads/001_compressed.pdf',59,None),('pero-photo-case002',ROOT/'test-output/integrations/inputs/case-002.png',1,ROOT/'test-output/integrations/pero/raw/case-002.page.xml')]
 for name,source,expected,xml in cases:
  folder=ROOT/'test-output'/('ui-real-import-'+name+'-'+stamp);folder.mkdir(parents=True,exist_ok=True);before=sha(source);env=os.environ.copy();env.update(ARCHIVEREADER_DATA=str(folder),ARCHIVEREADER_LANGUAGE='uk',ARCHIVEREADER_PYTHON=sys.executable)
  if xml:env['ARCHIVEREADER_SMOKE_XML']=str(xml)
  startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
  subprocess.run([str(app),'--smoke-import',str(source)],env=env,startupinfo=startup,check=True,timeout=150)
  result=json.loads((folder/'smoke-import.json').read_text('utf-8'));assert result['pages']==expected,(name,result)
  subprocess.run([str(app),'--smoke-test']+(['--smoke-interchange'] if xml else []),env=env,startupinfo=startup,check=True,timeout=150)
  assert (folder/'window.png').is_file(),name
  if xml:assert (folder/'interchange-ui/preview.png').is_file()
  after=sha(source);assert after==before,name
  db=sqlite3.connect(folder/'archive.sqlite');count=db.execute('SELECT COUNT(*) FROM pages').fetchone()[0];statuses=dict(db.execute('SELECT status,COUNT(*) FROM pages GROUP BY status'));db.close();assert count==expected
  report['cases'].append({'name':name,'source':str(source),'source_sha256_before':before,'source_sha256_after':after,'original_unchanged':before==after,'import':result,'database_pages':count,'status_counts':statuses,'library':str(folder),'main_ui':str(folder/'window.png'),'interchange_ui':str(folder/'interchange-ui/preview.png') if xml else None,'models_run':False});print(name,'OK',count,'original unchanged',flush=True)
 output=ROOT/'test-output'/('real-ui-proof-'+stamp+'.json');output.write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8');print(output,flush=True)
