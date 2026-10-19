"""Render fact review in four languages against isolated synthetic photo-book records."""
import json
import os
from pathlib import Path
import subprocess
import sys
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.books import BookTools
from backend.archivereader.fact_review import FactReviewTools


def main():
    output=ROOT/'test-output/ui-facts';output.mkdir(parents=True,exist_ok=True)
    for language in ['uk','en','pl','cs']:
        folder=output/language;engine=Engine(folder)
        for index,name in enumerate(['Jan Kowalski','Jan Kowalsky']):
            source=folder/f'synthetic-{index}.png';image=Image.new('RGB',(1200,700),'ivory');draw=ImageDraw.Draw(image);draw.text((80,100),f'SYNTHETIC TEST — NOT ARCHIVAL EVIDENCE\n{name}\nVillage, house {34+index}, 183{2+index}',font=ImageFont.truetype('C:/Windows/Fonts/times.ttf',38),fill='black',spacing=25);image.save(source);engine.import_file({'path':str(source)})
        pages=engine.list_pages({});tools=FactReviewTools(engine);books=BookTools(engine)
        if not books.books({}):books.book_save({'name':'Synthetic test book','items':[{'page':p['id'],'label':str(i+1)} for i,p in enumerate(pages)]})
        for i,page in enumerate(pages):engine.save_record({'id':f'fact-smoke-{i}','page':page['id'],'kind':'Інші записи та примітки','person':['Jan Kowalski','Jan Kowalsky'][i],'place':'Village','house':str(34+i),'date':str(1832+i),'text':'Synthetic record; not archival evidence.'})
        current=tools.fact_reviews({'record':'fact-smoke-0'})
        if current['facts'][0]['assessment'] is None:tools.fact_save({'record':'fact-smoke-0','field':'person','value':'Jan Kowalski','status':'hypothesis','note':'Synthetic review. Similar names alone are not proof.','signature':current['source']['signature'],'rect':[.05,.2,.8,.3]})
        kinship=next(f for f in tools.fact_reviews({'record':'fact-smoke-0'})['facts'] if f['field']=='kinship')
        if kinship['assessment'] is None:tools.fact_save({'record':'fact-smoke-0','field':'kinship','value':'Possible brother of another synthetic person','status':'hypothesis','note':'Synthetic hypothesis only. No family link created.','signature':current['source']['signature']})
        engine.db.close();env=os.environ.copy();env.update(ARCHIVEREADER_DATA=str(folder),ARCHIVEREADER_LANGUAGE=language,ARCHIVEREADER_PYTHON=sys.executable)
        startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
        subprocess.run([str(ROOT/'bin/Release/net10.0-windows/ArchiveReader.exe'),'--smoke-test','--smoke-facts'],env=env,startupinfo=startup,check=True,timeout=120)
        for i in range(2):
            if not (folder/f'facts-ui/tab-{i}.png').is_file():raise RuntimeError('Missing fact review render: '+language)
        print(language+': OK',flush=True)

if __name__=='__main__':main()
