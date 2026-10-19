"""Prepare immutable local scans and preview samples; never invent reference text."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.operations import Operations


def prepare(folder,inputs):
    folder=Path(folder).resolve();engine=Engine(folder);tools=Operations(engine);samples=[]
    try:
        for source in inputs:
            source=Path(source).resolve();before=hashlib.sha256(source.read_bytes()).hexdigest()
            doc=engine.import_file({'path':str(source)})['id'];pages=[p for p in engine.list_pages({}) if p['doc']==doc]
            tools.book_profile({'id':pages[0]['id'],'values':{'split':'test','notes':'Prepared for independent evaluation. Language/script and manual references still require review.'}})
            for index in sorted({0,len(pages)//2,len(pages)-1}):
                page=pages[index];preview=engine.render({'id':page['id']})
                samples.append({'document':doc,'page':page['id'],'number':page['num']+1,'name':source.name,'image':preview['path'],'verified':False,'source_sha256':before})
            if hashlib.sha256(source.read_bytes()).hexdigest()!=before:raise ValueError('Source changed during preparation')
        (folder/'evaluation-preparation.json').write_text(json.dumps({'policy':'No generated ground truth. Verify references manually; do not train on these test books.','samples':samples,'coverage':tools.evaluation_coverage({})},ensure_ascii=False,indent=2),encoding='utf8')
        cards=''.join('<article><h2>'+html.escape(s['name'])+' · '+str(s['number'])+'</h2><p>Текст ще не перевірено. Мову й письмо потрібно вказати вручну.</p><img loading="lazy" src="'+html.escape(Path(s['image']).as_uri(),quote=True)+'"></article>' for s in samples)
        (folder/'evaluation-preparation.html').write_text('<!doctype html><meta charset="utf-8"><title>Підготовка еталона</title><style>body{font:16px system-ui;margin:30px;background:#edf1f3}article{display:inline-block;vertical-align:top;width:46%;padding:1%;background:white;margin:1%}img{width:100%}</style><h1>Зразки для ручної перевірки</h1><p>Це підготовка набору, а не оцінка точності. Оригінали не змінені; жоден рядок не позначений перевіреним.</p>'+cards,encoding='utf8')
        quote=lambda value:"'"+str(value).replace("'","''")+"'"
        (folder/'Open-EvaluationLibrary.ps1').write_text('$env:ARCHIVEREADER_DATA='+quote(folder)+'\n$env:ARCHIVEREADER_PYTHON='+quote(sys.executable)+'\nStart-Process -FilePath '+quote(ROOT/'bin/Release/net10.0-windows/ArchiveReader.exe')+' -WindowStyle Hidden\n',encoding='utf-8-sig')
        (folder/'Open-EvaluationLibrary.cmd').write_text('@echo off\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Open-EvaluationLibrary.ps1"\n',encoding='utf8')
        return {'documents':len(inputs),'samples':len(samples),'verified_lines':0,'path':str(folder/'evaluation-preparation.html')}
    finally:engine.db.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--library',type=Path,required=True);parser.add_argument('sources',nargs='+',type=Path);args=parser.parse_args()
    print(json.dumps(prepare(args.library,args.sources),ensure_ascii=False))
