"""One-epoch local training integration check on synthetic books; no accuracy claim."""
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.workbench import Workbench


def main():
    output=ROOT/'test-output'/'training-smoke'/uuid.uuid4().hex
    output.mkdir(parents=True)
    model=ROOT/'models/fondue-handwriting/model.mlmodel'
    before=hashlib.sha256(model.read_bytes()).hexdigest()
    engine=Engine(output/'library'); workbench=Workbench(engine)
    font=ImageFont.truetype('C:/Windows/Fonts/times.ttf',45)
    for role,color in [('train','white'),('validation','#fffdf4'),('test','#fff8e8')]:
        image=Image.new('RGB',(1200,500),color); draw=ImageDraw.Draw(image)
        texts=['Anna Pauli','Joannes filius Pauli','Maria filia Annae','Domus 34']
        for i,text in enumerate(texts): draw.text((50,40+i*100),text,font=font,fill='black')
        source=output/(role+'.png'); image.save(source)
        imported=engine.import_file({'path':str(source)})
        page=next(p for p in engine.list_pages({}) if p['doc']==imported['id'])
        workbench.book_profile({'id':page['id'],'values':{'split':role}})
        for i,text in enumerate(texts):
            workbench.save_annotation({'page':page['id'],'data':{'kind':'line','rect':[40/1200,(30+i*100)/500,1000/1200,80/500],'text':text,'verified':True}})
    os.environ['OMP_NUM_THREADS']='2'
    try:
        result=engine.train_model({'model':str(model),'executable':str(ROOT/'.venv/Scripts/ketos.exe'),'explicit':True,'epochs':1})
        if not result['models']: raise RuntimeError('Training produced no loadable model')
        if hashlib.sha256(model.read_bytes()).hexdigest()!=before: raise RuntimeError('Base model changed')
        (output/'result.json').write_text(json.dumps(result,indent=2),encoding='utf8')
        print('One-epoch training integration: OK',output,flush=True)
    finally: engine.db.close()


if __name__=='__main__':main()
