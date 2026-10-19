"""Bounded same-book visual retrieval. Shape similarity never establishes text."""
import html,json,math,uuid
from pathlib import Path
import numpy as np
from PIL import Image,ImageOps
try:
 from .historical_reading import HistoricalTools
 from .layout import content_sha
 from .workbench import validate_rect
except ImportError:
 from historical_reading import HistoricalTools
 from layout import content_sha
 from workbench import validate_rect

def features(image):
 """Describe visible ink without inferring characters or filling missing strokes."""
 gray=ImageOps.autocontrast(image.convert('L'));a=np.asarray(gray,dtype=np.float32)/255
 ink=1-a
 if float(ink.max()-ink.min())<.03:return None
 mask=ink>max(.12,float(np.quantile(ink,.70)))
 yy,xx=np.where(mask)
 if len(xx)<6:return None
 box=(int(xx.min()),int(yy.min()),int(xx.max()+1),int(yy.max()+1));gray=gray.crop(box)
 width=max(4,min(96,round(gray.width*40/max(1,gray.height))))
 arr=1-np.asarray(gray.resize((width,40),Image.Resampling.BILINEAR),dtype=np.float32)/255
 # Eight vertical ink bands per column; preserve neighbouring stroke structure.
 seq=arr.reshape(8,5,width).mean(axis=1).T
 small=np.asarray(gray.resize((32,16),Image.Resampling.BILINEAR),dtype=np.float32).reshape(-1)/255
 return seq,small

def dtw(left,right):
 """Align bounded feature sequences; the returned distance is not confidence."""
 n,m=len(left),len(right);previous=np.full(m+1,np.inf);previous[0]=0
 distances=np.sqrt(((left[:,None,:]-right[None,:,:])**2).mean(axis=2))
 band=max(abs(n-m)+2,math.ceil(max(n,m)*.3))
 for i in range(1,n+1):
  current=np.full(m+1,np.inf)
  for j in range(max(1,i-band),min(m,i+band)+1):current[j]=float(distances[i-1,j-1])+min(previous[j],current[j-1],previous[j-1])
  previous=current
 return float(previous[m]/(n+m))

class ShapeSearch(HistoricalTools):
 def shape_search(self,a):
  page=a['id'];rect=validate_rect(a['rect']);source=self._source(page);docs=self._docs(source['doc']);query_image=self.whole_image(page)
  def crop(image,r):
   x,y,w,h=r;return image.crop((round(x*image.width),round(y*image.height),min(image.width,round((x+w)*image.width)),min(image.height,round((y+h)*image.height))))
  query=crop(query_image,rect);q=features(query)
  if q is None:raise ValueError('У фрагменті недостатньо видимих штрихів.')
  folder=self.engine.root/'results'/('shape-search-'+uuid.uuid4().hex);folder.mkdir();query.save(folder/'query.png')
  rows=list(self.db.execute("SELECT a.id,a.page,a.data,p.doc,p.num,d.name,d.path,d.sha FROM annotations a JOIN pages p ON p.id=a.page JOIN documents d ON d.id=p.doc WHERE json_extract(a.data,'$.kind') IN ('line','entry') AND p.doc IN ("+','.join('?' for _ in docs)+') ORDER BY a.rowid DESC LIMIT 301',docs))
  query_path=self.engine.page(page)['path']
  scanned=0;windows=0;shortlist=[];seen=set();pages=set();bindings=[];sources={query_path:source['source_sha256']};last_page=None;image=None
  for row in rows[:300]:
   region=json.loads(row['data'])
   if region.get('kind') not in ['line','entry'] or not region.get('rect'):continue
   if windows>=3000:break
   if len(pages)>=12 and row['page'] not in pages:continue
   if row['path'] not in sources:sources[row['path']]=content_sha(row['path'])
   if sources[row['path']]!=row['sha']:continue
   r=region['rect'];identity=(row['page'],tuple(r))
   if r[3]>.25:continue
   if identity in seen:continue
   seen.add(identity)
   # Exclude the query itself, including a parent line window overlapping it.
   if last_page!=row['page']:image=self.whole_image(row['page']);last_page=row['page']
   pages.add(row['page']);candidate=crop(image,r)
   if candidate.width<3 or candidate.height<3:continue
   bindings.append((row['id'],row['data']));scanned+=1
   target=max(4,round(candidate.height*query.width/max(1,query.height)))
   widths=sorted({min(candidate.width,max(4,round(target*k))) for k in [.8,1,1.25]})
   for width in widths:
    count=min(12,max(1,math.ceil(candidate.width/max(1,width/2))))
    for x in sorted({round(v) for v in np.linspace(0,max(0,candidate.width-width),count)}):
     if windows>=3000:break
     subrect=[r[0]+x/image.width,r[1],width/image.width,r[3]]
     if row['page']==page:
      ix=max(0,min(subrect[0]+subrect[2],rect[0]+rect[2])-max(subrect[0],rect[0]));iy=max(0,min(subrect[1]+subrect[3],rect[1]+rect[3])-max(subrect[1],rect[1]))
      if ix*iy/max(1e-9,rect[2]*rect[3])>.5:continue
     fragment=candidate.crop((x,0,x+width,candidate.height));f=features(fragment)
     if f is None:continue
     windows+=1;rough=float(np.sqrt(np.mean((q[1]-f[1])**2)))
     shortlist.append((rough,{'page':row['page'],'number':row['num']+1,'document':row['name'],'annotation':row['id'],'rect':subrect,'whole_region_text':region.get('text',''),'text_status':'human_confirmed_whole_region' if region.get('verified') else 'unverified_whole_region','fragment_text':None,'writer_known':False},f[0],fragment.copy()))
     shortlist.sort(key=lambda item:item[0]);shortlist=shortlist[:30]
  # The cheap descriptor limits expensive DTW to a small candidate shortlist.
  ranked=[]
  for _,meta,sequence,fragment in shortlist:ranked.append((dtw(q[0],sequence),meta,fragment))
  ranked.sort(key=lambda item:item[0]);results=[]
  for distance,meta,fragment in ranked:
   if any(m['page']==meta['page'] and abs(m['rect'][0]-meta['rect'][0])<meta['rect'][2]*.5 and abs(m['rect'][1]-meta['rect'][1])<.01 for m in results):continue
   path=folder/f'match-{len(results)+1}.png';fragment.save(path);results.append(meta|{'distance':distance,'path':str(path),'verified':False})
   if len(results)==8:break
  # Reject stale evidence if a source or its annotation changed during retrieval.
  for path,sha in sources.items():
   if content_sha(path)!=sha:raise ValueError('Оригінал змінився під час пошуку.')
  if self._docs(source['doc'])!=docs:raise ValueError('Склад книги змінився під час пошуку.')
  for ident,before in bindings:
   current=self.db.execute('SELECT data FROM annotations WHERE id=?',(ident,)).fetchone()
   if not current or current[0]!=before:raise ValueError('Розмітка змінилася під час пошуку.')
  report={'query':{'page':page,'rect':rect,'path':str(folder/'query.png'),'source_sha256':source['source_sha256']},'results':results,'scanned_regions':scanned,'windows':windows,'limits':{'region_limit':300,'page_limit':12,'window_limit':3000,'dtw_shortlist':30,'bounded_search':True},'policy':'Visual ink features + DTW, not a trained Siamese network or letter classifier. Lower distance is closer shape, not probability. No inferred writer, fragment transcription, text replacement, verification or training.'}
  (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
  body=''.join('<tr><td><img style="max-width:500px" src="'+Path(r['path']).name+'"></td><td>'+html.escape(r['document'])+' · '+str(r['number'])+'<br>DTW '+format(r['distance'],'.4f')+'<br>'+html.escape(r['text_status'])+'<p>'+html.escape(r['whole_region_text'])+'</p></td></tr>' for r in results)
  (folder/'report.html').write_text('<meta charset="utf-8"><h1>Пошук схожої форми</h1><p>Схожість не є прочитанням літери. Текст поруч належить цілому рядку, а не знайденому фрагменту. Писар не визначався. Пошук обмежений 300 ділянками й 12 сторінками.</p><h2>Запит</h2><img style="max-width:600px" src="query.png"><table border="1">'+body+'</table>','utf-8');report['report']=str(folder/'report.html');return report
