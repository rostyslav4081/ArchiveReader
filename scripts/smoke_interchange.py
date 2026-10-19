"""Four-locale offline PAGE/ALTO exchange preview with real synthetic geometry."""
import os,subprocess,sys
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.interchange import PAGE
if __name__=='__main__':
 output=ROOT/'test-output/ui-interchange';output.mkdir(parents=True,exist_ok=True);source=output/'synthetic.png';im=Image.new('RGB',(1000,1400),'#fffdf0');ImageDraw.Draw(im).text((80,140),'SYNTHETIC TEST\nPhilippus & Anna\nNot an archival document.',fill='black',font=ImageFont.truetype('C:/Windows/Fonts/times.ttf',40),spacing=25);im.save(source)
 xml=output/'external.page.xml';xml.write_text(f'<PcGts xmlns="{PAGE}"><Metadata/><Page imageFilename="synthetic.png" imageWidth="1000" imageHeight="1400"><TextRegion id="region_1"><Coords points="40,100 940,100 940,400 40,400"/><TextLine id="line_1" custom="readingOrder {{index:0;}}"><Coords points="70,195 500,195 500,260 70,260"/><Baseline points="80,250 490,250"/><TextEquiv><Unicode>Philippus &amp; Anna</Unicode></TextEquiv></TextLine></TextRegion></Page></PcGts>','utf-8')
 for language in ['uk','en','pl','cs']:
  folder=output/language;e=Engine(folder);e.import_file({'path':str(source)});e.db.close();env=os.environ.copy();env.update(ARCHIVEREADER_DATA=str(folder),ARCHIVEREADER_LANGUAGE=language,ARCHIVEREADER_PYTHON=sys.executable,ARCHIVEREADER_SMOKE_XML=str(xml.resolve()))
  startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
  subprocess.run([str(ROOT/'bin/Release/net10.0-windows/ArchiveReader.exe'),'--smoke-test','--smoke-interchange'],env=env,startupinfo=startup,check=True,timeout=90)
  if not (folder/'interchange-ui/preview.png').is_file():raise RuntimeError('Missing interchange capture: '+language)
  print(language,'OK',flush=True)
