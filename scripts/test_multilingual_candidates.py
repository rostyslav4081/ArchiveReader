"""Local engineering diagnostic. EHRI overlaps PP-OCRv6 training; no generalisation claim."""
import html,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PIL import Image
from backend.archivereader.engine import parse_alto
from backend.archivereader.recognizers import kraken_region
out=ROOT/'test-output/multilingual-candidates';out.mkdir(exist_ok=True);rows=[]
for lang in ['czech','hungarian','slovak','german']:
 source=ROOT/f'test-output/ehri/{lang}.jpg';im=Image.open(source).convert('RGB')
 refs=[r for r in parse_alto(ROOT/f'test-output/ehri/{lang}.xml') if len(r['text'])>=12 and r['box'][2]>=200][:2]
 for n,line in enumerate(refs):
  x,y,w,h=line['box'];crop=out/f'{lang}-{n}.png';im.crop((max(0,int(x)),max(0,int(y)),min(im.width,int(x+w+1)),min(im.height,int(y+h+1)))).save(crop)
  candidates={'medium':ROOT/'models/kraken-ppocrv6-medium/medium.safetensors'}
  if lang=='german':candidates['german-print']=ROOT/'models/german-print/model.mlmodel'
  predictions={}
  for name,model in candidates.items():
   start=time.perf_counter();result=kraken_region(crop,model,out/f'{lang}-{n}-{name}.xml',single_line=True);predictions[name]={'text':'\n'.join(r['text'] for r in result),'seconds':time.perf_counter()-start}
  rows.append({'language':lang,'crop':crop.name,'reference':line['text'],'predictions':predictions});print(json.dumps(rows[-1],ensure_ascii=False),flush=True)
report={'scope':'Public EHRI cropped-line engineering diagnostic; source revision 20a5e002031c1f9e66176133b4602ed439db6521, CC-BY-4.0. EHRI is in PP-OCRv6 training mixture. Not an independent accuracy benchmark or proof for private historical books.','rows':rows}
(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
body=''.join('<tr><td>'+r['language']+'</td><td><img style="max-width:500px" src="'+r['crop']+'"></td><td>'+html.escape(r['reference'])+'</td><td>'+html.escape(json.dumps(r['predictions'],ensure_ascii=False))+'</td></tr>' for r in rows)
(out/'report.html').write_text('<meta charset="utf-8"><h1>Проба інших мов</h1><p>Реальні публічні скани EHRI, CC-BY-4.0. Цей корпус входить до навчальних матеріалів PP-OCRv6: це перевірка запуску, не незалежне вимірювання точності на наших книгах.</p><table border="1"><tr><th>Мова</th><th>Скан</th><th>Текст корпусу</th><th>Модель</th></tr>'+body+'</table>','utf-8')
