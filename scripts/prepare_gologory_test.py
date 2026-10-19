"""Import/render supplied AGAD301 PDFs into separate ignored test libraries."""
import argparse
import hashlib
import html
import json
import re
from pathlib import Path
import sys
from PIL import Image,ImageDraw
import pymupdf

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.books import BookTools
SOURCE=None
OUT=ROOT/'test-output/gologory-301-332'

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    global SOURCE,OUT
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--output',type=Path);args=parser.parse_args()
    SOURCE=args.source.resolve()
    match=re.search(r'AGAD[_ -]301[_ -](\d+)(?:_|$)',SOURCE.stem,re.I)
    if not match:raise ValueError('Filename must explicitly identify AGAD301 unit')
    case_number=match.group(1)
    OUT=args.output.resolve() if args.output else ROOT/'test-output'/f'gologory-301-{case_number}'
    if not OUT.is_relative_to((ROOT/'test-output').resolve()):raise ValueError('Output must stay under test-output')
    prior_manifest=OUT/'cases.json'
    if prior_manifest.exists() and Path(json.loads(prior_manifest.read_text(encoding='utf-8'))['source']).resolve()!=SOURCE:raise ValueError('Output belongs to another source PDF; choose a separate output directory')
    metadata={'331':(40,'Lipowce Majdan births1800-1834','births'),'332':(107,'Gologory marriages1755-1795','marriages'),'333':(15,'Zukow marriages1806-1862','marriages'),'334':(123,'Gologory deaths1755-1795','deaths'),'335':(45,'Gologory Lipowce deaths1827-1834','deaths'),'336':(30,'Gologory Lipowce mixed1839','mixed births marriages deaths')}
    if case_number not in metadata:raise ValueError('Unit not in explicit supplied-file inventory')
    expected,description,record_type=metadata[case_number];title=f'AGAD301/{case_number} '+description
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'inputs').mkdir(exist_ok=True)
    initial=sha(SOURCE);engine=Engine(OUT/'library');tools=BookTools(engine)
    doc=engine.import_file({'path':str(SOURCE)})['id'];pages=[dict(p) for p in engine.db.execute('SELECT id,num FROM pages WHERE doc=? ORDER BY num',(doc,))]
    cases=[];native_characters=0;sheet=Image.new('RGB',(9*180,((len(pages)+8)//9)*265),'white');draw=ImageDraw.Draw(sheet)
    with pymupdf.open(SOURCE) as pdf:
        assert len(pdf)==len(pages)==expected
        for index,page in enumerate(pages):
            pdfpage=pdf[index];native_characters+=len(pdfpage.get_text().strip());rendered=engine.render({'id':page['id']})
            target=OUT/'inputs'/f'page-{index+1:03}.png'
            with Image.open(rendered['path']) as source:
                image=source.convert('RGB');image.thumbnail((2400,2400));image.save(target);size=list(image.size);pixelsha=hashlib.sha256(image.tobytes()).hexdigest();thumb=image.copy();thumb.thumbnail((174,239))
            with Image.open(target) as check:check.verify()
            x=(index%9)*180;y=(index//9)*265;sheet.paste(thumb,(x,y+22));draw.text((x+4,y+4),str(index+1),fill='black')
            images=[{'xref':im[0],'width':im[2],'height':im[3]} for im in pdfpage.get_images(full=True)]
            image_sha=sha(target);cases.append({'id':f'gologory-{index+1:03}','image':str(target),'image_sha256':image_sha,'pixel_sha256':pixelsha,'size':size,'library_page':page['id'],'source_page':index+1,'source_sha256':initial,'source_page_points':[pdfpage.rect.width,pdfpage.rect.height],'embedded_images':images,'aliases':[{'path':str(target),'label':f'AGAD301/332 scan{index+1}','origin':'provided PDF page','source_document':str(SOURCE),'source_page':index+1,'source_sha256':initial,'sha256':image_sha,'original_size':[[im['width'],im['height']] for im in images]}]})
            print('Rendered',index+1,'/',len(pages),flush=True)
    old=next((book for book in tools.books({}) if book['name']==title),None)
    book=tools.book_save({'book':old['id'] if old else None,'name':title,'items':[{'page':p['id'],'label':str(p['num']+1)} for p in pages],'data':{'profile':{'split':'test','languages':'la,pl','notes':'User-supplied PDF. Filename metadata is not independently verified. No human-verified reference transcription.'}}})
    sheet.save(OUT/'contact-sheet.jpg',quality=90)
    assert sha(SOURCE)==initial
    for case in cases:
        largest=max(case['embedded_images'],key=lambda im:im['width']*im['height'],default=None)
        case['aliases'][0]['original_size']=[largest['width'],largest['height']] if largest else None
    copied=Path(engine.db.execute('SELECT path FROM documents WHERE id=?',(doc,)).fetchone()['path']);assert sha(copied)==initial
    manifest={'scope':'All107 scanned pages of the newly supplied AGAD301/332 PDF; no native text; no ground-truth transcription.','preparation':'Engine original-mode1800px previews, RGB, maximum side<=2400px, one page at a time. Original PDF unchanged.','source':str(SOURCE),'source_sha256':initial,'source_bytes':SOURCE.stat().st_size,'source_unchanged':True,'imported_copy_sha256':sha(copied),'document':doc,'book':book['id'],'library':str(OUT/'library'),'native_text_characters':native_characters,'cases':cases}
    manifest['scope']=f'All{expected} scanned pages of newly supplied AGAD301/{case_number} PDF; no ground-truth transcription.'
    manifest['unit']=f'AGAD301/{case_number}';manifest['record_type_filename']=record_type
    for case in cases:
        case['id']=f'agad301-{case_number}-{case["source_page"]:03}'
        case['aliases'][0]['label']=f'AGAD301/{case_number} scan{case["source_page"]}'
    (OUT/'cases.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    esc=html.escape;rows=['<!doctype html><meta charset="utf-8"><title>AGAD301/332 test book</title><style>body{font:16px system-ui;margin:30px}main{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:16px}img{max-width:100%}article{border:1px solid #ccc;padding:8px}</style><h1>AGAD301/332:107 сканованих сторінок</h1><p>Усі сторінки імпортовано й відрендерено. Повного прочитання чи підтверджених знахідок прізвищ ще немає. Назва й роки наразі взяті з назви наданого файла.</p><p><a href="cases.json">Маніфест і контрольні суми</a> · <a href="contact-sheet.jpg">Контактний аркуш</a></p><main>']
    rows[0]=rows[0].replace('AGAD301/332',f'AGAD301/{case_number}').replace('107 сканованих',f'{expected} сканованих')
    rows += ['<article><a href="inputs/page-'+f'{c["source_page"]:03}'+'.png">Скан '+str(c['source_page'])+'<img loading="lazy" src="inputs/page-'+f'{c["source_page"]:03}'+'.png"></a></article>' for c in cases];rows.append('</main>');(OUT/'index.html').write_text('\n'.join(rows),encoding='utf-8')
    launcher=f"$env:ARCHIVEREADER_DATA='{OUT/'library'}'\n$env:ARCHIVEREADER_PYTHON='{ROOT/'.venv/Scripts/python.exe'}'\nStart-Process -FilePath '{ROOT/'bin/Release/net10.0-windows/ArchiveReader.exe'}' -WindowStyle Hidden\n";(OUT/'Open-Gologory.ps1').write_text(launcher,encoding='utf-8-sig');(OUT/'Open-Gologory.cmd').write_text('@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Open-Gologory.ps1"\r\n',encoding='ascii')
    engine.db.close();print('Ready',OUT/'cases.json',flush=True)

if __name__=='__main__':main()
