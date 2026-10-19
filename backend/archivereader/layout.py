"""Reviewable geometry proposals and isolated OCR of saved page regions."""
import hashlib
import json
import math
from pathlib import Path
import statistics
import shutil
import importlib.metadata
import uuid
import os
import sys

try:
    from .workbench import Workbench,validate_rect,overlaps
    from .engine import run_process,parse_alto
except ImportError:
    from workbench import Workbench,validate_rect,overlaps
    from engine import run_process,parse_alto


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def content_sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def thread_limit(a):
    value=a.get('threads',2)
    return max(1,min(4,value)) if type(value) is int else 2


def bounded_rect(box,width,height,scope):
    if not box or len(box)!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in box): return None
    x,y,w,h=box
    left=max(0,x)/width; top=max(0,y)/height; right=min(width,x+w)/width; bottom=min(height,y+h)/height
    if right-left<=0 or bottom-top<=0: return None
    rx,ry,rw,rh=scope
    rect=[rx+left*rw,ry+top*rh,(right-left)*rw,(bottom-top)*rh]
    if min(rect[2:])<.002: return None
    validate_rect(rect)
    return rect


def union_rect(rows):
    boxes=[r['rect'] for r in rows]; x=min(b[0] for b in boxes); y=min(b[1] for b in boxes)
    return [x,y,max(b[0]+b[2] for b in boxes)-x,max(b[1]+b[3] for b in boxes)-y]


def column_groups(lines,scope):
    """Conservative left-edge clusters; wide headings remain separate."""
    if len(lines)<4: return [lines] if lines else []
    narrow=[r for r in lines if r['rect'][2]<scope[2]*.65]
    wide=[r for r in lines if r not in narrow]
    if not narrow: return [lines]
    tolerance=max(scope[2]*.035,statistics.median(r['rect'][2] for r in narrow)*.15)
    groups=[]
    for row in sorted(narrow,key=lambda r:r['rect'][0]):
        match=next((g for g in groups if abs(row['rect'][0]-statistics.median(r['rect'][0] for r in g))<=tolerance),None)
        if match is None: groups.append([row])
        else: match.append(row)
    strong=[g for g in groups if len(g)>=3]
    if len(strong)<2: return [lines]
    leftovers=wide+[r for g in groups if len(g)<3 for r in g]
    # Short leftovers can join the closest column; cross-column headings cannot.
    for row in leftovers:
        g=min(strong,key=lambda g:abs(row['rect'][0]-union_rect(g)[0]))
        outer=union_rect(g)
        if row['rect'][0]>=outer[0]-.02 and row['rect'][0]+row['rect'][2]<=outer[0]+outer[2]+.02: g.append(row)
        else: strong.append([row])
    return sorted(strong,key=lambda g:(union_rect(g)[0],union_rect(g)[1]))


def row_groups(lines):
    groups=[]
    tolerance=statistics.median(r['rect'][3] for r in lines)*.65 if lines else 0
    for row in sorted(lines,key=lambda r:r['rect'][1]+r['rect'][3]/2):
        middle=row['rect'][1]+row['rect'][3]/2
        match=next((g for g in reversed(groups) if abs(middle-statistics.median(r['rect'][1]+r['rect'][3]/2 for r in g))<=tolerance),None)
        if match is None: groups.append([row])
        else: match.append(row)
    return groups


def horizontal_rules(image,scope):
    from PIL import ImageOps
    gray=ImageOps.autocontrast(image.convert('L')); gray.thumbnail((1000,1600))
    pixels=list(gray.get_flattened_data()); positions=[]
    for y in range(gray.height):
        run=longest=gaps=0
        for value in pixels[y*gray.width:(y+1)*gray.width]:
            if value<95: run+=1; gaps=0
            elif gaps<2 and run: run+=1; gaps+=1
            else: longest=max(longest,run); run=gaps=0
        if max(longest,run)>=gray.width*.42: positions.append(y)
    bands=[]
    for y in positions:
        if bands and y-bands[-1][-1]<=3: bands[-1].append(y)
        else: bands.append([y])
    return [scope[1]+statistics.mean(band)/gray.height*scope[3] for band in bands]


def proposals(lines,scope,mode,rules=(),parent=None):
    """No text-based inference of dates, persons or event types."""
    regions=[]
    def add(kind,rows,label,owner=None):
        ident='draft-'+uuid.uuid4().hex
        regions.append({'id':ident,'kind':kind,'rect':union_rect(rows),'label':label,'parent':owner,
                        'text':'','verified':False,'suggested':True})
        return ident
    groups=column_groups(lines,scope) if mode=='columns' else [lines]
    if mode=='table':
        # Physical ruling is stronger evidence for entry boundaries than line gaps.
        if len(rules)>=3:
            bands=[scope[1]]+sorted(rules)+[scope[1]+scope[3]]
            entries=[]
            for top,bottom in zip(bands,bands[1:]):
                rows=[r for r in lines if top<=r['rect'][1]+r['rect'][3]/2<bottom]
                if rows: entries.append(rows)
        else: entries=row_groups(lines)
        for i,rows in enumerate(entries):
            entry=add('entry',rows,str(i+1),parent)
            for j,row in enumerate(sorted(rows,key=lambda r:(r['rect'][0],r['rect'][1]))):
                add('line',[row],str(j+1),entry)
    else:
        for i,group in enumerate(groups):
            if not group: continue
            owner=parent
            if mode=='columns' and parent is None: owner=add('column',group,str(i+1))
            ordered=sorted(group,key=lambda r:(r['rect'][1],r['rect'][0]))
            typical=statistics.median(r['rect'][3] for r in ordered)
            paragraphs=[]
            for row in ordered:
                if paragraphs and row['rect'][1]-(paragraphs[-1][-1]['rect'][1]+paragraphs[-1][-1]['rect'][3])<=typical*.8: paragraphs[-1].append(row)
                else: paragraphs.append([row])
            for rows in paragraphs:
                entry=add('entry',rows,str(len(regions)+1),owner)
                for row in rows: add('line',[row],str(len(regions)+1),entry)
    for i,region in enumerate(regions): region['reading_order']=i+1
    return regions


class LayoutTools(Workbench):
    def __init__(self,engine):
        super().__init__(engine)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS layout_proposals(id TEXT PRIMARY KEY,page TEXT,data TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS region_recognition(id TEXT PRIMARY KEY,page TEXT,annotation TEXT,data TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')

    def scope(self,a,allowed_kinds=('entry','column')):
        page=self.engine.page(a['id']); region=None
        if a.get('annotation'):
            region=next((r for r in self.annotations({'id':page['id']}) if r['id']==a['annotation']),None)
            if not region or region['kind'] not in allowed_kinds: raise ValueError('Виберіть збережений запис або колонку.')
        scope=region['rect'] if region else [0,0,1,1]
        rendering=self.region_crop({'id':page['id'],'annotation':region['id']}) if region else self.engine.render({'id':page['id'],'whole':True,'full':True})
        return page,region,scope,rendering

    def layout_propose(self,a):
        page,region,scope,rendering=self.scope(a)
        mode=a.get('mode','columns')
        if mode not in ['columns','table','text']: raise ValueError('Неправильний порядок читання.')
        lines=[]; method='kraken-baseline-segmentation'
        if a.get('reuse',True) and json.loads(page['lines']):
            method='existing-ocr-geometry'
            old=self.engine.render({'id':page['id'],'full':True})
            roi=json.loads(page['roi']) or [0,0,1,1]
            for line in json.loads(page['lines']):
                rect=bounded_rect(line.get('box'),old['width'],old['height'],roi)
                if rect and rect[0]>=scope[0] and rect[1]>=scope[1] and rect[0]+rect[2]<=scope[0]+scope[2]+.000001 and rect[1]+rect[3]<=scope[1]+scope[3]+.000001:
                    lines.append({'rect':rect})
        if not lines:
            method='kraken-baseline-segmentation'
            folder=self.engine.root/'results'/('layout-'+uuid.uuid4().hex); folder.mkdir()
            output=folder/'segmentation.json'
            cmd=[a.get('executable','kraken'),'-r','-n','-i',rendering['path'],str(output),'--threads',str(thread_limit(a)),'segment','-bl']
            if a.get('segmentation'): cmd+=['-i',a['segmentation']]
            run_process(cmd,a.get('timeout',300))
            data=json.loads(output.read_text(encoding='utf-8'))
            for line in data.get('lines',[]):
                boundary=line.get('boundary')
                if boundary:
                    x=min(p[0] for p in boundary); y=min(p[1] for p in boundary)
                    box=[x,y,max(p[0] for p in boundary)-x,max(p[1] for p in boundary)-y]
                elif line.get('bbox'):
                    x,y,right,bottom=line['bbox']; box=[x,y,right-x,bottom-y]
                else: continue
                rect=bounded_rect(box,rendering['width'],rendering['height'],scope)
                if rect: lines.append({'rect':rect})
        if not lines: raise ValueError('Рядків не знайдено. Спробуйте іншу модель сегментації або розмітьте вручну.')
        rules=[]
        if mode=='table':
            from PIL import Image
            with Image.open(rendering['path']) as image: rules=horizontal_rules(image,scope)
        draft=[]
        anchors=[r for r in self.annotations({'id':page['id']}) if r['kind']=='column'] if mode=='columns' and region is None else []
        remaining=lines[:]
        for anchor in sorted(anchors,key=lambda r:(r.get('reading_order',100000),r['rect'][0])):
            x,y,w,h=anchor['rect']
            contained=[r for r in remaining if r['rect'][0]>=x and r['rect'][1]>=y and r['rect'][0]+r['rect'][2]<=x+w+.000001 and r['rect'][1]+r['rect'][3]<=y+h+.000001]
            draft+=proposals(contained,anchor['rect'],mode,parent=anchor['id'])
            remaining=[r for r in remaining if r not in contained]
        draft+=proposals(remaining,scope,mode,rules,region['id'] if region else None)
        for i,r in enumerate(draft): r['reading_order']=i+1
        ident=uuid.uuid4().hex
        data={'regions':draft,'method':method,'mode':mode,'rules':len(rules),'snapshot':fingerprint(self.annotations({'id':page['id']})),
              'limitation':'Geometry proposals only. Entries may merge/split incorrectly; no semantic event classification or trained reading-order claim.'}
        with self.db: self.db.execute('INSERT INTO layout_proposals(id,page,data) VALUES (?,?,?)',(ident,page['id'],json.dumps(data,ensure_ascii=False)))
        return data|{'id':ident}

    def layout_apply(self,a):
        row=self.db.execute('SELECT data FROM layout_proposals WHERE id=? AND page=?',(a['proposal'],a['id'])).fetchone()
        if not row: raise ValueError('Пропозицію не знайдено.')
        data=json.loads(row['data']); existing=self.annotations({'id':a['id']})
        if data.get('source_sha256'):
            page=self.engine.page(a['id'])
            if content_sha(page['path'])!=data['source_sha256']:raise ValueError('Оригінал джерела змінився. Оновіть бібліотеку.')
            if data.get('crop_sha256'):
                current=self.region_crop({'id':a['id'],'annotation':data['scope_annotation']}) if data.get('scope_annotation') else self.engine.render({'id':a['id'],'whole':True,'full':True})
                if content_sha(current['path'])!=data['crop_sha256']:raise ValueError('Результат змінився. Оновіть список.')
        if data['snapshot']!=fingerprint(existing): raise ValueError('Результат змінився. Оновіть список.')
        chosen=set(a.get('regions',[])); lookup={r['id']:r for r in data['regions']}
        if not chosen or not chosen<=lookup.keys(): raise ValueError('Виберіть пропозиції для збереження.')
        for ident in list(chosen):
            parent=lookup[ident].get('parent')
            while parent in lookup: chosen.add(parent); parent=lookup[parent].get('parent')
        mapping={}; added=0; last_order=max([r.get('reading_order',0) for r in existing]+[0])
        for region in data['regions']:
            if region['id'] not in chosen: continue
            match=next((r for r in existing if r['kind']==region['kind'] and all(abs(x-y)<.001 for x,y in zip(r['rect'],region['rect']))),None)
            if match: mapping[region['id']]=match['id']; continue
            values=region.copy(); values['parent']=mapping.get(region.get('parent'),region.get('parent'))
            last_order+=1; values['reading_order']=last_order; values['proposal']=a['proposal']
            saved=self.save_annotation({'page':a['id'],'data':values})['id']; mapping[region['id']]=saved; added+=1
        return {'added':added,'ids':mapping}

    def layout_order(self,a):
        rows=self.annotations({'id':a['id']}); regions={r['id']:r for r in rows if r['kind'] in ['column','entry','line']}
        ids=a['regions']
        if len(ids)!=len(set(ids)) or set(ids)!=regions.keys(): raise ValueError('Результат змінився. Оновіть список.')
        for i,ident in enumerate(ids): self.save_annotation({'page':a['id'],'annotation':ident,'data':regions[ident]|{'reading_order':i+1}})
        return {'saved':True}

    def recognize_region(self,a):
        if not a.get('annotation'): raise ValueError('Виберіть збережений запис або колонку.')
        page,region,scope,rendering=self.scope(a,('line','entry','column'))
        if any(r['kind'] in ['damage','missing'] and overlaps(scope,r['rect']) for r in self.annotations({'id':page['id']})):
            raise ValueError('Ділянка перетинає позначене пошкодження. Перевірте межі перед повторним розпізнаванням.')
        saved_rows=self.annotations({'id':page['id']})
        family={region['id']}
        while True:
            children={r['id'] for r in saved_rows if r.get('parent') in family}
            if children<=family:break
            family|=children
        manual_lines=sorted([r for r in saved_rows if r['id'] in family and r['id']!=region['id'] and r['kind']=='line' and (not r.get('suggested') or r.get('verified'))],key=lambda r:(r.get('reading_order',100000),r['rect'][1],r['rect'][0])) if a.get('use_saved_lines',True) and region['kind']!='line' else []
        for line in manual_lines:
            x,y,w,h=line['rect'];sx,sy,sw,sh=scope
            if x<sx or y<sy or x+w>sx+sw+.000001 or y+h>sy+sh+.000001:raise ValueError('Saved line lies outside its parent region.')
        base_input_sha=content_sha(rendering['path'])
        variant=a.get('variant','original')
        if variant not in ['original','upscale2','contrast']:raise ValueError('Unknown image variant.')
        if variant!='original':
            from PIL import Image,ImageOps
            with Image.open(rendering['path']) as image:
                image=image.convert('RGB')
                if variant=='upscale2':
                    if image.width*image.height>20000000:raise ValueError('Region too large for enlargement.')
                    image=image.resize((image.width*2,image.height*2),Image.Resampling.LANCZOS)
                else:image=ImageOps.autocontrast(image,cutoff=1)
                variant_path=self.engine.root/'cache'/('region-variant-'+fingerprint([base_input_sha,variant])+'.png');image.save(variant_path)
                rendering=rendering|{'path':str(variant_path),'width':image.width,'height':image.height}
        model=Path(a.get('model',''))
        if not model.is_file(): raise ValueError('Виберіть локальну модель Kraken (.mlmodel або .safetensors).')
        mode=a.get('mode','columns')
        if mode not in ['columns','table','text']: raise ValueError('Неправильний порядок читання.')
        try:from .model_identity import fingerprint_models
        except ImportError:from model_identity import fingerprint_models
        original=self.db.execute('SELECT path,sha FROM documents WHERE id=?',(page['doc'],)).fetchone()
        actual=content_sha(original['path'])
        if actual!=original['sha']:raise ValueError('Оригінал джерела змінився. Оновіть бібліотеку.')
        models=fingerprint_models(a)
        executable=str(a.get('executable','kraken'));resolved_executable=shutil.which(executable)
        try:runtime_version=importlib.metadata.version('kraken')
        except importlib.metadata.PackageNotFoundError:runtime_version=None
        identity={'version':1,'page':page['id'],'source_sha256':actual,'region':region,
                  'input_sha256':content_sha(rendering['path']),'base_input_sha256':base_input_sha,'variant':variant,'saved_lines':manual_lines,'models':models,
                  'mode':mode,'executable':executable,'executable_sha256':content_sha(resolved_executable) if resolved_executable else None,
                  'kraken_runtime_version':runtime_version,'threads':thread_limit(a),'pipeline':'kraken-baseline-alto-v2','pipeline_sha256':content_sha(__file__)}
        expected_executable=Path(sys.executable).resolve().parent/('kraken.exe' if os.name=='nt' else 'kraken')
        native=os.environ.get('ARCHIVEREADER_MODEL_SESSION')=='1' and ((executable=='kraken' and not resolved_executable) or (resolved_executable and Path(resolved_executable).resolve()==expected_executable))
        identity['transport']='persistent_native' if native else 'cli'
        if native:
            try:from . import recognizers
            except ImportError:import recognizers
            identity['adapter_sha256']=content_sha(recognizers.__file__)
            if region['kind']!='line' and not manual_lines and not a.get('segmentation'):
                from importlib import resources
                identity['default_segmentation_sha256']=content_sha(resources.files('kraken').joinpath('blla.mlmodel'))
        reused_layout=None
        if a.get('reuse_layout_run'):
            if not native or manual_lines or region['kind']=='line':raise ValueError('Saved page layout reuse requires the native page recognizer.')
            old=self.db.execute('SELECT data FROM region_recognition WHERE id=? AND page=? AND annotation=?',(a['reuse_layout_run'],page['id'],region['id'])).fetchone()
            if not old:raise ValueError('Результат не знайдено.')
            old=json.loads(old['data']);reused_layout=Path(old['path'])/'result.alto.xml'
            if old.get('snapshot')!=fingerprint(region) or old.get('source_sha256')!=actual or old.get('input_sha256')!=content_sha(rendering['path']) or not reused_layout.is_file() or content_sha(reused_layout)!=old.get('output_sha256'):raise ValueError('Saved layout no longer matches the source crop.')
            identity['reused_layout']={'run':a['reuse_layout_run'],'sha256':content_sha(reused_layout)}
        cache_key=fingerprint(identity)
        if a.get('force') is not True:
            for old in self.db.execute('SELECT id,data FROM region_recognition WHERE page=? AND annotation=? ORDER BY rowid DESC LIMIT 100',(page['id'],region['id'])):
                data=json.loads(old['data']);artifact=Path(data.get('path',''))/'result.alto.xml'
                if data.get('cache_key')==cache_key and artifact.is_file() and content_sha(artifact)==data.get('output_sha256'):
                    return data|{'id':old['id'],'reused':True}
        folder=self.engine.root/'results'/('region-ocr-'+uuid.uuid4().hex); folder.mkdir()
        source=folder/'input.png'; source.write_bytes(Path(rendering['path']).read_bytes()); output=folder/'result.alto.xml'
        cmd=[a.get('executable','kraken'),'-r','-a','-i',str(source),str(output),'--threads',str(thread_limit(a))]
        if region['kind']=='line':cmd+=['ocr','--no-segmentation','-m',str(model)]
        else:
            cmd+=['segment','-bl']
            if a.get('segmentation'):cmd+=['-i',a['segmentation']]
            cmd+=['ocr','-m',str(model)]
        child_runs=[]
        if manual_lines:
            from xml.etree.ElementTree import Element,SubElement,tostring
            root=Element('alto')
            for line in manual_lines:
                result=self.recognize_region(a|{'annotation':line['id'],'use_saved_lines':False})
                child_runs.append({'annotation':line['id'],'run':result['id']})
                x,y,w,h=line['rect'];sx,sy,sw,sh=scope
                element=SubElement(root,'TextLine',HPOS=str((x-sx)/sw*rendering['width']),VPOS=str((y-sy)/sh*rendering['height']),WIDTH=str(w/sw*rendering['width']),HEIGHT=str(h/sh*rendering['height']))
                SubElement(element,'String',CONTENT=result['text'])
            output.write_bytes(tostring(root,encoding='utf-8',xml_declaration=True))
        elif native:
            if reused_layout:recognizers.kraken_region(source,model,output,a.get('segmentation'),False,thread_limit(a),layout_xml=reused_layout)
            else:recognizers.kraken_region(source,model,output,a.get('segmentation'),region['kind']=='line',thread_limit(a))
        else:run_process(cmd,a.get('timeout',300))
        lines=[]
        for line in parse_alto(output):
            rect=bounded_rect(line['box'],rendering['width'],rendering['height'],scope)
            if rect: lines.append(line|{'rect':rect})
        if reused_layout and content_sha(reused_layout)!=identity['reused_layout']['sha256']:raise ValueError('Saved layout changed during recognition.')
        if native and identity.get('default_segmentation_sha256') and identity['default_segmentation_sha256']!=content_sha(resources.files('kraken').joinpath('blla.mlmodel')):raise ValueError('Segmentation model changed during recognition.')
        current=next((r for r in self.annotations({'id':page['id']}) if r['id']==region['id']),None)
        refreshed=self.region_crop({'id':page['id'],'annotation':region['id']}) if current else None
        if current!=region or content_sha(original['path'])!=actual or fingerprint_models(a)!=models or not refreshed or content_sha(refreshed['path'])!=base_input_sha:
            raise ValueError('Джерело, ділянка або модель змінилися під час розпізнавання. Повторіть спробу.')
        if manual_lines and any(next((r for r in self.annotations({'id':page['id']}) if r['id']==line['id']),None)!=line for line in manual_lines):raise ValueError('Saved lines changed during recognition.')
        if manual_lines:ordered=lines
        elif mode=='columns': ordered=[r for group in column_groups(lines,scope) for r in sorted(group,key=lambda r:(r['rect'][1],r['rect'][0]))]
        else: ordered=[r for group in row_groups(lines) for r in sorted(group,key=lambda r:r['rect'][0])]
        ident=uuid.uuid4().hex
        data={'text':'\n'.join(r['text'] for r in ordered),'lines':ordered,'rect':scope,'annotation':region['id'],'snapshot':fingerprint(region),
              'model_sha256':content_sha(model),'input_sha256':content_sha(source),
              'source_sha256':self.db.execute('SELECT sha FROM documents WHERE id=?',(page['doc'],)).fetchone()['sha'],
              'path':str(folder),'mode':mode,'variant':variant,'base_input_sha256':base_input_sha,'saved_lines':manual_lines,'child_runs':child_runs,'verified':False,'cache_key':cache_key,'identity':identity,'output_sha256':content_sha(output)}
        empty=sum(not r['text'].strip() for r in ordered)
        data['review_flags']=(['no_readable_lines'] if not ordered or empty==len(ordered) else ['mostly_empty_lines_check_segmentation'] if empty>len(ordered)/2 else [])
        (folder/'result.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        with self.db: self.db.execute('INSERT INTO region_recognition(id,page,annotation,data) VALUES (?,?,?,?)',(ident,page['id'],region['id'],json.dumps(data,ensure_ascii=False)))
        return data|{'id':ident,'reused':False}

    def region_recognition_apply(self,a):
        row=self.db.execute('SELECT * FROM region_recognition WHERE id=? AND page=?',(a['run'],a['id'])).fetchone()
        if not row: raise ValueError('Результат не знайдено.')
        region=next((r for r in self.annotations({'id':a['id']}) if r['id']==row['annotation']),None)
        data=json.loads(row['data'])
        if not region or fingerprint(region)!=data['snapshot']: raise ValueError('Результат змінився. Оновіть список.')
        if any(r['kind'] in ['damage','missing'] and overlaps(region['rect'],r['rect']) for r in self.annotations({'id':a['id']})):
            raise ValueError('Ділянка перетинає позначене пошкодження. Перевірте результат вручну.')
        page=self.engine.page(a['id']);original=self.db.execute('SELECT path,sha FROM documents WHERE id=?',(page['doc'],)).fetchone()
        if content_sha(original['path'])!=data.get('source_sha256') or original['sha']!=data.get('source_sha256'):
            raise ValueError('Оригінал джерела змінився. Розпізнайте ділянку повторно.')
        crop=self.region_crop({'id':a['id'],'annotation':region['id']})
        if content_sha(crop['path'])!=data.get('base_input_sha256',data.get('input_sha256')):raise ValueError('Зображення ділянки змінилося. Розпізнайте повторно.')
        if data.get('saved_lines') and any(next((r for r in self.annotations({'id':a['id']}) if r['id']==line['id']),None)!=line for line in data['saved_lines']):raise ValueError('Saved lines changed during recognition.')
        added=0; conflicts=[];children=self.annotations({'id':a['id']})
        for i,line in enumerate(data['lines']):
            manual=data.get('saved_lines',[])
            match=next((r for r in children if i<len(manual) and r['id']==manual[i]['id']),None) if manual else next((r for r in children if r['kind']=='line' and r.get('parent')==region['id'] and all(abs(x-y)<.001 for x,y in zip(r['rect'],line['rect']))),None)
            if match:
                if match.get('text','')!=line['text']:conflicts.append({'annotation':match['id'],'existing_text':match.get('text',''),'proposed_text':line['text'],'verified':match.get('verified',False)})
                continue
            self.save_annotation({'page':a['id'],'data':{'kind':'line','rect':line['rect'],'parent':region['id'],'text':line['text'],
               'verified':False,'suggested':True,'recognition_run':a['run'],'label':str(i+1)}}); added+=1
        return {'added':added,'conflicts':conflicts,'overwritten':False}

    def region_ordered_text(self,a):
        if not a.get('annotation'): raise ValueError('Виберіть збережений запис або колонку.')
        page,region,scope,_=self.scope(a)
        rows=self.annotations({'id':page['id']}); family={region['id']}
        while True:
            children={r['id'] for r in rows if r.get('parent') in family}
            if children<=family: break
            family|=children
        lines=[r for r in rows if r['id'] in family and r['kind']=='line']
        lines.sort(key=lambda r:(r.get('reading_order',100000),r['rect'][1],r['rect'][0]))
        return {'annotation':region['id'],'rect':scope,'text':'\n'.join(r.get('text','') for r in lines),'lines':len(lines)}


    def layout_quality(self,a):
        page=self.engine.page(a['id']);rows=self.annotations({'id':page['id']});lines=[r for r in rows if r['kind']=='line'];issues=[]
        median=statistics.median(r['rect'][3] for r in lines) if lines else 0
        for r in lines:
            x,y,w,h=r['rect']
            if w<.02 or (median and h<median*.35):issues.append({'kind':'tiny','annotations':[r['id']]})
        # Bound pair checks for large pages; the report explicitly states truncation.
        for i,r in enumerate(lines[:500]):
            for other in lines[:500][i+1:]:
                if r.get('parent')!=other.get('parent'):continue
                x,y,w,h=r['rect'];u,v,z,t=other['rect'];area=max(0,min(x+w,u+z)-max(x,u))*max(0,min(y+h,v+t)-max(y,v))
                if area>.2*min(w*h,z*t):issues.append({'kind':'overlap','annotations':[r['id'],other['id']]})
        for parent in [r for r in rows if r['kind']=='entry']:
            children=sorted([r for r in lines if r.get('parent')==parent['id']],key=lambda r:r['rect'][1])
            for left,right in zip(children,children[1:]):
                if right['rect'][1]-(left['rect'][1]+left['rect'][3])>max(left['rect'][3],right['rect'][3])*1.5:issues.append({'kind':'possible_gap','annotations':[left['id'],right['id']]})
        return {'snapshot':fingerprint(rows),'issues':issues[:1000],'truncated':len(lines)>500 or len(issues)>1000,'lines':len(lines),'policy':'Geometry heuristics only; gaps are not proof of omitted writing, and tiny regions can be legitimate.'}

    def layout_edit_lines(self,a):
        rows=self.annotations({'id':a['id']})
        if a.get('expected')!=fingerprint(rows):raise ValueError('Результат змінився. Оновіть список.')
        ids=a.get('regions',[])
        if not isinstance(ids,list) or len(ids)!=len(set(ids)):raise ValueError('Select lines to edit.')
        selected=[r for r in rows if r['id'] in ids]
        if len(selected)!=len(ids) or not selected or any(r['kind']!='line' or r.get('verified') or r.get('record') for r in selected):raise ValueError('Only unverified lines without linked records can be split or merged.')
        if any(r.get('parent') in ids for r in rows):raise ValueError('Спочатку видаліть дочірні ділянки.')
        if len({r.get('parent') for r in selected})!=1:raise ValueError('Lines must have the same parent.')
        selected.sort(key=lambda r:(r.get('reading_order',100000),r['rect'][1],r['rect'][0]));operation=a.get('operation');new=[]
        if operation=='merge' and 2<=len(selected)<=50:
            new=[selected[0]|{'rect':union_rect(selected),'text':'\n'.join(r.get('text','') for r in selected),'label':'Merged lines'}]
        elif operation=='split' and len(selected)==1:
            r=selected[0];x,y,w,h=r['rect'];ratio=a.get('ratio',.5);axis=a.get('axis','y')
            if not isinstance(ratio,(int,float)) or not .05<=ratio<=.95 or axis not in ['x','y']:raise ValueError('Invalid split position.')
            rects=[[x,y,w,h*ratio],[x,y+h*ratio,w,h*(1-ratio)]] if axis=='y' else [[x,y,w*ratio,h],[x+w*ratio,y,w*(1-ratio),h]]
            for rect in rects:validate_rect(rect)
            new=[r|{'rect':rect,'text':'','label':'Split line','note':(r.get('note','')+' Original unsplit reading: '+r.get('text',''))[:20000]} for rect in rects]
        else:raise ValueError('Select one line to split or several lines to merge.')
        saved=[]
        with self.db:
            for row in new:
                ident=uuid.uuid4().hex;data={k:v for k,v in row.items() if k!='id'};data.update(verified=False,suggested=False,edited_from=ids)
                encoded=json.dumps(data,ensure_ascii=False);self.db.execute('INSERT INTO annotations(id,page,data) VALUES (?,?,?)',(ident,a['id'],encoded));self.db.execute('INSERT INTO annotation_history(annotation,before,after) VALUES (?,NULL,?)',(ident,encoded));saved.append(ident)
            for row in selected:
                before=self.db.execute('SELECT data FROM annotations WHERE id=?',(row['id'],)).fetchone()['data'];self.db.execute('INSERT INTO annotation_history(annotation,before,after) VALUES (?,?,NULL)',(row['id'],before));self.db.execute('DELETE FROM annotations WHERE id=?',(row['id'],))
        return {'ids':saved,'old_ids':ids,'history_preserved':True,'verified':False}

    def layout_compare(self,a):
        configs=a.get('models',[])
        if not isinstance(configs,list) or not 1<=len(configs)<=2:raise ValueError('Choose at most two segmentation models.')
        page,region,scope,crop=self.scope(a);source=self.db.execute('SELECT path,sha FROM documents WHERE id=?',(page['doc'],)).fetchone();sha=content_sha(source['path']);snapshot=fingerprint(self.annotations({'id':a['id']}));outputs=[]
        if sha!=source['sha']:raise ValueError('Оригінал джерела змінився. Оновіть бібліотеку.')
        for config in configs:
            if not isinstance(config,dict):raise ValueError('Invalid segmentation model.')
            model=config.get('path','');before=content_sha(model) if model else None
            import time
            started=time.perf_counter()
            try:
                result=self.layout_propose(a|{'segmentation':model,'reuse':False})
                if before!=(content_sha(model) if model else None):raise ValueError('Segmentation model changed during recognition.')
                result.update(source_sha256=sha,crop_sha256=content_sha(crop['path']),scope_annotation=a.get('annotation'),model_sha256=before,model_path=model)
                with self.db:self.db.execute('UPDATE layout_proposals SET data=? WHERE id=?',(json.dumps({k:v for k,v in result.items() if k!='id'},ensure_ascii=False),result['id']))
                outputs.append({'name':str(config.get('name',''))[:200],'proposal':result,'seconds':time.perf_counter()-started})
            except Exception as exc:outputs.append({'name':str(config.get('name',''))[:200],'error':str(exc),'seconds':time.perf_counter()-started})
        if content_sha(source['path'])!=sha or fingerprint(self.annotations({'id':a['id']}))!=snapshot:raise ValueError('Результат змінився. Оновіть список.')
        return {'models':outputs,'source_sha256':sha,'snapshot':snapshot,'verified':False,'automatic_selection':False}

    def book_quality_map(self,a):
        page=self.engine.page(a['id']);group=self.photo_book(page['doc'])
        offset=a.get('offset',0)
        if type(offset) is not int or offset<0:raise ValueError('Invalid page offset.')
        rows=[]
        if group:
            total=self.db.execute('SELECT count(*) FROM book_items WHERE book=?',(group['id'],)).fetchone()[0]
            batch=self.db.execute('SELECT p.id,i.position AS num,p.status,p.text,i.label FROM book_items i LEFT JOIN pages p ON p.id=i.page WHERE i.book=? ORDER BY i.position,i.rowid LIMIT 200 OFFSET ?',(group['id'],offset))
        else:
            total=self.db.execute('SELECT count(*) FROM pages WHERE doc=?',(page['doc'],)).fetchone()[0]
            batch=self.db.execute('SELECT id,num,status,text FROM pages WHERE doc=? ORDER BY num LIMIT 200 OFFSET ?',(page['doc'],offset))
        for p in batch:
            if not p['id']:
                rows.append({'page':None,'number':p['num']+1,'label':p['label'],'state':'missing_page','line_count':0,'verified_lines':0,'issues':0,'coverage_complete':False});continue
            annotations=self.annotations({'id':p['id']});lines=[r for r in annotations if r['kind']=='line'];quality=self.layout_quality({'id':p['id']});readable=bool(p['text'].strip()) or any(r.get('text','').strip() for r in lines)
            reviewed=sum(bool(r.get('verified')) for r in lines);state='unprocessed' if not readable else 'machine_read'
            page_job=None
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='page_review_jobs'").fetchone():
                latest=self.db.execute('SELECT id,data FROM page_review_jobs WHERE page=? ORDER BY rowid DESC LIMIT 1',(p['id'],)).fetchone()
                if latest:
                    job=json.loads(latest['data'])
                    if job.get('binding',{}).get('annotations')==quality['snapshot']:
                        states=[u['state'] for u in job['units']];page_job={'id':latest['id'],'done':sum(v in ['done','empty'] for v in states),'total':len(states),'failed':states.count('failed')}
                        if any(v in ['pending','running'] for v in states):state='page_processing'
                        elif 'failed' in states:state='recognition_failed'
                        elif 'done' in states:state='machine_read'
                        else:state='empty_result'

            if reviewed:state='partly_verified' if reviewed<len(lines) else 'saved_lines_verified'
            if quality['issues']:state='layout_review'
            rows.append({'page':p['id'],'number':p['num']+1,'state':state,'line_count':len(lines),'verified_lines':reviewed,'issues':len(quality['issues']),'page_job':page_job,'coverage_complete':False})
        return {'pages':rows,'total':total,'offset':offset,'next_offset':offset+len(rows) if offset+len(rows)<total else None,'policy':'Saved-line verification is not proof of full-page coverage. Geometry warnings require review.'}
