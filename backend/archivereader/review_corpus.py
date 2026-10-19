"""Frozen whole-entry evaluation with independent, human-confirmed references.

Entry drafts and model consensus are never training labels. One shared extraction
and reading order is used for every recognizer in a comparison.
"""
from pathlib import Path
import contextlib
import hashlib
import json
import sys
import time
import uuid

try:
    from .library import LibraryTools, digest
    from .workbench import overlaps
    from .engine import uncertain_text
    from .htr_compare import compare, score, normalize
except ImportError:
    from library import LibraryTools, digest
    from workbench import overlaps
    from engine import uncertain_text
    from htr_compare import compare, score, normalize

REASONS={'draft':'Спочатку підтвердьте власне прочитання.',
         'damaged':'Пошкоджений запис збережіть як чернетку.',
         'uncertain_text':'Непевний або порожній текст збережіть як чернетку.',
         'reading_order_required':'Підтвердьте один блок читання або задайте порядок дочірніх рядків.',
         'source_changed':'Розмітка змінилася. Імпортуйте запис повторно як чернетку.',
         'source_or_split_changed':'Джерело або роль книги змінилися. Перевірте незалежність тестового набору.'}


FIELD_NAMES={'person','date','house','place','related1','related2','age'}

def checked_fields(value):
    if not isinstance(value,dict) or not set(value)<=FIELD_NAMES:raise ValueError('Неправильні поля еталона.')
    if any(not isinstance(v,str) or len(v)>2000 for v in value.values()):raise ValueError('Значення поля надто довге.')
    return value.copy()

def weight_identity(path):
    """Content identity without loading a network or retaining weight bytes.

    Names and tokenizer/settings files do not make copied weights independent.
    Shards contribute their sorted content hashes, independent of filenames.
    """
    path=Path(path).resolve()
    files=[path] if path.is_file() else sorted(f for f in path.iterdir() if f.is_file() and f.suffix.lower() in {'.safetensors','.bin','.mlmodel'}) if path.is_dir() else []
    if not files:raise ValueError('Виберіть локальну модель.')
    identities=[]
    for file in files:
        with file.open('rb') as source:identities.append(hashlib.file_digest(source,'sha256').hexdigest())
    return hashlib.sha256(json.dumps(sorted(set(identities))).encode('ascii')).hexdigest()


def segment_entry(image_path, segmentation=None):
    """One shared proposed reading order, restricted to a confirmed single block."""
    from PIL import Image
    from kraken import blla
    from kraken.lib.vgsl import TorchVGSLModel
    image=Image.open(image_path).convert('RGB')
    model=TorchVGSLModel.load_model(segmentation) if segmentation else None
    bounds=blla.segment(image,model=model,device='cpu')
    rects=[]
    for line in bounds.lines:
        polygon=line.boundary
        if not polygon:continue
        x=max(0,int(min(p[0] for p in polygon)));y=max(0,int(min(p[1] for p in polygon)))
        right=min(image.width,int(max(p[0] for p in polygon))+1);bottom=min(image.height,int(max(p[1] for p in polygon))+1)
        if right>x and bottom>y:rects.append([x/image.width,y/image.height,(right-x)/image.width,(bottom-y)/image.height])
    if not rects:raise ValueError('Рядків не знайдено. Позначте рядки запису вручну.')
    return sorted(rects,key=lambda r:(r[1],r[0]))


def model_suitability(entries,names):
    """Rank only paired successful verified entries in this exact frozen test scope."""
    groups={}
    for entry in entries:groups.setdefault(entry['document'],[]).append(entry)
    books=[]
    for document,rows in groups.items():
        common=[r for r in rows if all(r['results'].get(n,{}).get('score',{}).get('characters',0)>0 for n in names)]
        models=[]
        for name in names:
            scores=[r['results'][name]['score'] for r in common];chars=sum(r['characters'] for r in scores)
            models.append({'name':name,'common_cer':sum(r['character_errors'] for r in scores)/chars if chars else None,'failed_entries':sum('score' not in r['results'].get(name,{}) for r in rows)})
        ranked=sorted((r for r in models if r['common_cer'] is not None),key=lambda r:r['common_cer'])
        # A tie or no paired data never declares a winner; failures stay visible.
        best=ranked[0]['name'] if len(ranked)>1 and ranked[0]['common_cer']<ranked[1]['common_cer'] and not ranked[0]['failed_entries'] else None
        books.append({'document':document,'name':rows[0].get('book_name',document),'verified_entries':len(rows),'common_entries':len(common),'models':models,'lowest_observed_cer_model':best,'small_sample':len(common)<20,'automatic_activation':False})
    return {'books':books,'scope':'Only these frozen human-verified entries; not language identification or general suitability. Small samples and shared failures limit conclusions.','automatic_activation':False}


class CorpusTools(LibraryTools):
    def __init__(self,engine):
        super().__init__(engine)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS entry_references(id TEXT PRIMARY KEY,
          page TEXT NOT NULL REFERENCES pages(id),annotation TEXT NOT NULL UNIQUE,data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS entry_reference_history(id INTEGER PRIMARY KEY,
          reference TEXT NOT NULL,before TEXT,after TEXT NOT NULL,created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS entry_corpus_runs(id TEXT PRIMARY KEY,path TEXT NOT NULL,
          data TEXT NOT NULL,created TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')

    def _entry(self,page_id,annotation):
        page=self.engine.page(page_id)
        region=next((r for r in self.annotations({'id':page_id}) if r['id']==annotation and r['kind']=='entry'),None)
        if not region:raise ValueError('Збережений запис не знайдено. Створіть розмітку запису.')
        children=[r for r in self.annotations({'id':page_id}) if r.get('parent')==annotation and r['kind']=='line']
        original=self.db.execute('SELECT path,sha FROM documents WHERE id=?',(page['doc'],)).fetchone()
        try:
            with Path(original['path']).open('rb') as stream:source=hashlib.file_digest(stream,'sha256').hexdigest()
        except OSError as exc:raise ValueError('Оригінал джерела недоступний.') from exc
        if source!=original['sha']:raise ValueError('Оригінал джерела змінився.')
        return page,region,children,digest({'source':source,'region':region,'children':children})

    def _family_test(self,doc,assign=False):
        family=self.document_family(doc)
        for member in family:
            row=self.db.execute('SELECT data FROM book_profiles WHERE doc=?',(member,)).fetchone()
            split=json.loads(row['data']).get('split','') if row else ''
            if split in ['train','validation']:raise ValueError('Родина джерела вже використовується для навчання або перевірки. Виберіть незалежну тестову книгу.')
            if not assign and split!='test':raise ValueError('Уся родина джерела має залишатися тестовою.')
        if assign is True:
            for member in family:
                page=self.db.execute('SELECT id FROM pages WHERE doc=? ORDER BY num LIMIT 1',(member,)).fetchone()
                if page:
                    values=self.book_profile({'id':page['id']});values['split']='test'
                    self.book_profile({'id':page['id'],'values':values})

    def corpus_import(self,a):
        if a.get('id'):self.engine.page(a['id'])
        candidates=self.db.execute("SELECT id,page,data FROM annotations WHERE json_extract(data,'$.kind')='entry'"+(' AND page=?' if a.get('id') else ''), (a['id'],) if a.get('id') else ()).fetchall()
        prepared=[]
        for row in candidates:
            page,region,children,binding=self._entry(row['page'],row['id']);self._family_test(page['doc'],assign='check')
            prepared.append((page,region,binding))
        for page,_,_ in prepared:self._family_test(page['doc'],assign=True)
        added=unchanged=0
        for page,region,binding in prepared:
            old=self.db.execute('SELECT * FROM entry_references WHERE annotation=?',(region['id'],)).fetchone()
            previous=json.loads(old['data']) if old else None
            if previous and previous['binding']==binding:unchanged+=1;continue
            ident=old['id'] if old else uuid.uuid4().hex
            data={'text':previous['text'] if previous else region.get('text',''),'human_verified':False,
                  'single_block':False,'binding':binding,'revision':uuid.uuid4().hex,'origin':'imported_draft','notes':previous.get('notes','') if previous else ''}
            data.update(fields=previous.get('fields',{}) if previous else {},fields_verified=False)
            self._write(ident,page['id'],region['id'],previous,data);added+=1
        return {'added':added,'unchanged':unchanged,'reference_policy':'Drafts only. Human confirmation required.'}

    def _write(self,ident,page,annotation,before,after):
        with self.db:
            self.db.execute('INSERT INTO entry_references VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(ident,page,annotation,json.dumps(after,ensure_ascii=False)))
            self.db.execute('INSERT INTO entry_reference_history(reference,before,after) VALUES (?,?,?)',(ident,json.dumps(before,ensure_ascii=False) if before else None,json.dumps(after,ensure_ascii=False)))

    def _eligibility(self,row,data):
        try:
            page,region,children,binding=self._entry(row['page'],row['annotation'])
            if binding!=data['binding']:return 'source_changed'
            self._family_test(page['doc'])
            if not data.get('human_verified'):return 'draft'
            if not data.get('text','').strip() or uncertain_text(data['text']):return 'uncertain_text'
            if any(r['kind'] in ['damage','missing'] and overlaps(region['rect'],r['rect']) for r in self.annotations({'id':page['id']})):return 'damaged'
            orders=[r.get('reading_order') for r in children]
            manual=bool(children) and all(type(n) is int and n>0 for n in orders) and len(set(orders))==len(orders)
            if not manual and not data.get('single_block'):return 'reading_order_required'
            return None
        except ValueError:return 'source_or_split_changed'

    def corpus_list(self,a):
        result=[]
        for row in self.db.execute('SELECT r.*,p.num,d.name FROM entry_references r JOIN pages p ON p.id=r.page JOIN documents d ON d.id=p.doc ORDER BY r.rowid DESC'):
            if a.get('id') and row['page']!=a['id']:continue
            data=json.loads(row['data']);reason=self._eligibility(row,data)
            result.append(data|{'id':row['id'],'page':row['page'],'annotation':row['annotation'],'number':row['num']+1,'name':row['name'],'excluded':reason,'eligible':reason is None})
        return result

    def corpus_save(self,a):
        row=self.db.execute('SELECT * FROM entry_references WHERE id=?',(a['reference'],)).fetchone()
        if not row:raise ValueError('Еталон запису не знайдено.')
        previous=json.loads(row['data'])
        if a.get('revision')!=previous['revision']:raise ValueError('Еталон змінився. Оновіть список.')
        page,region,children,binding=self._entry(row['page'],row['annotation'])
        if binding!=previous['binding']:raise ValueError('Розмітка змінилася. Імпортуйте запис повторно як чернетку.')
        data=previous|{'text':str(a.get('text','')).strip(),'notes':str(a.get('notes','')),
                       'human_verified':a.get('human_verified') is True,'single_block':a.get('single_block') is True,
                       'revision':uuid.uuid4().hex,'origin':'human_edit'}
        data['fields_verified']=False
        if 'fields' in a or 'fields_verified' in a:
            data['fields']=checked_fields(a.get('fields',previous.get('fields',{})))
            data['fields_verified']=a.get('fields_verified') is True
            if data['fields_verified'] and (not any(v.strip() for v in data['fields'].values()) or not data['human_verified'] or any(uncertain_text(v) for v in data['fields'].values() if v.strip())):
                raise ValueError('Підтвердьте власні певні значення полів разом із повним еталоном.')
        if data['human_verified']:
            reason=self._eligibility(row,data)
            if reason:raise ValueError(REASONS[reason])
        self._write(row['id'],row['page'],row['annotation'],previous,data)
        return data|{'id':row['id']}

    def corpus_history(self,a):
        return [dict(r)|{'before':json.loads(r['before']) if r['before'] else None,'after':json.loads(r['after'])} for r in self.db.execute('SELECT * FROM entry_reference_history WHERE reference=? ORDER BY id DESC',(a['reference'],))]

    def corpus_freeze(self,a):
        rows=self.corpus_list(a);eligible=[r for r in rows if r['eligible']]
        if not eligible:raise ValueError('Спочатку звірте повні записи з оригіналом і підтвердьте еталони.')
        folder=self.engine.root/'results'/('entry-corpus-'+uuid.uuid4().hex);folder.mkdir()
        manifest=[]
        for row in eligible:
            page,region,children,binding=self._entry(row['page'],row['annotation'])
            source=Path(self.region_crop({'id':page['id'],'annotation':row['annotation']})['path'])
            image=folder/(row['id']+'.png');image.write_bytes(source.read_bytes())
            x,y,w,h=region['rect'];manual=bool(children) and all(type(r.get('reading_order')) is int for r in children) and len({r['reading_order'] for r in children})==len(children)
            regions=[[(r['rect'][0]-x)/w,(r['rect'][1]-y)/h,r['rect'][2]/w,r['rect'][3]/h] for r in sorted(children,key=lambda r:r['reading_order'])] if manual else None
            manifest.append({'id':row['id'],'image':image.name,'image_sha256':hashlib.sha256(image.read_bytes()).hexdigest(),'text':row['text'],'human_verified':True,'revision':row['revision'],'binding':binding,'document':page['doc'],'source_sha256':self.db.execute('SELECT sha FROM documents WHERE id=?',(page['doc'],)).fetchone()['sha'],'page':page['num']+1,'split':'test','rect':region['rect'],'reading_regions':regions,'reading_policy':'manual' if regions else 'confirmed_single_block_auto_segmentation','book':page['doc'],'book_name':page['name']})
            if row.get('fields_verified') is True:manifest[-1].update(fields=checked_fields(row['fields']),fields_verified=True)
        target=folder/'manifest.json';target.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');sha=hashlib.sha256(target.read_bytes()).hexdigest()
        freeze={'manifest_sha256':sha,'scope':'Whole-entry end-to-end evaluation; segmentation/reading order are included.','policy':'Human-confirmed independent test entries only. No automatic references.','excluded':[{'id':r['id'],'reason':r['excluded']} for r in rows if not r['eligible']]}
        (folder/'freeze.json').write_text(json.dumps(freeze,ensure_ascii=False,indent=2),encoding='utf-8')
        return {'path':str(folder),'entries':len(manifest),'excluded':len(rows)-len(manifest),'manifest_sha256':sha}

    def corpus_score_fields(self,a):
        """Score explicit unverified predictions against frozen HUMAN field references."""
        source=Path(a['path']).resolve();manifest=source/'manifest.json';frozen=json.loads((source/'freeze.json').read_text('utf8'))
        sha=hashlib.sha256(manifest.read_bytes()).hexdigest()
        if sha!=frozen['manifest_sha256'] or a.get('expected_manifest_sha256')!=sha:raise ValueError('Збережений набір змінено. Оновіть знімок.')
        cases=json.loads(manifest.read_text('utf8'));eligible={}
        for row in cases:
            if row.get('human_verified') is not True or row.get('split')!='test':raise ValueError('Набір містить непідтверджені еталони.')
            self._family_test(row['document'])
            image=(source/row['image']).resolve()
            if image.parent!=source or hashlib.sha256(image.read_bytes()).hexdigest()!=row['image_sha256']:raise ValueError('Зображення еталона змінено.')
            current=self.db.execute('SELECT r.*,p.doc FROM entry_references r JOIN pages p ON p.id=r.page WHERE r.id=?',(row['id'],)).fetchone()
            if not current or self._entry(current['page'],current['annotation'])[3]!=row['binding']:raise ValueError('Джерело еталона змінилося.')
            if row.get('fields_verified') is True:
                fields=checked_fields(row.get('fields',{}))
                if fields:eligible[row['id']]=fields
        if not eligible:raise ValueError('У знімку немає окремо підтверджених людиною полів.')
        predictions=a.get('predictions')
        if not isinstance(predictions,list) or len(predictions)>10000:raise ValueError('Неправильний список прогнозів полів.')
        lookup={}
        for prediction in predictions:
            if not isinstance(prediction,dict) or prediction.get('id') not in eligible or prediction['id'] in lookup:raise ValueError('Прогноз має невідомий або повторний ідентифікатор.')
            fields=checked_fields(prediction.get('fields',{}));error=prediction.get('error')
            if error is not None and (not isinstance(error,str) or len(error)>4000):raise ValueError('Неправильний опис збою прогнозу.')
            lookup[prediction['id']]={'fields':fields,'error':error}
        model=a.get('model',{})
        if not isinstance(model,dict) or not isinstance(model.get('name'),str) or not model['name'].strip():raise ValueError('Вкажіть походження прогнозів.')
        metrics={};rows=[]
        for ident,fields in eligible.items():
            prediction=lookup.get(ident);results={}
            for field,reference in fields.items():
                metric=metrics.setdefault(field,{'references':0,'exact':0,'scored':0,'missing':0,'failed':0,'character_errors':0,'characters':0})
                metric['references']+=1
                if prediction is None or (not prediction['error'] and field not in prediction['fields']):metric['missing']+=1;results[field]={'status':'missing'};continue
                if prediction['error']:metric['failed']+=1;results[field]={'status':'failed','error':prediction['error']};continue
                value=prediction['fields'][field];scored=score(reference,value);exact=reference==value
                metric['scored']+=1;metric['exact']+=int(exact);metric['character_errors']+=scored['character_errors'];metric['characters']+=scored['characters']
                results[field]={'status':'scored','reference':reference,'prediction':value,'literal_exact':exact,'score':scored}
            rows.append({'id':ident,'fields':results})
        for metric in metrics.values():
            metric['exact_rate_all_references']=metric['exact']/metric['references']
            metric['cer_successful_predictions']=metric['character_errors']/metric['characters'] if metric['characters'] else None
        folder=self.engine.root/'results'/('field-evaluation-'+uuid.uuid4().hex);folder.mkdir()
        result={'path':str(folder),'dataset':str(source),'manifest_sha256':sha,'model':model,'prediction_origin':'caller_provided_unverified_fields','automatic_field_extraction':False,'raw_model_provenance_certified':False,'predictions_sha256':digest(predictions),'metrics':metrics,'rows':rows,'policy':'Caller-provided unverified field predictions scored against explicitly human-confirmed frozen test fields. The caller may have entered predictions manually; no raw model provenance is certified. No automatic semantic field extraction or model agreement used as ground truth. Missing and failed predictions count in exact denominator; CER covers successful predictions only. Literal dates/names/house numbers are not normalized for exact comparison.'}
        (folder/'field-report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        return result

    def corpus_compare(self,a):
        from PIL import Image
        configurations=a.get('models',[])
        if len(configurations)<2 or len({m['name'] for m in configurations})!=len(configurations) or len({str(Path(m['path']).resolve()).casefold() for m in configurations})!=len(configurations):
            raise ValueError('Для порівняння виберіть різні моделі.')
        identities={m['name']:weight_identity(m['path']) for m in configurations}
        if len(set(identities.values()))!=len(configurations):raise ValueError('Для порівняння виберіть різні моделі.')
        source=Path(a['path']).resolve();manifest=source/'manifest.json';frozen=json.loads((source/'freeze.json').read_text('utf-8'))
        if hashlib.sha256(manifest.read_bytes()).hexdigest()!=frozen['manifest_sha256']:raise ValueError('Збережений набір змінено. Створіть новий знімок.')
        cases=json.loads(manifest.read_text('utf-8'))
        if not cases or any(r.get('split')!='test' or r.get('human_verified') is not True for r in cases):raise ValueError('Набір містить непідтверджені еталони.')
        for row in cases:
            self._family_test(row['document'])
            image=(source/row['image']).resolve()
            if image.parent!=source or hashlib.sha256(image.read_bytes()).hexdigest()!=row['image_sha256']:raise ValueError('Збережений набір змінено. Створіть новий знімок.')
        self.check_known_training_overlap([({'doc':r['document'],'source_sha256':r['source_sha256']},r) for r in cases],a['models'])
        run=uuid.uuid4().hex;folder=self.engine.root/'results'/('entry-comparison-'+run);folder.mkdir();lines=[];entry_lines={};errors={};started=time.monotonic()
        for row in cases:
            try:
                rects=row.get('reading_regions') or segment_entry(source/row['image'],a.get('segmentation'))
                image=Image.open(source/row['image']).convert('RGB');entry_lines[row['id']]=[]
                for n,(x,y,w,h) in enumerate(rects):
                    ident=row['id']+'-'+str(n);name=ident+'.png';crop=image.crop((round(x*image.width),round(y*image.height),round((x+w)*image.width),round((y+h)*image.height)));crop.save(folder/name)
                    lines.append({'id':ident,'image':name,'image_sha256':hashlib.sha256((folder/name).read_bytes()).hexdigest(),'source':row['id']});entry_lines[row['id']].append(ident)
            except Exception as exc:errors[row['id']]=str(exc)
        extraction_seconds=time.monotonic()-started;report=None
        if lines:
            target=folder/'lines.json';target.write_text(json.dumps(lines,indent=2),encoding='utf-8')
            with contextlib.redirect_stdout(sys.stderr):report=compare(target,a['models'],folder)
        predicted={r['id']:r for r in report['rows']} if report else {};names=[m['name'] for m in a['models']];entries=[]
        for row in cases:
            results={}
            for name in names:
                parts=[predicted.get(ident,{}).get('results',{}).get(name,{}) for ident in entry_lines.get(row['id'],[])]
                if row['id'] in errors or not parts or any('text' not in r for r in parts):results[name]={'error':errors.get(row['id']) or '; '.join(r.get('error','Missing line output') for r in parts if 'text' not in r)}
                else:
                    text='\n'.join(r['text'] for r in parts);results[name]={'text':text,'score':score(row['text'],text)}
            entries.append(row|{'results':results})
        common=[r for r in entries if all('score' in r['results'][n] for n in names)];summaries=[]
        for name in names:
            scored=[r['results'][name]['score'] for r in entries if 'score' in r['results'][name]];paired=[r['results'][name]['score'] for r in common]
            def rate(rows,key,denominator):
                size=sum(r[denominator] for r in rows);return sum(r[key] for r in rows)/size if size else None
            meta=next((m for m in report['models'] if m['name']==name),{}) if report else {}
            summaries.append({'name':name,'weight_identity':identities[name],'entries':len(entries),'scored_entries':len(scored),'failed_entries':len(entries)-len(scored),'micro_cer':rate(scored,'character_errors','characters'),'micro_wer':rate(scored,'word_errors','words'),'common_cer':rate(paired,'character_errors','characters'),'common_wer':rate(paired,'word_errors','words'),'recognition_seconds':meta.get('seconds_including_model_load'), 'model':meta})
        result={'entries':entries,'models':summaries,'common_entries':len(common),'extraction_seconds':extraction_seconds,'path':str(folder),'dataset':str(source),'manifest_sha256':frozen['manifest_sha256'],'scope':'Whole-entry end-to-end; shared segmentation and reading order. Failed entries are counted, never scored as success.','limitations':['Reading order and segmentation errors affect entry CER/WER.','Single-block automatic order is top-to-bottom; complex tables require manual ordered line regions.','Source family separation does not prove absence from external model pretraining.']}
        result['suitability']=model_suitability(entries,names)
        (folder/'entry-report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        with self.db:self.db.execute('INSERT INTO entry_corpus_runs(id,path,data) VALUES (?,?,?)',(run,str(folder),json.dumps({'dataset':str(source),'manifest_sha256':frozen['manifest_sha256'],'models':summaries},ensure_ascii=False)))
        return result
