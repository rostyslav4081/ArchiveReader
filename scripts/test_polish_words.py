"""Compare real word crops; no language-model correction or reference labels."""
import hashlib,html,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PIL import Image
from backend.archivereader.htr_compare import trocr_lines
from backend.archivereader.recognizers import kraken_region
p=ROOT/'test-output/accuracy-improvement';source=p/'polish-line-1.png';im=Image.open(source).convert('RGB')
rects=[(0,0,72,im.height),(166,0,214,im.height),(408,0,473,im.height)]
paths=[];rows=[]
for n,rect in enumerate(rects):
 path=p/f'polish-word-{n+1}.png';im.crop(rect).save(path);paths.append(path);rows.append({'rect_in_line':rect,'crop':path.name})
started=time.perf_counter()
for row,result in zip(rows,trocr_lines(ROOT/'models/pet3r12-polish-words',paths),strict=True):row['pet3r12']=result
for n,(row,path) in enumerate(zip(rows,paths,strict=True)):
 for name in ['tiny','medium']:
  result=kraken_region(path,ROOT/f'models/kraken-ppocrv6-{name}/{name}.safetensors',p/f'word-{n+1}-{name}.xml',single_line=True)
  row[name]='\n'.join(r['text'] for r in result)
report={'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'seconds':time.perf_counter()-started,'human_verified':False,'accuracy_measured':False,'scope':'Three manually bounded word crops from a real historical Polish manuscript. PET3R12 historical training coverage is unconfirmed.','rows':rows}
(p/'polish-word-comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
body=''.join('<tr><td><img src="'+r['crop']+'"></td><td>'+html.escape(json.dumps(r['pet3r12'],ensure_ascii=False))+'</td><td>'+html.escape(r['tiny'])+'</td><td>'+html.escape(r['medium'])+'</td></tr>' for r in rows)
(p/'polish-word-comparison.html').write_text('<meta charset="utf-8"><h1>Польські слова: реальний рукопис</h1><p>Три вручну виділені слова. Це тест слів, не цілої сторінки. Еталона немає, точність не виміряна. Історична придатність PET3R12 не підтверджена.</p><table border="1"><tr><th>Скан</th><th>PET3R12</th><th>PP-OCRv6 Tiny</th><th>PP-OCRv6 Medium</th></tr>'+body+'</table>','utf-8')
print(json.dumps(report,ensure_ascii=False))
