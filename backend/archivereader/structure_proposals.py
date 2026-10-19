"""Conservative ruled-grid proposals, never semantic classification or OCR masks."""
import math
from PIL import Image,ImageOps


def longest_ink(values):
    start=last=None;best=(0,0,0);ink=0
    for i,value in enumerate(values):
        if value:
            if last is None or i-last>3:start=i;ink=0
            last=i;ink+=1
            length=last-start+1
            if length>best[0] and ink/length>=.82:best=(length,start,last)
    return best


def bands(lines,thickness):
    groups=[]
    for pos,start,end in lines:
        if not groups or pos-groups[-1][-1][0]>2:groups.append([])
        groups[-1].append((pos,start,end))
    return [(round(sum(p[0] for p in group)/len(group)),min(p[1] for p in group),max(p[2] for p in group))
            for group in groups if group[-1][0]-group[0][0]+1<=thickness]


def suggest_structure(path):
    with Image.open(path) as source:
        if source.width*source.height>100_000_000:raise ValueError('Зображення завелике для аналізу сітки.')
        image=ImageOps.grayscale(source);image.thumbnail((850,850))
    width,height=image.size
    if min(width,height)<40:return {'candidates':[],'policy':'Image too small; no structure inferred.'}
    found=[]
    for angle in (0,-1.5,1.5,-3,3):
        rotated=image.rotate(angle,resample=Image.Resampling.BILINEAR,fillcolor=255)
        pixels=rotated.point(lambda value:1 if value<165 else 0).tobytes()
        horizontal=[];vertical=[]
        for y in range(height):
            length,start,end=longest_ink(pixels[y*width:(y+1)*width])
            if length>=width*.3:horizontal.append((y,start,end))
        for x in range(width):
            length,start,end=longest_ink(pixels[x::width])
            if length>=height*.23:vertical.append((x,start,end))
        horizontal=bands(horizontal,max(4,round(height*.012)))
        vertical=bands(vertical,max(4,round(width*.012)))
        if len(vertical)<3 or len(horizontal)<2:continue
        # Page borders/spines are not sufficient evidence of a table.
        if not any(height*.12<y<height*.88 for y,_,_ in horizontal):continue
        if not any(width*.12<x<width*.88 for x,_,_ in vertical):continue
        crosses=sum(hx1-4<=vx<=hx2+4 and vy1-4<=hy<=vy2+4
                    for hy,hx1,hx2 in horizontal for vx,vy1,vy2 in vertical)
        if crosses<6:continue
        left=min([x for x,_,_ in vertical]+[x1 for _,x1,_ in horizontal])
        right=max([x for x,_,_ in vertical]+[x2 for _,_,x2 in horizontal])
        top=min([y for y,_,_ in horizontal]+[y1 for _,y1,_ in vertical])
        bottom=max([y for y,_,_ in horizontal]+[y2 for _,_,y2 in vertical])
        theta=math.radians(angle);cx=width/2;cy=height/2
        corners=[(math.cos(theta)*(x-cx)-math.sin(theta)*(y-cy)+cx,
                  math.sin(theta)*(x-cx)+math.cos(theta)*(y-cy)+cy)
                 for x,y in [(left,top),(right,top),(right,bottom),(left,bottom)]]
        x1=max(0,min(x for x,y in corners)/width);x2=min(1,max(x for x,y in corners)/width)
        y1=max(0,min(y for x,y in corners)/height);y2=min(1,max(y for x,y in corners)/height)
        if x2-x1<.12 or y2-y1<.12:continue
        found.append({'role':'table','rect':[x1,y1,x2-x1,y2-y1],
                      'verified':False,'confidence':None,'method':'ruled_grid_heuristic',
                      'evidence':{'horizontal_bands':len(horizontal),'vertical_bands':len(vertical),
                                  'intersections':crosses,'analysis_angle':angle,'analysis_size':[width,height]},
                      'warning':'Можлива сітка. Це не підтверджені клітинки, рядки чи порядок читання.'})
    best=max(found,key=lambda r:r['evidence']['intersections'],default=None)
    return {'candidates':[best] if best else [],
            'policy':'Only possible ruled grids are proposed. No text/picture semantics, no automatic exclusions, no handwriting reconstruction. Human review required.'}


def cached_structure(path,cache_dir,force=False):
    """Reuse only identical pixels and algorithm/dependency versions; draft only."""
    import hashlib,json,os,time,uuid
    from pathlib import Path
    from PIL import __version__ as pillow_version
    started=time.perf_counter();path=Path(path);cache_dir=Path(cache_dir)
    with path.open('rb') as stream:image_sha=hashlib.file_digest(stream,'sha256').hexdigest()
    algorithm_sha=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    identity={'image_sha256':image_sha,'algorithm_sha256':algorithm_sha,'pillow':pillow_version,'schema':1}
    ident=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest();target=cache_dir/('structure-'+ident+'.json')
    hash_ms=(time.perf_counter()-started)*1000;hit=False;result=None
    try:
        if not force and target.stat().st_size<=262144:
            stored=json.loads(target.read_text('utf-8'))
            if stored.get('identity')==identity and _valid_cached_structure(stored.get('result')):result=stored['result'];hit=True
    except (OSError,ValueError,TypeError,RecursionError):pass
    analysis_started=time.perf_counter()
    if result is None:result=suggest_structure(path)
    analysis_ms=0 if hit else (time.perf_counter()-analysis_started)*1000
    persistence='available'
    if not hit:
        temporary=None
        try:
            cache_dir.mkdir(parents=True,exist_ok=True);temporary=cache_dir/('structure-write-'+uuid.uuid4().hex+'.tmp')
            temporary.write_text(json.dumps({'identity':identity,'result':result},ensure_ascii=False),'utf-8');os.replace(temporary,target)
        except OSError:persistence='unavailable'
        finally:
            if temporary is not None:
                try:temporary.unlink(missing_ok=True)
                except OSError:pass
    return result|{'cache':{'hit':hit,'identity':identity,'persistence':persistence},'timings_ms':{'input_hash':round(hash_ms,3),'analysis':round(analysis_ms,3),'total':round((time.perf_counter()-started)*1000,3)}}


def _valid_cached_structure(result):
    if not isinstance(result,dict) or not isinstance(result.get('candidates'),list) or len(result['candidates'])>20 or not isinstance(result.get('policy'),str):return False
    for candidate in result['candidates']:
        if not isinstance(candidate,dict) or candidate.get('verified') is not False or candidate.get('role')!='table' or candidate.get('confidence') is not None:return False
        rect=candidate.get('rect')
        if not isinstance(rect,list) or len(rect)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in rect):return False
        x,y,w,h=rect
        if not(0<=x<1 and 0<=y<1 and w>0 and h>0 and x+w<=1.000001 and y+h<=1.000001):return False
    return True
