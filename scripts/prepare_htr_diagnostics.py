"""Small, explicit human-read heading diagnostics; never training ground truth.

All eight supplied images and both PDFs are inventoried. Only clearly read
heading crops have a reference; their results cannot establish body-text accuracy.
"""
import hashlib
import json
from pathlib import Path
import sys
from PIL import Image,ImageDraw
import pymupdf

ROOT=Path(__file__).resolve().parents[1]
SOURCES=[('names','b84d97be-72f2-4546-812a-e85e7f85775d'),('polish-body','f1f3d53a-6a09-48a2-b4c8-7e377c1f5ac6'),('church','33c471d9-ded9-4873-bb84-b2d5edc28748'),('icons','f97f15ed-4f84-420f-85af-07693f5c1aa1'),('equipment','99b1ab8f-2259-486f-a645-dbd6466dce39'),('reform','eb1842c7-db42-4643-8854-b388d2312ea4'),('lipowce','6b1ee526-2002-4af0-b22f-e07111b5517f'),('town','bf4c0450-6a75-45b7-8ea7-c15752145102')]
# Rectangles use original image pixels, not altered/super-resolved images.
CROPS=[('church-books','church',(252,163,489,210),'Księgi Cerkiewne.'),('church-land','church',(141,421,389,459),'Grunta Cerkiewne.'),
       ('reform-title','reform',(256,307,718,356),'Ordinatio Reformatoria.'),('reform-village','reform',(251,893,607,953),'Wieś Lipowce.'),
       ('village','lipowce',(225,395,595,440),'Wieś Lipowce'),('town-title','town',(280,440,728,490),'Miasto Przemyslany.')]


def main():
    out=ROOT/'test-output/htr-repair-20261015';out.mkdir(exist_ok=True);images={};inventory=[];manifest=[]
    for name,ident in SOURCES:
        path=Path('C:/Users/inst/AppData/Local/Temp')/('codex-clipboard-'+ident+'.png')
        images[name]=Image.open(path).convert('RGB');inventory.append({'id':name,'source':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':images[name].size,'reference_policy':'Diagnostic-only headings; body transcription remains unverified.'})
    for filename in ['19-18-69_001.pdf','001_compressed.pdf']:
        path=Path('C:/Users/inst/Downloads')/filename
        with pymupdf.open(path) as pdf:inventory.append({'id':filename,'source':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'pages':len(pdf),'native_text_pages':sum(bool(p.get_text().strip()) for p in pdf)})
    sheet=Image.new('RGB',(900,len(CROPS)*140),'white');draw=ImageDraw.Draw(sheet)
    for index,(ident,name,rect,text) in enumerate(CROPS):
        image=images[name].crop(rect);path=out/(ident+'.png');image.save(path);display=image.copy();display.thumbnail((870,100));sheet.paste(display,(10,index*140+25));draw.text((10,index*140+5),ident,fill='black')
        manifest.append({'id':ident,'image':path.name,'image_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'source':name,'book':'ASNM_01358' if name in ['church','reform'] else 'ASNM_01349','book_name':name,'reference':text,'purpose':'development diagnostic; not training, not held-out accuracy estimate','source_rect':rect})
    sheet.save(out/'heading-crops.png');(out/'inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf8');(out/'manifest-draft.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8');print(out)


if __name__=='__main__':main()
