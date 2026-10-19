"""Actual deployed Kraken segmentation and scoped HTR on a pinned public scan."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.layout import LayoutTools


def main():
    source=ROOT/'test-output/archive-samples/cz-andelska-hora-01-0080.jpg'
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    output=ROOT/'test-output/layout-smoke'/uuid.uuid4().hex; output.mkdir(parents=True)
    engine=Engine(output/'library'); engine.import_file({'path':str(source)}); page=engine.list_pages({})[0]
    layout=LayoutTools(engine)
    column=layout.save_annotation({'page':page['id'],'data':{'kind':'column','rect':[.60,.27,.104,.70],'label':'Names column; test crop','text':'Manual text remains separate'}})['id']
    engine.db.close()
    executable=str(ROOT/'.venv/Scripts/kraken.exe')
    def call(command,**values):
        request={'root':str(output/'library'),'command':command,'id':page['id'],'executable':executable}|values
        env=os.environ.copy(); env['PYTHONUTF8']='1'
        result=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'bin/Release/net10.0-windows/engine.py')],input=json.dumps(request),text=True,encoding='utf8',capture_output=True,env=env,timeout=360)
        (output/(command+'.stderr.log')).write_text(result.stderr,encoding='utf8')
        response=json.loads(result.stdout); (output/(command+'.json')).write_text(json.dumps(response,ensure_ascii=False,indent=2),encoding='utf8')
        if not response['ok']: raise RuntimeError(response)
        return response['result']
    print('Segmenting actual handwritten column…',flush=True)
    proposal=call('layout_propose',annotation=column,reuse=False,mode='text')
    if not any(r['kind']=='line' for r in proposal['regions']): raise RuntimeError('No line proposals')
    print('Recognizing only the saved column…',flush=True)
    result=call('recognize_region',annotation=column,mode='text',model=str(ROOT/'models/fondue-handwriting/model.mlmodel'))
    if not result['lines']: raise RuntimeError('No region lines')
    applied=call('region_recognition_apply',run=result['id'])
    engine=Engine(output/'library'); layout=LayoutTools(engine)
    assert engine.page(page['id'])['text']==''
    assert next(r for r in layout.annotations({'id':page['id']}) if r['id']==column)['text']=='Manual text remains separate'
    assert hashlib.sha256(source.read_bytes()).hexdigest()==before
    print('Deployed scoped HTR: OK; proposals:',len(proposal['regions']),'lines:',len(result['lines']),'added:',applied['added'],output,flush=True)
    engine.db.close()


if __name__=='__main__': main()
