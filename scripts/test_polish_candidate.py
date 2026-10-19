"""Compare a Polish line candidate on polygons from a whole real manuscript page."""
import json,time,sys,html,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PIL import Image,ImageDraw
from kraken.lib.xml import XMLPage
from backend.archivereader.htr_compare import trocr_lines
out=ROOT/'test-output/accuracy-improvement'
data=json.loads((out/'polish-other-page-medium.json').read_text('utf-8'))
image=Image.open(data['source']).convert('RGB')
lines=XMLPage(str(out/'polish-other-page-medium.alto.xml'),filetype='alto',linetype='baselines').to_container().lines
paths=[];rows=[]
for line in lines:
 p=line.boundary
 if not p or not line.text.strip():continue
 x=max(0,int(min(v[0] for v in p)));y=max(0,int(min(v[1] for v in p)));r=min(image.width,int(max(v[0] for v in p))+1);b=min(image.height,int(max(v[1] for v in p))+1)
 if r-x<image.width*.45:continue
 crop=image.crop((x,y,r,b));mask=Image.new('L',crop.size);ImageDraw.Draw(mask).polygon([(v[0]-x,v[1]-y) for v in p],fill=255);masked=Image.new('RGB',crop.size,'white');masked.paste(crop,(0,0),mask)
 path=out/f'polish-line-{len(rows)+1}.png';masked.save(path);paths.append(path);rows.append({'polygon':p,'medium':line.text,'crop':str(path)})
 if len(rows)==3:break
start=time.perf_counter()
for row,result in zip(rows,trocr_lines(ROOT/'models/polish-metrical-experimental',paths),strict=True):row['polish_experimental']=result
report={'source':data['source'],'source_sha256':hashlib.sha256(Path(data['source']).read_bytes()).hexdigest(),'seconds':time.perf_counter()-start,'human_verified':False,'accuracy_measured':False,'warning':'Polish candidate is trained for 1800–1865 metrical registers with automatic pseudo-labels; this prose page is outside its confirmed scope.','rows':rows}
(out/'polish-candidate-comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
body=''.join('<tr><td><img style="max-width:100%" src="'+Path(r['crop']).name+'"></td><td>'+html.escape(r['medium'])+'</td><td>'+html.escape(json.dumps(r['polish_experimental'],ensure_ascii=False))+'</td></tr>' for r in rows)
(out/'polish-comparison.html').write_text('<meta charset="utf-8"><title>Перевірка польської сторінки</title><h1>Інша ціла польська рукописна сторінка</h1><p>Модельні прочитання, не еталон. Точність не виміряна. Польська експериментальна модель має інший період і тип документів.</p><img style="width:45%;float:left" src="'+html.escape(Path(data['source']).as_uri())+'"><pre style="white-space:pre-wrap">'+html.escape(data['text'])+'</pre><div style="clear:both"></div><table border="1"><tr><th>Справжній фрагмент</th><th>PP-OCRv6 medium</th><th>Polish metrical experimental</th></tr>'+body+'</table>','utf-8')
print(json.dumps(report,ensure_ascii=False))
