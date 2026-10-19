"""Find review-only surname candidates in saved PaddleOCR output (no inference).

Example:
  python scripts/find_surname_candidates.py --report .../paddle/report.json \
      --surname Skowyra --output test-output/surname-candidates

Only aligned rec_texts/rec_polys from the checksummed input image produce crops.
Confidence is model output, not evidence of correctness. No hit proves absence.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import unicodedata
import uuid

MAX_JSON=64*1024*1024
VARIANTS=('Skowyra','Skowira','Skovera','Scovyra','Szkowyra','Skowra')

def sha(path):
 with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def bounded_json(path):
 with Path(path).open('rb') as stream:raw=stream.read(MAX_JSON+1)
 if len(raw)>MAX_JSON:raise ValueError('JSON exceeds 64 MiB limit: '+str(path))
 return json.loads(raw),hashlib.sha256(raw).hexdigest()
def normalize(text):
 return ''.join(c for c in unicodedata.normalize('NFKD',str(text)).casefold().replace('ł','l') if not unicodedata.combining(c))
def distance(a,b,maximum=2):
 if abs(len(a)-len(b))>maximum:return maximum+1
 previous=list(range(len(b)+1))
 for i,ca in enumerate(a,1):
  current=[maximum+1]*(len(b)+1);current[0]=i
  for j in range(max(1,i-maximum),min(len(b),i+maximum)+1):current[j]=min(current[j-1]+1,previous[j]+1,previous[j-1]+(ca!=b[j-1]))
  if min(current)>maximum:return maximum+1
  previous=current
 return previous[-1]
def matches(text,surname):
 variants=list(VARIANTS) if normalize(surname) in {normalize(v) for v in VARIANTS} else [surname]
 if surname not in variants:variants.insert(0,surname)
 normalized=[(v,normalize(v)) for v in variants];result=[]
 for token in re.finditer(r'[^\W\d_]+',text,re.UNICODE):
  word=token.group();key=normalize(word)
  if len(key)>66:continue
  comparisons=[(distance(key,value),variant) for variant,value in normalized if len(key)>=5 and len(value)>=5 and abs(len(key)-len(value))<=2]
  exact=next((v for v,k in normalized if k==key),None)
  if exact:score,variant=0,exact
  elif comparisons:score,variant=min(comparisons,key=lambda x:(x[0],x[1]))
  else:continue
  if score<=2:result.append({'token':word,'start':token.start(),'end':token.end(),'matched_variant':variant,'edit_distance':score,'kind':'exact_variant' if score==0 else 'fuzzy_ocr_candidate'})
 return result

def split_match(left,right,surname):
 """A spelling hypothesis only: explicit dash + immediately next array entry."""
 if not isinstance(left,str) or not isinstance(right,str) or max(len(left),len(right))>20000:return None
 tail=re.search(r'([^\W\d_]+)[-\u00ad\u2010-\u2015]\s*$',left,re.UNICODE)
 head=re.match(r'\s*([^\W\d_]+)',right,re.UNICODE)
 if not tail or not head:return None
 fragments=[tail.group(1),head.group(1)]
 if not all(2<=len(v)<=12 for v in fragments):return None
 joined=''.join(fragments)
 variants=VARIANTS if normalize(surname) in {normalize(v) for v in VARIANTS} else [surname]
 if not 5<=len(normalize(joined))<=max(len(normalize(v)) for v in variants)+2:return None
 found=matches(joined,surname)
 if not found:return None
 return {'hypothesis_token':joined,'fragments':fragments,'spans':[(tail.start(1),tail.end(1)),(head.start(1),head.end(1))],'matches':found}

def box_for(polygon):
 return [min(p[0] for p in polygon),min(p[1] for p in polygon),max(p[0] for p in polygon),max(p[1] for p in polygon)]
def plausible_next_line(first,second):
 a=box_for(first);b=box_for(second);ha=a[3]-a[1];hb=b[3]-b[1]
 overlap=max(0,min(a[2],b[2])-max(a[0],b[0]));small_width=min(a[2]-a[0],b[2]-b[0])
 # Conservative same-column/next-line gate, not proof of reading order.
 if overlap<small_width*.25:return False
 if (b[1]+b[3]-a[1]-a[3])/2<=max(1,min(ha,hb)*.25):return False
 return -.5*max(ha,hb)<=b[1]-a[3]<=max(12,2*max(ha,hb))

def make_assets(row,polygons,image,assets,output):
 from PIL import ImageDraw
 width,height=image.size;ident=row['id'];boxes=[];lines=[]
 for n,poly in enumerate(polygons):
  box=box_for(poly);box=[max(0,math.floor(box[0])),max(0,math.floor(box[1])),min(width,math.ceil(box[2])),min(height,math.ceil(box[3]))];boxes.append(box)
  path=assets/(ident+'-line-'+str(n+1)+'.png');image.crop(tuple(box)).save(path);lines.append(path.relative_to(output).as_posix())
 union=[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)]
 padding=max(30,max(b[3]-b[1] for b in boxes)*2);context_box=[0,max(0,union[1]-padding),width,min(height,union[3]+padding)]
 context=assets/(ident+'-context.png');full=assets/(row['image_sha256']+Path(row['image']).suffix.lower());page=assets/(ident+'-page.png');image.crop(tuple(context_box)).save(context)
 if not full.exists():shutil.copyfile(row['image'],full)
 marked=image.copy();draw=ImageDraw.Draw(marked)
 for polygon in polygons:draw.line([tuple(p) for p in polygon]+[tuple(polygon[0])],fill='red',width=max(2,width//500))
 marked.thumbnail((1600,1600));marked.save(page)
 row['assets']={'line':lines[0],'lines':lines,'context':context.relative_to(output).as_posix(),'full_source':full.relative_to(output).as_posix(),'page_overlay':page.relative_to(output).as_posix()}
 row['crop_boxes_pixels']={'line':boxes[0],'lines':boxes,'union':union,'context':context_box}
 row['bounding_box_policy']='Union is only a bounding box of the displayed real line polygons, not a new text region, baseline or confirmed reading order.'

def path_from(value,base):
 path=Path(str(value))
 if path.is_absolute():return path.resolve()
 candidates=[(base/path).resolve(),path.resolve(),(Path(__file__).resolve().parents[1]/path).resolve()]
 return next((p for p in candidates if p.exists()),candidates[0])
def aliases_for(case,manifest_source=None):
 aliases=case.get('aliases') or [{'source_document':case.get('source_document') or manifest_source,'source_page':case.get('source_page'),'label':case.get('id')}]
 result=[]
 for a in aliases:
  source=a.get('source_document') or a.get('path');page=a.get('source_page')
  # Supplied manifests define source_page as one-based. Never guess 0→1.
  valid_page=page if type(page) is int and page>=1 else None
  result.append({'source_document':source,'source_page_1based':valid_page,'page_numbering':'one_based_input' if valid_page is not None else 'unknown_or_photo','label':a.get('label'),'origin':a.get('origin'),'source_sha256':a.get('source_sha256'),'manifest_alias':a})
 return result

def raw_blocks(data):
 values=data if isinstance(data,list) else [data]
 if len(values)>32:raise ValueError('Too many raw result blocks for one image')
 for item in values:
  if isinstance(item,dict) and isinstance(item.get('res'),dict):item=item['res']
  if isinstance(item,dict) and isinstance(item.get('rec_texts'),list):yield item

def valid_polygon(value,width,height):
 if not isinstance(value,list) or not 3<=len(value)<=1000:return None
 result=[]
 for p in value:
  if not isinstance(p,list) or len(p)!=2 or any(type(v) not in [int,float] or not math.isfinite(v) for v in p):return None
  if not 0<=p[0]<=width or not 0<=p[1]<=height:return None
  result.append(p)
 if max(p[0] for p in result)<=min(p[0] for p in result) or max(p[1] for p in result)<=min(p[1] for p in result):return None
 return result

def write_atomic(path,value):
 temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp');temporary.write_text(value,'utf-8');os.replace(temporary,path)
def scan(report_path,surname,output):
 from PIL import Image,ImageDraw
 report_path=Path(report_path).resolve();output=Path(output).resolve()
 if report_path in [(output/'candidates.json').resolve(),(output/'candidates.html').resolve()]:raise ValueError('Output would overwrite the input report; choose an isolated folder')
 output.mkdir(parents=True,exist_ok=True);assets=output/'assets';assets.mkdir(exist_ok=True)
 report,report_sha=bounded_json(report_path);cases=report.get('cases',report.get('results',[]))
 if not isinstance(cases,list) or len(cases)>10000:raise ValueError('Expected a bounded report cases array')
 if not surname.strip() or len(surname)>64:raise ValueError('Surname must contain 1–64 characters')
 candidates=[];issues=[];dedup={};verified_cases=0;parsed_cases=0;lines_read=0;geometry_lines=0;digest_cache={}
 def checked_hash(path):
  key=str(path.resolve())
  if key not in digest_cache:digest_cache[key]=sha(path)
  return digest_cache[key]
 requested=report.get('summary',{}).get('requested',len(cases));manifest_source=None
 if report.get('manifest'):
  manifest_path=path_from(report['manifest'],report_path.parent)
  try:
   manifest,manifest_sha=bounded_json(manifest_path)
   if report.get('manifest_sha256') and manifest_sha!=report['manifest_sha256']:issues.append({'kind':'manifest_hash_mismatch','path':str(manifest_path)})
   else:manifest_source=manifest.get('source')
  except (OSError,ValueError) as ex:issues.append({'kind':'manifest_unavailable','error':str(ex)})
 for case in cases:
  case_id=case.get('id');image_path=path_from(case.get('image',''),report_path.parent);expected=case.get('image_sha256');aliases=aliases_for(case,manifest_source)
  if not isinstance(expected,str) or not re.fullmatch('[0-9a-fA-F]{64}',expected):issues.append({'case':case_id,'kind':'missing_image_sha256'});continue
  try:
   actual=checked_hash(image_path)
   if actual.lower()!=expected.lower():issues.append({'case':case_id,'kind':'image_sha256_mismatch','expected':expected,'actual':actual});continue
   verified_cases+=1
   raw_path=path_from(case['raw_path'],report_path.parent);raw,raw_sha=bounded_json(raw_path)
   if case.get('raw_sha256') and case['raw_sha256']!=raw_sha:issues.append({'case':case_id,'kind':'raw_sha256_mismatch'});continue
   blocks=list(raw_blocks(raw))
   if not blocks:issues.append({'case':case_id,'kind':'missing_rec_texts'});continue
   parsed_cases+=1
   with Image.open(image_path) as opened:
    if opened.width*opened.height>100000000:raise ValueError('Image exceeds 100 megapixels')
    image=opened.convert('RGB');width,height=image.size
   if case.get('size') and case['size']!=[width,height]:issues.append({'case':case_id,'kind':'image_size_mismatch'});continue
  except (KeyError,OSError,ValueError) as ex:issues.append({'case':case_id,'kind':'case_unavailable','error':str(ex)});continue
  for block_index,raw in enumerate(blocks):
   texts=raw['rec_texts']
   if len(texts)>50000:issues.append({'case':case_id,'kind':'too_many_text_lines'});continue
   polygons=raw.get('rec_polys');scores=raw.get('rec_scores');aligned=isinstance(polygons,list) and len(polygons)==len(texts);score_aligned=isinstance(scores,list) and len(scores)==len(texts)
   reasons=[]
   if not aligned:reasons.append('rec_polys_not_aligned_with_rec_texts')
   bound=False
   if raw.get('input_path'):
    raw_input=path_from(raw['input_path'],raw_path.parent)
    try:bound=checked_hash(raw_input)==actual
    except OSError:bound=False
   if not bound:reasons.append('raw_input_identity_not_verified')
   config=report.get('configuration',{});settings=raw.get('model_settings',{})
   if any(config.get(k) is True for k in ['doc_orientation','doc_unwarping']) or settings.get('use_doc_preprocessor') is True or raw.get('doc_preprocessor_res'):reasons.append('preprocessed_geometry_not_proven_original')
   if reasons:issues.append({'case':case_id,'block':block_index,'kind':'geometry_unavailable','reasons':reasons})
   for index,text in enumerate(texts):
    lines_read+=1
    if not isinstance(text,str) or len(text)>20000:continue
    found=matches(text,surname)
    if not found:continue
    key=(actual,block_index,index)
    if key in dedup:
     existing=dedup[key]
     existing['case_ids']=sorted(set(existing['case_ids']+[case_id]))
     for alias in aliases:
      if alias not in existing['sources']:existing['sources'].append(alias)
     continue
    polygon=valid_polygon(polygons[index],width,height) if not reasons else None
    score=scores[index] if score_aligned else None;confidence=score if type(score) in [int,float] and math.isfinite(score) and 0<=score<=1 else None
    ident=hashlib.sha256((report_sha+actual+str(block_index)+':'+str(index)).encode()).hexdigest()[:20]
    row={'id':ident,'case_ids':[case_id],'image':str(image_path),'image_sha256':actual,'raw_path':str(raw_path),'raw_sha256':raw_sha,'raw_result_index':block_index,'line_index_0based':index,'text':text,'matches':found,'match_kind':'exact_variant' if any(m['kind']=='exact_variant' for m in found) else 'fuzzy_ocr_candidate','minimum_edit_distance':min(m['edit_distance'] for m in found),'raw_score':score,'model_confidence':confidence,'confidence_policy':'Raw model confidence is not calibrated truth and does not confirm the surname.','sources':aliases,'polygon_pixels':polygon,'geometry_status':'aligned_original_image' if polygon else 'unavailable','geometry_unavailable_reasons':reasons or ([] if polygon else ['invalid_or_missing_line_polygon']),'nearby_ocr_text':[{'line_index_0based':j,'text':texts[j]} for j in range(max(0,index-2),min(len(texts),index+3)) if isinstance(texts[j],str)],'context_policy':'Adjacent OCR array entries, not verified reading order or confirmed family relationships.','confirmed':False,'human_verified':False,'assets':{}}
    if polygon:geometry_lines+=1;make_assets(row,[polygon],image,assets,output)
    candidates.append(row);dedup[key]=row
   # An explicit terminal hyphen is required; neighboring OCR entries alone
   # never justify joining words. All text and both confidences stay separate.
   for index in range(len(texts)-1):
    hypothesis=split_match(texts[index],texts[index+1],surname)
    if hypothesis is None:continue
    indices=[index,index+1];polys=[valid_polygon(polygons[i],width,height) if not reasons else None for i in indices]
    if all(polys) and not plausible_next_line(polys[0],polys[1]):
     issues.append({'case':case_id,'block':block_index,'kind':'split_line_geometry_rejected','line_indices_0based':indices});continue
    key=(actual,block_index,index,'split')
    if key in dedup:
     existing=dedup[key];existing['case_ids']=sorted(set(existing['case_ids']+[case_id]))
     for alias in aliases:
      if alias not in existing['sources']:existing['sources'].append(alias)
     continue
    lines=[]
    for n,i in enumerate(indices):
     score=scores[i] if score_aligned else None;confidence=score if type(score) in [int,float] and math.isfinite(score) and 0<=score<=1 else None
     lines.append({'line_index_0based':i,'text':texts[i],'raw_score':score,'model_confidence':confidence,'polygon_pixels':polys[n],'fragment':hypothesis['fragments'][n],'fragment_span':list(hypothesis['spans'][n])})
    ident=hashlib.sha256((report_sha+actual+str(block_index)+':'+str(index)+':split').encode()).hexdigest()[:20]
    row={'id':ident,'case_ids':[case_id],'image':str(image_path),'image_sha256':actual,'raw_path':str(raw_path),'raw_sha256':raw_sha,'raw_result_index':block_index,'line_index_0based':index,'line_indices_0based':indices,'text':texts[index]+'\n'+texts[index+1],'lines':lines,'matches':hypothesis['matches'],'match_kind':'split_line_candidate','hypothesis_token':hypothesis['hypothesis_token'],'fragments':hypothesis['fragments'],'minimum_edit_distance':min(m['edit_distance'] for m in hypothesis['matches']),'raw_score':[line['raw_score'] for line in lines],'model_confidence':None,'line_model_confidences':[line['model_confidence'] for line in lines],'confidence_policy':'Both original model confidences are shown separately. No joint probability, confirmed transcription or relationship is inferred.','sources':aliases,'polygon_pixels':None,'line_polygons_pixels':polys,'geometry_status':'two_aligned_original_image_lines' if all(polys) else 'unavailable','geometry_unavailable_reasons':reasons or ([] if all(polys) else ['one_or_both_line_polygons_missing_or_invalid']),'adjacency_status':'plausible_geometry_only' if all(polys) else 'array_adjacency_only_unverified','nearby_ocr_text':[{'line_index_0based':j,'text':texts[j]} for j in range(max(0,index-2),min(len(texts),index+4)) if isinstance(texts[j],str)],'context_policy':'Explicit hyphen plus next OCR array entry is only a spelling hypothesis. Same-column/next-line geometry gate is conservative, never verified reading order.','confirmed':False,'human_verified':False,'assets':{}}
    if all(polys):geometry_lines+=1;make_assets(row,polys,image,assets,output)
    candidates.append(row);dedup[key]=row
  image.close()
 candidates.sort(key=lambda r:(r['minimum_edit_distance'],next((s['source_page_1based'] for s in r['sources'] if s['source_page_1based'] is not None),10**9),r['image'],r['line_index_0based']))
 result={'created_utc':datetime.now(timezone.utc).isoformat(),'report':str(report_path),'report_sha256':report_sha,'report_status':report.get('status'),'tool':report.get('tool'),'configuration_sha256':report.get('configuration_sha256'),'surname':surname,'variants':list(VARIANTS) if normalize(surname) in {normalize(v) for v in VARIANTS} else [surname],'matching_policy':'Case/diacritic-normalized whole tokens; exact listed variants or Levenshtein <=2 for tokens/variants >=5 characters. Explicit terminal-hyphen splits are separate unverified hypotheses; both source lines/confidences are retained. No inferred spelling correction.','coverage':{'report_cases':len(cases),'requested_cases':requested,'image_hash_verified_cases':verified_cases,'parsed_raw_cases':parsed_cases,'raw_lines_read':lines_read,'candidate_lines':len(candidates),'split_line_candidates':sum(r['match_kind']=='split_line_candidate' for r in candidates),'candidate_lines_with_geometry':geometry_lines,'partial_report':report.get('status') not in ['completed','complete','done'] or len(cases)<requested},'policy':'OCR candidates only, never confirmed people or facts. No hit is not proof of absence. Missing/misaligned/transformed geometry never creates invented crop coordinates. Original sources and reports are unchanged.','confirmed_candidates':0,'candidates':candidates,'issues':issues}
 write_atomic(output/'candidates.json',json.dumps(result,ensure_ascii=False,indent=2));write_atomic(output/'candidates.html',render_html(result));return result

def render_html(result):
 esc=lambda v:html.escape(str(v))
 parts=['<!doctype html><html lang="uk"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Кандидати прізвища '+esc(result['surname'])+'</title><style>body{font:16px/1.5 system-ui;max-width:1200px;margin:auto;padding:24px;background:#f4f5f1;color:#182a2b}article{background:white;padding:20px;margin:24px 0;border:1px solid #bbc9c9;border-radius:8px}img{max-width:100%;height:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere}strong{color:#8a3215}.page{max-height:550px;max-width:48%;object-fit:contain;vertical-align:top}.line{max-height:180px}.meta{color:#455c5c;font-size:14px}</style><h1>Кандидати: '+esc(result['surname'])+'</h1><p><strong>Це неперевірений результат OCR. Збіги не підтверджують особу чи спорідненість. Відсутність збігів не доводить відсутності прізвища.</strong></p><p>'+esc(result['coverage']['parsed_raw_cases'])+' / '+esc(result['coverage']['requested_cases'])+' випадків прочитано з наявного звіту. Кандидатів: '+esc(len(result['candidates']))+'. '+('Звіт ще неповний.' if result['coverage']['partial_report'] else 'Звіт завершено.')+'</p><p class="meta">Оригінали та звіти залишено без змін. Відстань редагування — ознака для пошуку, а впевненість — вихід моделі; жодна з них не є доказом правильного прочитання.</p><p><a href="candidates.json">Кандидати та походження JSON</a></p>']
 for row in result['candidates']:
  label='Гіпотеза переносу між двома OCR-рядками' if row['match_kind']=='split_line_candidate' else 'Точний варіант у тексті OCR' if row['match_kind']=='exact_variant' else 'Нечіткий кандидат OCR'
  sources='<br>'.join(esc(Path(s['source_document']).name if s.get('source_document') else 'Джерело не вказано')+(' · PDF сторінка '+esc(s['source_page_1based'])+' (від 1)' if s.get('source_page_1based') is not None else ' · номер сторінки невідомий / фото') for s in row['sources'])
  parts+=['<article><h2>'+esc(label)+' · '+esc(row['case_ids'])+'</h2><p>'+sources+'</p><p><b>'+esc(row['text'])+'</b></p><p class="meta">OCR-рядок '+esc(row['line_index_0based']+1)+'; мінімальна відстань: '+esc(row['minimum_edit_distance'])+'; вихідна впевненість моделі: '+esc(row['raw_score'])+'. Статус: НЕ ПІДТВЕРДЖЕНО.</p><pre>'+esc(json.dumps(row['matches'],ensure_ascii=False))+'</pre>']
  if row['match_kind']=='split_line_candidate':parts+=['<p><strong>Лише гіпотеза: '+esc(row['hypothesis_token'])+'. Сусідство в OCR-масиві не доводить порядок читання; тексти не об’єднано в архівний запис.</strong></p><pre>'+esc(json.dumps(row['lines'],ensure_ascii=False,indent=2))+'</pre>']
  a=row['assets']
  if a:parts+=['<p>Окремі точні фрагменти вихідних рядків:</p>'+''.join('<img class="line" src="'+esc(path)+'" alt="Окремий справжній фрагмент рядка"><br>' for path in a.get('lines',[a['line']]))+'<p>Контекст на всю ширину сторінки:</p><img src="'+esc(a['context'])+'" alt="Контекст рядків"><p><a href="'+esc(a['full_source'])+'">Повне незмінене вхідне зображення</a></p><img class="page" src="'+esc(a['page_overlay'])+'" alt="Окремі справжні контури OCR на сторінці">']
  else:parts+=['<p><strong>Немає перевіреної геометрії. Координати й фрагменти не створювалися.</strong></p><pre>'+esc(row['geometry_unavailable_reasons'])+'</pre>']
  parts+=['<p>Сусідні елементи OCR-масиву; порядок читання не перевірено:</p><pre>'+esc('\n'.join(f"{x['line_index_0based']+1}: {x['text']}" for x in row['nearby_ocr_text']))+'</pre></article>']
 parts+=['<details><summary>Обмеження та збої ('+esc(len(result['issues']))+')</summary><pre>'+esc(json.dumps(result['issues'],ensure_ascii=False,indent=2))+'</pre></details></html>'];return ''.join(parts)

def self_test():
 from PIL import Image,ImageDraw
 root=Path(__file__).resolve().parents[1]/'test-output';root.mkdir(exist_ok=True)
 with tempfile.TemporaryDirectory(dir=root) as tmp:
  folder=Path(tmp);image=folder/'image.png';im=Image.new('RGB',(400,300),'white');ImageDraw.Draw(im).text((30,40),'Skowyra',fill='black');im.save(image);digest=sha(image)
  texts=['Jan Skowyra','Anna Skowvra','No surname here','Skowyra'];polys=[[[20,20],[280,20],[280,60],[20,60]],[[20,70],[280,70],[280,110],[20,110]],[[20,120],[280,120],[280,160],[20,160]],[[20,170],[280,170],[280,210],[20,210]]];raw=folder/'raw.json';raw.write_text(json.dumps([{'input_path':str(image),'rec_texts':texts,'rec_polys':polys,'rec_scores':[.95,.2,.9,.7]}]),'utf-8');case={'id':'fixture','image':str(image),'image_sha256':digest,'size':[400,300],'raw_path':str(raw),'aliases':[{'source_document':'source.pdf','source_page':7}]};report=folder/'report.json';report.write_text(json.dumps({'tool':'PaddleOCR','status':'complete','cases':[case,case],'summary':{'requested':2}}),'utf-8');before=sha(report);result=scan(report,'Skowyra',folder/'out');assert len(result['candidates'])==3;assert result['candidates'][0]['match_kind']=='exact_variant';assert result['candidates'][-1]['minimum_edit_distance']==1;assert result['candidates'][-1]['raw_score']==.2;assert all(not r['confirmed'] and r['assets'] for r in result['candidates']);assert result['candidates'][0]['sources'][0]['source_page_1based']==7;assert sha(report)==before and sha(image)==digest
  candidate=result['candidates'][0]
  with Image.open(image) as source,Image.open(folder/'out'/candidate['assets']['line']) as crop:assert source.crop(tuple(candidate['crop_boxes_pixels']['line'])).convert('RGB').tobytes()==crop.convert('RGB').tobytes()
  assert sha(folder/'out'/candidate['assets']['full_source'])==digest
  raw.write_text(json.dumps([{'input_path':str(image),'rec_texts':['Skowyra'],'rec_polys':[],'rec_scores':[.9]}]),'utf-8');result=scan(report,'Skowyra',folder/'unaligned');assert len(result['candidates'])==1 and not result['candidates'][0]['assets'];assert result['candidates'][0]['polygon_pixels'] is None
  raw.write_text(json.dumps([{'rec_texts':['Skowyra'],'rec_polys':[polys[0]],'rec_scores':[.8]}]),'utf-8');result=scan(report,'Skowyra',folder/'unbound');assert not result['candidates'][0]['assets'] and 'raw_input_identity_not_verified' in result['candidates'][0]['geometry_unavailable_reasons']
  raw.write_text(json.dumps([{'input_path':str(image),'rec_texts':['Skowyra'],'rec_polys':[polys[0]],'rec_scores':[.8],'doc_preprocessor_res':{'angle':90}}]),'utf-8');result=scan(report,'Skowyra',folder/'transformed');assert not result['candidates'][0]['assets']
  split_texts=['Mariannam Sko-','wra annorum'];split_raw={'input_path':str(image),'rec_texts':split_texts,'rec_polys':polys[:2],'rec_scores':[.31,.72]};raw.write_text(json.dumps([split_raw]),'utf-8');result=scan(report,'Skowyra',folder/'split');assert len(result['candidates'])==1;candidate=result['candidates'][0];assert candidate['match_kind']=='split_line_candidate' and candidate['hypothesis_token']=='Skowra';assert candidate['line_indices_0based']==[0,1] and candidate['text']=='Mariannam Sko-\n'+'wra annorum';assert candidate['raw_score']==[.31,.72] and candidate['model_confidence'] is None;assert candidate['polygon_pixels'] is None and len(candidate['line_polygons_pixels'])==2;assert len(candidate['assets']['lines'])==2 and not candidate['confirmed']
  for index,path in enumerate(candidate['assets']['lines']):
   with Image.open(image) as source,Image.open(folder/'split'/path) as crop:assert source.crop(tuple(candidate['crop_boxes_pixels']['lines'][index])).convert('RGB').tobytes()==crop.convert('RGB').tobytes()
  repeated=scan(report,'Skowyra',folder/'split');assert candidate['id']==repeated['candidates'][0]['id']
  split_raw['rec_polys']=[polys[0],[[320,70],[390,70],[390,110],[320,110]]];raw.write_text(json.dumps([split_raw]),'utf-8');result=scan(report,'Skowyra',folder/'wrong-column');assert not result['candidates'];assert any(x['kind']=='split_line_geometry_rejected' for x in result['issues'])
  split_raw['rec_polys']=[];raw.write_text(json.dumps([split_raw]),'utf-8');result=scan(report,'Skowyra',folder/'split-no-geometry');assert len(result['candidates'])==1 and not result['candidates'][0]['assets'];assert result['candidates'][0]['adjacency_status']=='array_adjacency_only_unverified'
  assert split_match('Mariannam Sko\u00ad','wra annorum','Skowyra');assert split_match('Mariannam Sko—','wra annorum','Skowyra');assert not split_match('Mariannam Sko','wra annorum','Skowyra');assert not split_match('S-','kowra','Skowyra');assert not split_match('ABCDEFGHIJKLMNOP-','wra','Skowyra');assert not plausible_next_line(polys[0],[[20,250],[280,250],[280,290],[20,290]])
  im=Image.new('RGB',(400,300),'black');im.save(image);result=scan(report,'Skowyra',folder/'mismatch');assert not result['candidates'];assert all(i['kind']=='image_sha256_mismatch' for i in result['issues'])
  assert not matches('Skowyrabcdefgh abc','Skowyra');assert matches('Szkowyra Scovyra Skovera Skowira','Skowyra');assert not matches('Li','Skowyra');assert not matches('Skowyra','Differentname')
  protected=folder/'candidates.json';protected.write_text(report.read_text('utf-8'),'utf-8');protected_sha=sha(protected)
  try:scan(protected,'Skowyra',folder)
  except ValueError:pass
  else:raise AssertionError('Input report overwrite was not rejected')
  assert sha(protected)==protected_sha and sha(report)==before
 print('Self-test PASS: exact/fuzzy, explicit split lines, both confidences/polygons, pixel-exact separate crops, deterministic IDs, wrong-column/fragment limits, missing geometry, dedup, page1-based, immutable sources and SHA mismatch.')

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--report',type=Path);parser.add_argument('--surname',default='Skowyra');parser.add_argument('--output',type=Path);parser.add_argument('--self-test',action='store_true');args=parser.parse_args()
 if args.self_test:self_test();return
 if args.report is None or args.output is None:parser.error('--report and --output are required')
 result=scan(args.report,args.surname,args.output);print(json.dumps({'output':str(args.output.resolve()/'candidates.html'),'coverage':result['coverage'],'issues':len(result['issues']),'confirmed':0},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
