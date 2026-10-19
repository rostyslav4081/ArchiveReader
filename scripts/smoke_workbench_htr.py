"""Exercise the deployed JSON bridge with real local models and a public line sample."""
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import argparse

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.workbench import Workbench


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--frozen',action='store_true'); args=parser.parse_args()
    output=ROOT/'test-output'/'workbench-htr'/uuid.uuid4().hex
    output.mkdir(parents=True)
    examples=ROOT/'test-output'/'handwriting'
    case=next(c for c in json.loads((examples/'manifest.json').read_text(encoding='utf8')) if len(c['reference'])>20)
    engine=Engine(output/'library')
    engine.import_file({'path':str(examples/case['image'])})
    page=engine.list_pages({})[0]
    workbench=Workbench(engine)
    region=workbench.save_annotation({'page':page['id'],'data':{'kind':'line','rect':[0,0,1,1],'text':case['reference'],'verified':True}})
    frozen=None
    if args.frozen:
        from backend.archivereader.library import LibraryTools
        library=LibraryTools(engine)
        library.book_profile({'id':page['id'],'values':{'split':'test'}})
        frozen=library.benchmark_freeze({})['path']
    engine.db.close()
    models=[{'name':'A','engine':'kraken','path':str(ROOT/'models/fondue-handwriting/model.mlmodel')},
            {'name':'B','engine':'kraken','path':str(ROOT/'models/fondue-mixed/model.mlmodel')}]
    request={'command':'compare_regions','root':str(output/'library'),'id':page['id'],'annotation':region['id'],'models':models}
    if frozen: request.update(command='benchmark_compare',path=frozen)
    env=os.environ.copy();env['PYTHONUTF8']='1'
    result=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'bin/Release/net10.0-windows/engine.py')],
                          input=json.dumps(request),text=True,encoding='utf8',capture_output=True,env=env,timeout=180)
    (output/'stderr.log').write_text(result.stderr,encoding='utf8')
    payload=json.loads(result.stdout)
    (output/'response.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
    if not payload['ok'] or any(m.get('failed_lines') for m in payload['result']['models']):
        raise RuntimeError(payload)
    print('Deployed HTR comparison: OK',output)


if __name__=='__main__':main()
