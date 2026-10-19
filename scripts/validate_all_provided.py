"""Isolated integration diagnostics for all supplied files; no verified ground truth."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.books import BookTools
from backend.archivereader.board_import import BoardTools
from prepare_htr_diagnostics import SOURCES

OUT=ROOT/'test-output/htr-lab-20261015'
BOUNDS={'names':(.285,.005,.43,.023),'polish-body':(.273,.132,.60,.027),'church':(252/853,163/1280,237/853,47/1280),'icons':(.263,.143,.62,.026),'equipment':(.168,.122,.66,.027),'reform':(256/853,307/1280,462/853,49/1280),'lipowce':(225/853,395/1280,370/853,45/1280),'town':(280/853,440/1280,448/853,50/1280),'19-18-69_001.pdf':(.305,.677,.357,.025),'001_compressed.pdf':(.355,.18,.35,.037)}

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--prepare-only',action='store_true');parser.add_argument('--repeat-comparison',action='store_true');args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True);engine=Engine(OUT/'library');tools=BookTools(engine);inventory=[];selected=[]
    if not engine.settings({}):engine.settings({'values':{'engine':'kraken','executable':str(ROOT/'.venv/Scripts/kraken.exe'),'model':str(ROOT/'models/german-handwriting/model.mlmodel'),'languages':'deu','uiLanguage':'uk'}})
    sources=[(name,Path('C:/Users/inst/AppData/Local/Temp')/('codex-clipboard-'+ident+'.png')) for name,ident in SOURCES]+[(name,Path('C:/Users/inst/Downloads')/name) for name in ['19-18-69_001.pdf','001_compressed.pdf']]
    for name,path in sources:
        original_sha=sha(path);doc=engine.import_file({'path':str(path)})['id'];pages=[p for p in engine.list_pages({}) if p['doc']==doc];renders=[]
        for page in pages:
            rendered=engine.render({'id':page['id']})
            with Image.open(rendered['path']) as image:image.verify()
            renders.append({'page':page['num']+1,'page_id':page['id'],'preview':rendered['path']})
        page=pages[1] if path.suffix.lower()=='.pdf' else pages[0];region=tools.save_annotation({'page':page['id'],'annotation':'provided-diagnostic-'+name.replace('.','-')+('-page2' if path.suffix.lower()=='.pdf' else ''),'data':{'kind':'line','rect':list(BOUNDS[name]),'text':'','verified':False,'note':'Manually bounded development diagnostic; no reference transcription; not training or held-out accuracy evaluation.'}})
        # save_annotation returns the complete page annotation list.
        region=next(r for r in tools.annotations({'id':page['id']}) if r['id']=='provided-diagnostic-'+name.replace('.','-')+('-page2' if path.suffix.lower()=='.pdf' else ''));selected.append((page,region));crop=tools.region_crop({'id':page['id'],'annotation':region['id']})
        assert sha(path)==original_sha
        inventory.append({'id':name,'source':str(path),'source_sha256':original_sha,'source_unchanged':True,'document':doc,'pages':len(pages),'rendered_pages':renders,'selected_page':page['num']+1,'selected_page_id':page['id'],'annotation':region['id'],'source_bounds_normalized':region['rect'],'crop':crop['path'],'reference':None,'verified':False})
        print('Prepared '+name+' '+str(len(pages))+' pages',flush=True)
    for title,names in [('ASNM_01358',['polish-body','church','icons','equipment','reform']),('ASNM_01349',['lipowce','town'])]:
        existing=next((b for b in tools.books({}) if b['name']==title),None)
        tools.book_save({'book':existing['id'] if existing else None,'name':title,'items':[{'page':x['selected_page_id'],'label':x['id']} for x in inventory if x['id'] in names],'data':{'profile':{'languages':'pl,la','split':'','calendar':'','notes':'User-provided development diagnostics, not verified references.'}}})
    figma=ROOT/'test-output/figma-family-tree';board=BoardTools(engine);board_args={'path':str(figma/'raw-board.json'),'assets':str(figma/'asset-manifest.json'),'people':['1:41','1:65','1:94','1:153','1:208','1:279','1:443','1:446','1:549','1:622','1:662','1:746','1:767','1:1082','1:1108']};board_args['sha']=board.board_preview(board_args)['sha'];board_result=board.board_import(board_args)
    sheet=Image.new('RGB',(1000,len(inventory)*120),'white');draw=ImageDraw.Draw(sheet)
    for index,item in enumerate(inventory):
        with Image.open(item['crop']) as source:
            image=source.convert('RGB');image.thumbnail((970,90));sheet.paste(image,(10,index*120+25))
        draw.text((10,index*120+5),item['id'],fill='black')
    sheet.save(OUT/'selected-crops.png')
    launcher=f"$env:ARCHIVEREADER_DATA='{OUT/'library'}'\n$env:ARCHIVEREADER_PYTHON='{ROOT/'.venv/Scripts/python.exe'}'\n$env:ARCHIVEREADER_MODEL='{ROOT/'models/german-handwriting/model.mlmodel'}'\nStart-Process -FilePath '{ROOT/'bin/Release/net10.0-windows/ArchiveReader.exe'}' -WindowStyle Hidden\n"
    (OUT/'Open-HtrLab.ps1').write_text(launcher,encoding='utf-8-sig');(OUT/'Open-HtrLab.cmd').write_text('@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Open-HtrLab.ps1"\r\n',encoding='ascii')
    report={'files':inventory,'total_pages':sum(x['pages'] for x in inventory),'rendered_pages':sum(len(x['rendered_pages']) for x in inventory),'recognized_selected_crops':0,'verified_reference_lines':0,'policy':'Only 10 selected manually bounded crops are compared. No whole-document HTR, CER, WER or training ground truth. All model alternatives remain unverified.','figma':{'people':len(board_result['persons']),'nodes':len(board_result['snapshot']['nodes']),'assets':len(board_result['assets'])}}
    report_path=OUT/'report.json';report['selected_crops_signature']=hashlib.sha256(json.dumps([(x['source_sha256'],x['annotation'],x['source_bounds_normalized']) for x in inventory],sort_keys=True).encode()).hexdigest();prior=json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    if not args.prepare_only:
        comparison=prior.get('comparison') if prior.get('selected_crops_signature')==report['selected_crops_signature'] else None
        if not comparison or args.repeat_comparison:
            comparison=tools.run_comparison(selected,[{'name':'Mannheim German handwriting','engine':'kraken','path':str(ROOT/'models/german-handwriting/model.mlmodel')},{'name':'Polish metrical experimental','engine':'trocr','path':str(ROOT/'models/polish-metrical-experimental')}])
        report['comparison']=comparison;report['recognized_selected_crops']=len(comparison['rows'])
        outcomes={r['id']:r['results'] for r in comparison['rows']}
        for item in inventory:item['model_outcomes']=outcomes.get(item['annotation'],{})
    assert report['total_pages']==85 and len(inventory)==10
    assert all(not r.get('verified') for page,region in selected for r in tools.annotations({'id':page['id']}))
    for item in inventory:assert sha(item['source'])==item['source_sha256']
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');engine.db.close();print(report_path,flush=True)

if __name__=='__main__':main()
