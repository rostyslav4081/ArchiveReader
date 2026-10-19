"""Render the complete entry-corpus editor in four locales with synthetic drafts."""
import os
from pathlib import Path
import subprocess
import sys
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.review_corpus import CorpusTools

if __name__=='__main__':
    output=ROOT/'test-output/ui-entry-corpus';output.mkdir(parents=True,exist_ok=True)
    image=Image.new('RGB',(1200,1500),'#fffdf4');draw=ImageDraw.Draw(image)
    draw.text((80,100),'SYNTHETIC ENTRY\nJoannes filius Pauli et Annae\n14 Martii 1832, domus 34\nNot an archival document.',fill='black',font=ImageFont.truetype('C:/Windows/Fonts/times.ttf',38),spacing=25)
    source=output/'synthetic.png';image.save(source)
    app=ROOT/'bin/Release/net10.0-windows/ArchiveReader.exe'
    for language in ['uk','en','pl','cs']:
        folder=output/language;engine=Engine(folder);engine.import_file({'path':str(source)});page=engine.list_pages({})[0]['id'];tools=CorpusTools(engine)
        tools.save_annotation({'page':page,'annotation':'smoke-corpus-entry','data':{'kind':'entry','rect':[.05,.05,.9,.32],'text':'Synthetic draft: Joannes filius Pauli et Annae. 14 Martii1832, domus34.','verified':False}})
        tools.corpus_import({'id':page});engine.db.close()
        env=os.environ.copy();env['ARCHIVEREADER_DATA']=str(folder);env['ARCHIVEREADER_LANGUAGE']=language;env['ARCHIVEREADER_PYTHON']=sys.executable
        startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
        subprocess.run([str(app),'--smoke-test','--smoke-corpus'],env=env,startupinfo=startup,check=True,timeout=90)
        if not all((folder/'corpus-ui'/f'tab-{i}.png').is_file() for i in range(2)):raise RuntimeError('Missing corpus UI capture: '+language)
        print(language,'OK',flush=True)
