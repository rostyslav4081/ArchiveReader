"""Read-only source corpus test. All imports, OCR outputs and reports stay in ignored test-output/."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import pymupdf
from PIL import Image
import psutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine


def digest(path):
    with path.open('rb') as source: return hashlib.file_digest(source,'sha256').hexdigest()


def recognize(root, page, output):
    request={'command':'recognize','root':str(root),'id':page['id'],'engine':'kraken',
             'executable':str(ROOT/'.venv'/'Scripts'/'kraken.exe'),
             'model':str(ROOT/'models'/'kraken-ppocrv6-tiny'/'tiny.safetensors'),'timeout':300}
    env=os.environ.copy(); env['PYTHONUTF8']='1'
    start=time.monotonic(); peak=0
    with (output/'worker-output.json').open('w',encoding='utf-8') as stdout, (output/'worker-error.log').open('w',encoding='utf-8') as stderr:
        process=subprocess.Popen([sys.executable,'-X','utf8',str(ROOT/'backend'/'archivereader'/'engine.py')],stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,env=env,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        process.stdin.write(json.dumps(request)); process.stdin.close()
        while process.poll() is None:
            try:
                parent=psutil.Process(process.pid)
                total=parent.memory_info().rss
                for child in parent.children(recursive=True):
                    try: total+=child.memory_info().rss
                    except psutil.Error: pass
                peak=max(peak,total)
            except psutil.Error: pass
            if time.monotonic()-start>340:
                for child in psutil.Process(process.pid).children(recursive=True):
                    try: child.kill()
                    except psutil.Error: pass
                process.kill(); process.wait(); raise TimeoutError('Worker exceeded 340 seconds')
            time.sleep(0.25)
    result=json.loads((output/'worker-output.json').read_text(encoding='utf-8'))
    return result | {'seconds':round(time.monotonic()-start,2),'peak_process_tree_rss_MB':round(peak/1024**2,1)}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('corpus',type=Path)
    parser.add_argument('--image-folder',action='append',default=[])
    parser.add_argument('--pdf',action='append',default=[])
    parser.add_argument('--image',action='append',default=[])
    parser.add_argument('--region',nargs=4,type=float)
    parser.add_argument('--output',type=Path,default=ROOT/'test-output'/'corpus')
    args=parser.parse_args(); output=args.output.resolve(); output.mkdir(parents=True,exist_ok=True)
    engine=Engine(output/'library')
    selected=[args.corpus/name for name in args.pdf+args.image]
    inventory=[]
    for folder in args.image_folder:
        files=sorted(p for p in (args.corpus/folder).iterdir() if p.suffix.lower() in ['.jpg','.jpeg','.png','.tif','.tiff','.webp'])
        inventory.append({'folder':folder,'image_count':len(files)})
        if files: selected.append(files[min(10,len(files)-1)])
    report={'inventory':inventory,'files':[],'notes':['Sources are read-only. No source content is uploaded.','No CER/WER claimed without verified reference transcriptions.','Peak RSS is the sum across worker processes and may include shared memory.']}
    for source in selected:
        entry={'name':source.name,'bytes':source.stat().st_size}; report['files'].append(entry)
        before=digest(source); start=time.monotonic()
        try:
            imported=engine.import_file({'path':str(source)})
            entry['import_seconds']=round(time.monotonic()-start,2)
            pages=[p for p in engine.list_pages({}) if p['doc']==imported['id']]
            entry['pages']=len(pages); entry['previews']=[]
            for number in sorted(set([0,len(pages)//2,len(pages)-1])):
                rendered=engine.render({'id':pages[number]['id']})
                entry['previews'].append({'page':number+1,**rendered})
            target=pages[len(pages)//2]
            print(f"OCR: {source.name} / page {target['num']+1}",flush=True)
            result=recognize(engine.root,target,output)
            entry['ocr']=result
            if result['ok']:
                details=engine.details({'id':target['id']})
                entry['line_count']=len(details['lines'])
                entry['characters']=len(details['text'])
                confidences=[line['confidence'] for line in details['lines'] if line.get('confidence') is not None]
                entry['mean_confidence']=sum(confidences)/len(confidences) if confidences else None
                (output/(source.stem+'.txt')).write_text(details['text'],encoding='utf-8')
            print(f"Result: {'OK' if result['ok'] else 'ERROR'}; {result['seconds']}s; peak {result['peak_process_tree_rss_MB']} MB",flush=True)
            if args.region:
                engine.set_region({'id':target['id'],'roi':args.region})
                print(f'Region OCR: {source.name}',flush=True)
                entry['region']=args.region
                entry['region_ocr']=recognize(engine.root,target,output)
                details=engine.details({'id':target['id']})
                (output/(source.stem+'-region.txt')).write_text(details['text'],encoding='utf-8')
                print(f"Region result: {entry['region_ocr']['ok']}; {entry['region_ocr']['seconds']}s",flush=True)
        except Exception as e:
            entry['error']=str(e); print(f'ERROR: {e}',flush=True)
        entry['source_unchanged']=digest(source)==before
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    engine.export({'path':str(output/'transcriptions.json')})
    engine.export({'path':str(output/'transcriptions.xlsx')})
    engine.db.close()
    print(output/'report.json',flush=True)


if __name__=='__main__': main()
