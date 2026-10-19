"""Bounded offline PAGE/ALTO interchange; never treats imported text as verified truth.

Supported subset: one raster page, text regions/blocks and lines, real polygons,
optional real baselines and explicit reading order. Other XML stays in the archive.
Schemas: PRImA PAGE 2019-07-15 and LOC ALTO v4 (no online schema resolution).
"""
import hashlib,json,math,re,shutil,uuid
from datetime import datetime,timezone
from pathlib import Path
import xml.etree.ElementTree as ET
try:
 from .workbench import Workbench,validate_rect
 from .library import digest
except ImportError:
 from workbench import Workbench,validate_rect
 from library import digest
PAGE='http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15'
ALTO='http://www.loc.gov/standards/alto/ns-v4#'
MAX_XML=12*1024*1024

def local(tag):return tag.rsplit('}',1)[-1]
def children(node,name):return [e for e in node if local(e.tag)==name]
def first(node,name):return next((e for e in node if local(e.tag)==name),None)
def points(value,width,height,minimum=3,clip=False):
 raw=[v for v in re.split(r'[\s,]+',value.strip()) if v]
 if len(raw)%2 or len(raw)<minimum*2 or len(raw)>20000:raise ValueError('Неправильні координати XML.')
 try:result=[[float(raw[i])/width,float(raw[i+1])/height] for i in range(0,len(raw),2)]
 except (ValueError,OverflowError):raise ValueError('Неправильні координати XML.')
 if any(not math.isfinite(v) for p in result for v in p):raise ValueError('Неправильні координати XML.')
 outside=any(not 0<=v<=1 for p in result for v in p)
 if outside:
  # Only small detector overflow is repairable, explicitly confirmed on apply.
  if not clip or any(v < -min(20,max(5,dimension*.01))/dimension or v > 1+min(20,max(5,dimension*.01))/dimension for p in result for v,dimension in zip(p,[width,height])):raise ValueError('Координати XML виходять за межі зображення.')
  result=[[min(1,max(0,v)) for v in p] for p in result]
 return result

def rect_polygon(rect):
 x,y,w,h=rect;return [[x,y],[x+w,y],[x+w,y+h],[x,y+h]]
def bounds(poly):
 xs=[p[0] for p in poly];ys=[p[1] for p in poly]
 return validate_rect([min(xs),min(ys),max(xs)-min(xs),max(ys)-min(ys)])
def point_text(poly,w,h):return ' '.join(f'{round(x*w)},{round(y*h)}' for x,y in poly)
def parse_xml(raw,clip=False):
 if not raw or len(raw)>MAX_XML:raise ValueError('XML завеликий або порожній.')
 # Reject declarations in UTF-8/16/32 before parsing. No DTD/network resolution.
 clean=raw.replace(b'\x00',b'').upper()
 if b'<!DOCTYPE' in clean or b'<!ENTITY' in clean:raise ValueError('DTD та сутності XML не підтримуються.')
 try:root=ET.fromstring(raw)
 except (ET.ParseError,ValueError):raise ValueError('Не вдалося прочитати XML.')
 nodes=list(root.iter())
 stack=[(root,0)]
 while stack:
  node,depth=stack.pop()
  if depth>64:raise ValueError('XML має надто глибоку структуру.')
  stack.extend((child,depth+1) for child in node)
 if len(nodes)>100000:raise ValueError('XML містить забагато елементів.')
 kind=local(root.tag);namespace=root.tag.partition('}')[0].lstrip('{')
 if kind=='PcGts' and namespace.startswith('http://schema.primaresearch.org/PAGE/gts/pagecontent/'):fmt='page';pages=[n for n in root if local(n.tag)=='Page']
 elif kind=='alto' and namespace in ['http://www.loc.gov/standards/alto/ns-v2#','http://www.loc.gov/standards/alto/ns-v3#',ALTO]:fmt='alto';pages=[n for n in nodes if local(n.tag)=='Page']
 else:raise ValueError('Підтримуються лише PAGE XML та ALTO XML.')
 if len(pages)!=1:raise ValueError('Виберіть XML лише однієї сторінки.')
 page=pages[0]
 try:w=float(page.attrib['imageWidth' if fmt=='page' else 'WIDTH']);h=float(page.attrib['imageHeight' if fmt=='page' else 'HEIGHT'])
 except (KeyError,ValueError):raise ValueError('У XML немає розмірів зображення.')
 if not all(math.isfinite(v) and v>=1 and v<=1000000 and v==int(v) for v in (w,h)):raise ValueError('Неправильні розміри зображення XML.')
 filename=page.get('imageFilename','') if fmt=='page' else next((n.text or '' for n in nodes if local(n.tag)=='fileName'),'')
 if fmt=='alto' and next((n.text for n in nodes if local(n.tag)=='MeasurementUnit'),'pixel')!='pixel':raise ValueError('ALTO має використовувати пікселі.')
 comments='\n'.join((n.text or '') for n in nodes if local(n.tag) in ['Comments','processingStepSettings'])
 sha=re.search(r'ArchiveReader source_sha256=([a-fA-F0-9]{64})',comments)
 page_id=re.search(r'ArchiveReader page_id=([A-Za-z0-9_-]+)',comments)
 image_sha=re.search(r'ArchiveReader image_sha256=([a-fA-F0-9]{64})',comments)
 refs={};explicit_order=False
 # Only a flat explicitly ordered group forms a total order. Nested/unordered
 # structures remain in retained XML and are not flattened into invented order.
 order_roots=[n for n in nodes if local(n.tag)=='ReadingOrder']
 for order_root in order_roots:
  groups=list(order_root)
  if len(groups)!=1 or local(groups[0].tag)!='OrderedGroup':continue
  group=groups[0]
  if all(local(n.tag) in ['RegionRefIndexed','ElementRef'] for n in group):
   for position,n in enumerate(group):
    ident=n.get('regionRef') or n.get('REF');index=n.get('index') if fmt=='page' else str(position)
    if ident and index is not None and len(ident.split())==1:
     try:refs[ident]=int(index)
     except ValueError:raise ValueError('Неправильний порядок читання XML.')
 if refs:explicit_order=True
 rows=[];seen=set();unsupported={};index=0
 def parse_region(node,parent=None):
  nonlocal index
  tag=local(node.tag);line=tag in ['TextLine'];original_id=node.get('id') or node.get('ID');ident=original_id or ('generated_'+tag.lower()+'_'+str(index+1))
  if ident in seen:raise ValueError('XML містить відсутні або повторені ідентифікатори.')
  seen.add(ident);geometry_clipped=False;original_geometry={}
  def norm(value,name,minimum=3):
   nonlocal geometry_clipped
   poly=points(value,w,h,minimum,clip)
   original_geometry[name]=value
   raw=[float(v) for v in re.split(r'[\s,]+',value.strip()) if v]
   if any(not 0<=v<=dim for i,v in enumerate(raw) for dim in [w if i%2==0 else h]):geometry_clipped=True
   return poly
  if fmt=='page':
   coords=first(node,'Coords')
   if coords is None:raise ValueError('Для текстової ділянки XML потрібні координати.')
   poly=norm(coords.get('points',''),'polygon');base=first(node,'Baseline');baseline=norm(base.get('points',''),'baseline',2) if base is not None else None
   equivalents=children(node,'TextEquiv');equivalents.sort(key=lambda n:int(n.get('index','0')) if n.get('index','0').isdigit() else 0)
   text=next((''.join(t.itertext()) for equiv in equivalents for t in equiv if local(t.tag)=='Unicode'),'')
  else:
   try:x=float(node.attrib['HPOS']);y=float(node.attrib['VPOS']);rw=float(node.attrib['WIDTH']);rh=float(node.attrib['HEIGHT'])
   except (ValueError,KeyError):raise ValueError('Неправильні межі тексту ALTO.')
   if rw<=0 or rh<=0:raise ValueError('Неправильні межі тексту ALTO.')
   box=norm(f'{x},{y} {x+rw},{y} {x+rw},{y+rh} {x},{y+rh}','box')
   shape=first(node,'Shape');polygon=first(shape,'Polygon') if shape is not None else None;poly=norm(polygon.get('POINTS',''),'polygon') if polygon is not None else box
   baseline=norm(node.get('BASELINE'),'baseline',2) if node.get('BASELINE') and len(re.findall(r'[-+]?\d+(?:\.\d+)?',node.get('BASELINE')))>2 else None
   if node.get('BASELINE') and baseline is None:original_geometry['scalar_baseline']=node.get('BASELINE')
   text=''
   if line:
    chunks=[];last_string=False
    for token in node:
     t=local(token.tag)
     if t=='String':
      if last_string:chunks.append(' ')
      chunks.append(token.get('CONTENT',''));last_string=True
     elif t=='SP':chunks.append(' ');last_string=False
     elif t=='HYP':chunks.append(token.get('CONTENT','-'));last_string=False
    text=''.join(chunks)
  rect=bounds(poly);order=refs.get(ident);custom=re.search(r'readingOrder\s*\{\s*index\s*:\s*(\d+)\s*;',node.get('custom',''))
  if custom:order=int(custom.group(1))
  if order is not None and not 0<=order<100000:raise ValueError('Неправильний порядок читання XML.')
  index+=1
  row={'external_id':ident,'original_external_id':original_id,'external_id_generated':original_id is None,'geometry_clipped':geometry_clipped,'original_geometry':original_geometry,'kind':'line' if line else 'entry','rect':rect,'polygon':poly,'baseline':baseline,'text':text,'parent_external':parent,'reading_order':order+1 if order is not None else None,'order_source':'explicit' if order is not None else 'xml_sequence','sequence':index,'verified':False}
  rows.append(row)
  for child in node:
   if local(child.tag) in (['TextRegion','TextLine'] if fmt=='page' else ['TextBlock','TextLine']):parse_region(child,ident)
 def walk(node):
  for child in node:
   tag=local(child.tag)
   if tag in (['TextRegion'] if fmt=='page' else ['TextBlock']):parse_region(child)
   else:walk(child)
 walk(page)
 for n in nodes:
  tag=local(n.tag)
  if tag.endswith('Region') and tag!='TextRegion':unsupported[tag]=unsupported.get(tag,0)+1
 if len(rows)>10000:raise ValueError('XML містить забагато текстових ділянок.')
 if not rows:raise ValueError('У XML немає підтримуваних текстових ділянок.')
 return {'format':fmt,'width':int(w),'height':int(h),'image_filename':filename,'source_sha256':sha.group(1).lower() if sha else None,'page_id':page_id.group(1) if page_id else None,'image_sha256':image_sha.group(1).lower() if image_sha else None,'rows':rows,'unsupported':unsupported,'explicit_region_order':explicit_order}

class InterchangeTools(Workbench):
 def __init__(self,engine):
  super().__init__(engine)
  self.db.executescript('''CREATE TABLE IF NOT EXISTS interchange_previews(id TEXT PRIMARY KEY,page TEXT,signature TEXT,xml_sha256 TEXT,xml BLOB,data TEXT,applied TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);''')
 def target(self,ident):
  page=self.engine.page(ident);doc=self.db.execute('SELECT sha FROM documents WHERE id=?',(page['doc'],)).fetchone()
  with Path(page['path']).open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
  if sha!=doc['sha']:raise ValueError('Оригінал джерела змінився. Імпорт заблоковано.')
  render=self.engine.render({'id':ident,'whole':True,'full':True,'preprocess':'original'})
  with Path(render['path']).open('rb') as stream:image_sha=hashlib.file_digest(stream,'sha256').hexdigest()
  info={'page':ident,'doc':page['doc'],'name':page['name'],'frame':page['num'],'source_sha256':sha,'image_sha256':image_sha,'width':render['width'],'height':render['height'],'path':render['path']}
  info['signature']=digest(info|{'annotations':self.annotations({'id':ident})})
  return info
 def interchange_preview(self,a):
  path=Path(a['path'])
  if not path.is_file() or path.stat().st_size>MAX_XML:raise ValueError('XML завеликий або не знайдений.')
  raw=path.read_bytes();parsed=parse_xml(raw,clip=True);target=self.target(a['id']);blocked=[]
  if (parsed['width'],parsed['height'])!=(target['width'],target['height']):blocked.append('dimensions_mismatch')
  if parsed['source_sha256'] and parsed['source_sha256']!=target['source_sha256']:blocked.append('source_sha_mismatch')
  if parsed['image_sha256'] and parsed['image_sha256']!=target['image_sha256']:blocked.append('image_sha_mismatch')
  if parsed['page_id'] and parsed['page_id']!=target['page']:blocked.append('page_identity_mismatch')
  # A filename is a clue, never proof. External tools commonly rename images.
  ambiguous=not (parsed['source_sha256'] and parsed['image_sha256'] and parsed['page_id'])
  token=uuid.uuid4().hex;value={'token':token,'parsed':parsed,'target':target,'blocked':blocked,'identity_confirmation_required':ambiguous,'clipping_confirmation_required':any(r['geometry_clipped'] for r in parsed['rows']),'xml_sha256':hashlib.sha256(raw).hexdigest(),'original_name':path.name,'policy':'New unverified regions only. Source XML retained byte-for-byte. Unsupported structures remain in the original XML; no universal schema conversion.'}
  with self.db:self.db.execute('INSERT INTO interchange_previews(id,page,signature,xml_sha256,xml,data) VALUES (?,?,?,?,?,?)',(token,a['id'],target['signature'],value['xml_sha256'],raw,json.dumps(value,ensure_ascii=False)))
  return value
 def interchange_apply(self,a):
  stored=self.db.execute('SELECT * FROM interchange_previews WHERE id=? AND page=?',(a['token'],a['id'])).fetchone()
  if not stored:raise ValueError('Спочатку перегляньте XML для цієї сторінки.')
  value=json.loads(stored['data'])
  if stored['applied']:raise ValueError('Цей імпорт уже застосовано.')
  if value['blocked']:raise ValueError('Зображення або джерело XML не відповідає сторінці.')
  if value.get('clipping_confirmation_required') and a.get('confirm_clipping') is not True:raise ValueError('Підтвердьте обрізання невеликих виходів за межі зображення.')
  if a.get('confirm') is not True:raise ValueError('Підтвердьте додавання неперевірених ділянок.')
  if value['identity_confirmation_required'] and a.get('confirm_identity') is not True:raise ValueError('Підтвердьте відповідність XML саме цій сторінці.')
  target=self.target(a['id'])
  if target['signature']!=stored['signature']:raise ValueError('Джерело або розмітка змінилися. Повторіть перегляд XML.')
  if hashlib.sha256(stored['xml']).hexdigest()!=stored['xml_sha256']:raise ValueError('Збережений XML пошкоджено.')
  rows=value['parsed']['rows'];ids={r['external_id']:uuid.uuid4().hex for r in rows};created=[]
  # BEGIN plus Workbench nested transactions would commit each region. Validate all
  # first, then a savepoint-safe direct insertion matching its annotation/audit shape.
  prepared=[]
  for row in rows:
   data={k:row[k] for k in ['kind','rect','text','polygon','baseline']};data.update(verified=False,_page=a['id'],interchange={'preview':a['token'],'xml_sha256':stored['xml_sha256'],'format':value['parsed']['format'],'external_id':row['external_id'],'sequence':row['sequence'],'order_source':row['order_source'],'original_external_id':row.get('original_external_id'),'external_id_generated':row.get('external_id_generated',False),'geometry_clipped':row.get('geometry_clipped',False),'original_geometry':row.get('original_geometry',{})})
   if row['reading_order'] is not None:data['reading_order']=row['reading_order']
   parent=row.get('parent_external')
   if parent:
    outer=next(r['rect'] for r in rows if r['external_id']==parent);inner=row['rect']
    if not(inner[0]>=outer[0] and inner[1]>=outer[1] and inner[0]+inner[2]<=outer[0]+outer[2]+1e-6 and inner[1]+inner[3]<=outer[1]+outer[3]+1e-6):raise ValueError('Дочірня ділянка XML виходить за межі батьківської.')
    data['parent']=ids[parent]
   prepared.append((ids[row['external_id']],a['id'],json.dumps(data,ensure_ascii=False)))
  with self.db:
   self.db.executemany('INSERT INTO annotations VALUES (?,?,?)',prepared)
   self.db.executemany('INSERT INTO annotation_history(annotation,before,after) VALUES (?,NULL,?)',[(r[0],r[2]) for r in prepared])
   self.db.execute('UPDATE interchange_previews SET applied=? WHERE id=?',(json.dumps({'created':[r[0] for r in prepared],'time':datetime.now(timezone.utc).isoformat()}),a['token']))
  return {'added':len(prepared),'annotations':[r[0] for r in prepared],'verified':False,'records_changed':False}
 def interchange_export(self,a):
  fmt=a.get('format','page')
  if fmt not in ['page','alto']:raise ValueError('Виберіть PAGE XML або ALTO XML.')
  target=self.target(a['id']);rows=[r for r in self.annotations({'id':a['id']}) if r['kind'] in ['line','entry','column']]
  if not rows:raise ValueError('Спочатку додайте текстову розмітку сторінки.')
  folder=self.engine.root/'results'/'interchange'/uuid.uuid4().hex;folder.mkdir(parents=True);shutil.copyfile(target['path'],folder/'image.png');w=target['width'];h=target['height']
  ns=PAGE if fmt=='page' else ALTO;ET.register_namespace('',ns);tag=lambda n:'{'+ns+'}'+n
  provenance='\n'.join('ArchiveReader '+k+'='+target[k] for k in ['source_sha256','image_sha256'])+'\nArchiveReader page_id='+target['page']
  exported=[];skipped_baselines=0
  def polygon(row):
   poly=row.get('polygon')
   if poly:
    checked=points(point_text(poly,w,h),w,h);rect=bounds(checked)
    # Do not silently reuse stale imported polygons after a rectangle was edited.
    if any(abs(a-b)>max(1/w,1/h)*2 for a,b in zip(rect,row['rect'])):return rect_polygon(row['rect']),False
    return poly,True
   return rect_polygon(row['rect']),False
  def geometry(node,row,page_format):
   nonlocal skipped_baselines
   poly,real=polygon(row)
   if page_format:ET.SubElement(node,tag('Coords'),{'points':point_text(poly,w,h)})
   elif real:ET.SubElement(ET.SubElement(node,tag('Shape')),tag('Polygon'),{'POINTS':point_text(poly,w,h)})
   baseline=row.get('baseline')
   if baseline and real:
    points(point_text(baseline,w,h),w,h,2)
    if page_format:ET.SubElement(node,tag('Baseline'),{'points':point_text(baseline,w,h)})
    else:node.set('BASELINE',point_text(baseline,w,h))
   elif baseline:skipped_baselines+=1
  # Export one text region per saved item to retain exact boxes and avoid inventing
  # missing parent bounds. PAGE line records are nested in a matching region.
  if fmt=='page':
   root=ET.Element(tag('PcGts'));metadata=ET.SubElement(root,tag('Metadata'));ET.SubElement(metadata,tag('Creator')).text='ArchiveReader';now=datetime.now(timezone.utc).isoformat();ET.SubElement(metadata,tag('Created')).text=now;ET.SubElement(metadata,tag('LastChange')).text=now;ET.SubElement(metadata,tag('Comments')).text=provenance
   page=ET.SubElement(root,tag('Page'),{'imageFilename':'image.png','imageWidth':str(w),'imageHeight':str(h)})
   ordered=[r for r in rows if type(r.get('reading_order')) is int]
   if ordered:
    ro=ET.SubElement(page,tag('ReadingOrder'));group=ET.SubElement(ro,tag('OrderedGroup'),{'id':'reading_order'})
    for n,row in enumerate(sorted(ordered,key=lambda r:r['reading_order'])):ET.SubElement(group,tag('RegionRefIndexed'),{'index':str(n),'regionRef':'r_'+row['id']})
   for row in rows:
    region=ET.SubElement(page,tag('TextRegion'),{'id':'r_'+row['id']});poly,_=polygon(row);ET.SubElement(region,tag('Coords'),{'points':point_text(poly,w,h)})
    node=ET.SubElement(region,tag('TextLine'),{'id':'l_'+row['id']}) if row['kind']=='line' else region
    if node is not region:geometry(node,row,True)
    if row.get('reading_order') is not None:node.set('custom','readingOrder {index:'+str(row['reading_order']-1)+';}')
    if row.get('text'):ET.SubElement(ET.SubElement(node,tag('TextEquiv')),tag('Unicode')).text=row['text']
    exported.append(row['id'])
  else:
   root=ET.Element(tag('alto'));description=ET.SubElement(root,tag('Description'));ET.SubElement(description,tag('MeasurementUnit')).text='pixel';ET.SubElement(ET.SubElement(description,tag('sourceImageInformation')),tag('fileName')).text='image.png';processing=ET.SubElement(description,tag('Processing'),{'ID':'processing'});ET.SubElement(processing,tag('processingStepSettings')).text=provenance
   ordered=[r for r in rows if type(r.get('reading_order')) is int]
   if ordered:
    group=ET.SubElement(ET.SubElement(root,tag('ReadingOrder')),tag('OrderedGroup'),{'ID':'reading_order'})
    for n,row in enumerate(sorted(ordered,key=lambda r:r['reading_order'])):ET.SubElement(group,tag('ElementRef'),{'ID':'ref_'+str(n),'REF':'l_'+row['id']})
   page=ET.SubElement(ET.SubElement(root,tag('Layout')),tag('Page'),{'ID':'page','PHYSICAL_IMG_NR':str(target['frame']+1),'WIDTH':str(w),'HEIGHT':str(h)});space=ET.SubElement(page,tag('PrintSpace'),{'HPOS':'0','VPOS':'0','WIDTH':str(w),'HEIGHT':str(h)})
   for row in rows:
    x,y,rw,rh=row['rect'];box={'HPOS':str(round(x*w)),'VPOS':str(round(y*h)),'WIDTH':str(max(1,round(rw*w))),'HEIGHT':str(max(1,round(rh*h)))};block=ET.SubElement(space,tag('TextBlock'),{'ID':'r_'+row['id']}|box);line=ET.SubElement(block,tag('TextLine'),{'ID':'l_'+row['id']}|box);geometry(line,row,False)
    ET.SubElement(line,tag('String'),{'ID':'s_'+row['id'],'CONTENT':row.get('text','')}|box)
    exported.append(row['id'])
  path=folder/(fmt+'.xml');ET.indent(root);ET.ElementTree(root).write(path,encoding='utf-8',xml_declaration=True)
  origins=[]
  for token in sorted({r.get('interchange',{}).get('preview') for r in rows if r.get('interchange',{}).get('preview')}):
   origin=self.db.execute('SELECT xml,xml_sha256,data FROM interchange_previews WHERE id=?',(token,)).fetchone()
   if origin:
    filename='source-'+token+'.xml';(folder/filename).write_bytes(origin['xml']);origins.append({'preview':token,'path':filename,'sha256':origin['xml_sha256'],'original_name':json.loads(origin['data']).get('original_name')})
  manifest={'format':fmt,'target':target,'annotations':exported,'original_xml':origins,'annotation_provenance':[{'id':r['id'],'verified':r.get('verified',False),'import':r.get('interchange')} for r in rows],'omitted_stale_baselines':skipped_baselines,'xml_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'policy':'Unverified OCR or imported text remains unverified; XML is an interchange subset, not a training reference.'};(folder/'provenance.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf-8')
  return {'path':str(path),'image':str(folder/'image.png'),'manifest':str(folder/'provenance.json'),'exported':len(exported),'omitted_stale_baselines':skipped_baselines}
