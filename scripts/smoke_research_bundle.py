"""Exercise bundle preview, export, verification and restore in real WPF UI."""
import os
from pathlib import Path
import subprocess
import sys
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.review_corpus import CorpusTools


def main():
    for language in ['uk','en','pl','cs']:
        folder=ROOT/'test-output/ui-bundle'/language;engine=Engine(folder);source=folder/'synthetic.png';image=Image.new('RGB',(400,200),'ivory');ImageDraw.Draw(image).text((30,50),'Synthetic archival test only',fill='black');image.save(source);engine.import_file({'path':str(source)});page=engine.list_pages({})[0]['id']
        model=folder/'models/synthetic-trocr';model.mkdir(parents=True,exist_ok=True);(model/'model.safetensors').write_bytes(b'Synthetic fixture; not an actual neural model');(model/'config.json').write_text('{}');engine.settings({'values':{'model':str(model)}})
        (folder/'results/report.html').write_text('<h1>Synthetic research report</h1>',encoding='utf8');tools=CorpusTools(engine)
        if not tools.corpus_list({}):
            tools.save_annotation({'page':page,'data':{'kind':'entry','rect':[.05,.1,.9,.7],'text':'Synthetic manual reference','verified':False}});tools.corpus_import({'id':page});row=tools.corpus_list({})[0];tools.corpus_save({'reference':row['id'],'revision':row['revision'],'text':'Synthetic manual reference','human_verified':True,'single_block':True});tools.corpus_freeze({})
        engine.db.close();env=os.environ.copy();env.update(ARCHIVEREADER_DATA=str(folder),ARCHIVEREADER_LANGUAGE=language,ARCHIVEREADER_PYTHON=sys.executable)
        startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
        subprocess.run([str(ROOT/'bin/Release/net10.0-windows/ArchiveReader.exe'),'--smoke-test','--smoke-bundle'],env=env,startupinfo=startup,check=True,timeout=150)
        for tab in range(2):
            if not (folder/f'bundle-ui/tab-{tab}.png').is_file():raise RuntimeError('Missing bundle render: '+language)
        restored=sorted(folder.glob('smoke-bundle-*-restored'))
        if not restored or not (restored[-1]/'results/report.html').exists():raise RuntimeError('Bundle smoke restore missing: '+language)
        print(language+': OK',flush=True)

if __name__=='__main__':main()
