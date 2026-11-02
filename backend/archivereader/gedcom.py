"""Reviewable UTF-8 GEDCOM subset import/export; preserve raw imports and report losses."""
import hashlib
import mimetypes
import shutil
import json
from pathlib import Path
import re
import uuid
import os
import tempfile
import zipfile
try:
    from .research import ResearchTools,date_bounds
    from .gedzip import input_bytes,safe_name,stage_media
except ImportError:
    from research import ResearchTools,date_bounds
    from gedzip import input_bytes,safe_name,stage_media


def parse(raw):
    text=raw.decode('utf-8-sig');roots=[];stack=[];ids=set()
    for number,line in enumerate(text.splitlines(),1):
        if not line.strip():continue
        match=re.fullmatch(r'(\d+) (?:(@[^@\s]+@) )?([A-Z0-9_]+)(?: (.*))?',line)
        if not match:raise ValueError('Неправильний рядок GEDCOM: '+str(number))
        level=int(match[1]);node={'tag':match[3],'xref':match[2],'value':match[4] or '', 'children':[],'line':number}
        if level>len(stack) or level>30:raise ValueError('Неправильна вкладеність GEDCOM.')
        if node['xref']:
            if node['xref'] in ids:raise ValueError('Повторний ідентифікатор GEDCOM.')
            ids.add(node['xref'])
        stack=stack[:level]
        if level:stack[-1]['children'].append(node)
        else:roots.append(node)
        stack.append(node)
    if not roots or roots[0]['tag']!='HEAD' or roots[-1]['tag']!='TRLR':raise ValueError('GEDCOM має містити HEAD і TRLR.')
    if sum(r['tag']=='HEAD' for r in roots)!=1 or sum(r['tag']=='TRLR' for r in roots)!=1:raise ValueError('GEDCOM має містити HEAD і TRLR.')
    if any(r['tag'] in ['INDI','FAM','SOUR'] and not r['xref'] for r in roots):raise ValueError('Запис GEDCOM не має ідентифікатора.')
    return roots


def children(node,tag):return [c for c in node['children'] if c['tag']==tag]
def value(node,tag):return text_value(children(node,tag)[0]) if children(node,tag) else ''
def text_value(node):
    text=node['value'].replace('@@','@')
    for child in node['children']:
        if child['tag']=='CONT':text+='\n'+text_value(child)
        elif child['tag']=='CONC':text+=text_value(child)
    return text


class GedcomTools(ResearchTools):
    def __init__(self,engine):
        super().__init__(engine)
        self.db.executescript('CREATE TABLE IF NOT EXISTS gedcom_imports(id TEXT PRIMARY KEY,sha TEXT UNIQUE,raw BLOB,report TEXT);')

    def preview(self,path):
        path=Path(path)
        raw,input_sha,package_files=input_bytes(path)
        try:roots=parse(raw)
        except UnicodeDecodeError as ex:raise ValueError('Підтримується GEDCOM у кодуванні UTF-8.') from ex
        declared=value(roots[0],'CHAR')
        if declared and declared.upper() not in ['UTF-8','UTF8']:raise ValueError('Підтримується GEDCOM у кодуванні UTF-8.')
        sources={r['xref']:value(r,'TITL') for r in roots if r['tag']=='SOUR'};people=[];families=[];unsupported=[]
        def citations(node):return [sources.get(c['value'],text_value(c))+' '+value(c,'PAGE') for c in children(node,'SOUR')]
        allowed={'HEAD','TRLR','INDI','FAM','SOUR','NAME','SEX','NOTE','CONT','CONC','BIRT','DEAT','MARR','EVEN','TYPE','DATE','PHRASE','PLAC','PAGE','TITL','HUSB','WIFE','CHIL','FAMC','FAMS','GEDC','VERS'}
        def audit(nodes):
            for node in nodes:
                if node['tag'] not in allowed:unsupported.append({'line':node['line'],'tag':node['tag'],'value':node['value']})
                audit(node['children'])
        audit(roots)
        for root in roots:
            if root['tag']=='INDI':
                events=[]
                for event in root['children']:
                    if event['tag'] not in ['BIRT','DEAT','MARR','EVEN']:continue
                    events.append({'tag':event['tag'],'date':value(event,'DATE'),'place':value(event,'PLAC'),'note':'\n'.join(text_value(n) for n in children(event,'NOTE')),'citation':'; '.join(citations(event)),
                                   'phrase':value(children(event,'DATE')[0],'PHRASE') if children(event,'DATE') else '', 'verified':False})
                people.append({'xref':root['xref'],'name':value(root,'NAME').replace('/','').strip() or root['xref'],'aliases':[text_value(n).replace('/','').strip() for n in children(root,'NAME')[1:]],
                               'notes':'\n'.join(text_value(n) for n in children(root,'NOTE')),'sex':value(root,'SEX'),'events':events})
            elif root['tag']=='FAM':
                for node in root['children']:
                    if node['tag'] not in ['HUSB','WIFE','CHIL','NOTE','SOUR']:
                        unsupported.append({'line':node['line'],'tag':node['tag'],'value':node['value'],'reason':'family_structure_preserved_raw_only'})
                families.append({'xref':root['xref'],'parents':[c['value'] for c in root['children'] if c['tag'] in ['HUSB','WIFE']],
                                 'children':[c['value'] for c in children(root,'CHIL')],'note':value(root,'NOTE'),'citation':'; '.join(citations(root))})
        known={p['xref'] for p in people}
        unresolved=[{'family':f['xref'],'reference':ref} for f in families for ref in f['parents']+f['children'] if ref not in known]
        media=[]
        if package_files is not None:
            by_ref={r['xref']:r for r in roots if r['xref']};found={}
            def media_paths(node,seen=None,source=None):
                seen=set() if seen is None else seen
                if len(seen)>128:raise ValueError('Занадто глибокий ланцюг джерел GEDZIP.')
                source=node if node['tag']=='SOUR' and node['xref'] else source
                paths=[]
                if node['tag']=='FILE':
                    name=safe_name(node['value'])
                    if name not in package_files:raise ValueError('У GEDZIP відсутній документ: '+name)
                    found.setdefault(name,{'path':name,'title':value(node,'TITL') or Path(name).name,
                        'citation':value(source,'TITL') if source else '', 'text':value(source,'TEXT') if source else '',
                        'bytes':package_files[name]})
                    if source:
                        for field,tag in [('citation','TITL'),('text','TEXT')]:
                            content=value(source,tag)
                            if content and content not in found[name][field]:found[name][field]+=('\n\n' if found[name][field] else '')+content
                    paths.append(name)
                if node['tag'] in ['OBJE','SOUR'] and node['value'] in by_ref and node['value'] not in seen:
                    paths+=media_paths(by_ref[node['value']],seen|{node['value']},source)
                for child in node['children']:paths+=media_paths(child,seen,source)
                return list(dict.fromkeys(paths))
            for root in roots:media_paths(root)
            for person in people:person['media_refs']=media_paths(by_ref[person['xref']])
            for family in families:family['media_refs']=media_paths(by_ref[family['xref']])
            media=list(found.values())
            unsupported=[x for x in unsupported if x['tag'] not in ['OBJE','FILE','FORM','TEXT']]
        return {'sha':input_sha,'people':people,'families':families,'unsupported':unsupported,'unresolved':unresolved,
                'package':package_files is not None,'media':media,
                'policy':'GEDZIP restores embedded referenced documents; plain GEDCOM does not fetch media. Imported claims retain their source notes without automatic confirmation.'},raw

    def gedcom_preview(self,a):return self.preview(a['path'])[0]

    def gedcom_import(self,a):
        report,raw=self.preview(a['path'])
        if a.get('sha')!=report['sha']:raise ValueError('GEDCOM змінився після перегляду.')
        old=self.db.execute('SELECT id FROM gedcom_imports WHERE sha=?',(report['sha'],)).fetchone()
        if old:raise ValueError('Цей GEDCOM уже імпортовано.')
        ident=uuid.uuid4().hex;mapping={p['xref']:uuid.uuid4().hex for p in report['people']}
        temporary=tempfile.TemporaryDirectory(dir=self.engine.root);created_files=[];media_pages={};media_records={}
        try:
            staged=stage_media(a['path'],report['media'],temporary.name) if report['package'] else []
            # The preview fingerprint covers the entire package, including photographs.
            if report['package'] and input_bytes(a['path'])[1]!=report['sha']:raise ValueError('GEDZIP змінився після перегляду.')
            with self.db:
                for item in staged:
                    existing=self.db.execute('SELECT id,path FROM documents WHERE sha=?',(item['sha'],)).fetchone()
                    if existing:
                        doc=existing['id']
                        if not Path(existing['path']).is_file() or hashlib.sha256(Path(existing['path']).read_bytes()).hexdigest()!=item['sha']:
                            raise ValueError('Збережений оригінал пошкоджений; відновіть його перед імпортом GEDZIP.')
                    else:
                        doc=uuid.uuid4().hex;target=self.engine.root/'originals'/(item['sha']+item['suffix'])
                        if target.exists():
                            if hashlib.sha256(target.read_bytes()).hexdigest()!=item['sha']:raise ValueError('Файл оригіналу змінився.')
                        else:
                            shutil.copyfile(item['staged'],target);created_files.append(target)
                        self.db.execute('INSERT INTO documents VALUES (?,?,?,?)',(doc,item['title'],str(target),item['sha']))
                        self.db.executemany('INSERT INTO pages(id,doc,num) VALUES (?,?,?)',[(uuid.uuid4().hex,doc,n) for n in range(item['count'])])
                        self.db.execute('INSERT INTO book_sources VALUES (?,?)',(doc,json.dumps({'title':item['citation'] or item['title'],'notes':'Імпортовано з GEDZIP. '+item['path']},ensure_ascii=False)))
                    page=self.db.execute('SELECT id FROM pages WHERE doc=? ORDER BY num LIMIT 1',(doc,)).fetchone()['id']
                    media_pages[item['path']]=page
                    rec=uuid.uuid4().hex;media_records[item['path']]=rec
                    self.db.execute('INSERT INTO records VALUES (?,?,?)',(rec,page,json.dumps({'kind':'Інші записи та примітки','person':'','text':item['text'],'notes':item['citation'],'verified':False},ensure_ascii=False)))
                self._import_gedcom_rows(a,report,raw,ident,mapping,media_pages,media_records)
        except Exception:
            for target in created_files:target.unlink(missing_ok=True)
            raise
        finally:temporary.cleanup()
        return {'id':ident,'people':len(mapping),'media_files':len(media_pages),'unsupported':report['unsupported'],'unresolved':report['unresolved']}

    def _import_gedcom_rows(self,a,report,raw,ident,mapping,media_pages,media_records):
        """Insert the complete genealogy inside the caller's database transaction."""
        for person in report['people']:
            data={k:v for k,v in person.items() if k!='xref'};data['import_id']=ident;data['unverified_import']=True
            data['media_pages']=list(dict.fromkeys(media_pages[p] for p in person.get('media_refs',[])))
            if person['xref']==next(iter(mapping)):data['collection_pages']=list(dict.fromkeys(media_pages.values()))
            data['events']=[event|{'import_id':ident,'person_xref':person['xref'],'source_file':Path(a['path']).name} for event in data['events']]
            self.db.execute('INSERT INTO persons VALUES (?,?)',(mapping[person['xref']],json.dumps(data,ensure_ascii=False)))
            for name in person.get('media_refs',[]):
                item=next(x for x in report['media'] if x['path']==name);rec=uuid.uuid4().hex
                evidence={'kind':'Інші записи та примітки','person':person['name'],'text':item['text'],'notes':item['citation'],'verified':False}
                self.db.execute('INSERT INTO records VALUES (?,?,?)',(rec,media_pages[name],json.dumps(evidence,ensure_ascii=False)))
                mention=self.enrich(self.mentions(records=[rec])[0])
                self.db.execute('INSERT INTO person_members VALUES (?,?,?)',(self.key(mention),mapping[person['xref']],json.dumps({'mention':mention,'note':'Фото прикріплене у вихідному GEDZIP; факт імпорту не підтверджує тотожність особи.'},ensure_ascii=False)))
        for family in report['families']:
            parents=[mapping[x] for x in family['parents'] if x in mapping];kids=[mapping[x] for x in family['children'] if x in mapping]
            pairs=[(parents[0],parents[1],'spouse')] if len(parents)==2 and parents[0]!=parents[1] else []
            pairs += [(parent,child,'parent') for parent in parents for child in kids if parent!=child]
            for left,right,kind in pairs:
                data={'left':left,'right':right,'kind':kind,'status':'imported','record':None,'signature':None,'evidence':{},'page':None,'note':family['note'],
                      'citation':family['citation'] or Path(a['path']).name+' '+str(family['xref']),'import_id':ident,
                      'documents':[{'page':media_pages[p],'record':media_records[p],'title':next(x['title'] for x in report['media'] if x['path']==p),'citation':next(x['citation'] for x in report['media'] if x['path']==p),'text':next(x['text'] for x in report['media'] if x['path']==p)} for p in family.get('media_refs',[])]}
                self.db.execute('INSERT INTO family_links VALUES (?,?)',(uuid.uuid4().hex,json.dumps(data,ensure_ascii=False)))
        self.db.execute('INSERT INTO gedcom_imports VALUES (?,?,?,?)',(ident,report['sha'],raw,json.dumps(report,ensure_ascii=False)))

    def gedcom_export(self,a):
        if Path(a['path']).suffix.lower()=='.gdz':
            destination=Path(a['path']).resolve();destination.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
                folder=Path(temporary);ged=folder/'gedcom.ged'
                result=self.gedcom_export(a|{'path':str(ged),'include_media':True})
                package=folder/'package.gdz'
                with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as archive:
                    archive.write(ged,'gedcom.ged')
                    for photo in sorted((folder/'gedcom.media').glob('*')):archive.write(photo,photo.relative_to(folder).as_posix())
                os.replace(package,destination)
            result['path']=str(destination);result['format']='GEDZIP';result['includes_media']=True
            destination.with_suffix('.gdz.report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
            return result
        destination=Path(a['path']).resolve();destination.parent.mkdir(parents=True,exist_ok=True);media={};include_imported=a.get('include_imported') is True
        people=self.person_list({});ids={p['id']:'@I'+str(i+1)+'@' for i,p in enumerate(people)};lines=['0 HEAD','1 SOUR ArchiveReader','1 GEDC','2 VERS 7.0'];warnings=[];sources={};source_pages={};links=[]
        def put(level,tag,text=''):
            parts=str(text).replace('\r','').replace('@','@@').split('\n');lines.append(f'{level} {tag}'+(' '+parts[0] if parts[0] else ''))
            for part in parts[1:]:lines.append(f'{level+1} CONT '+part)
        def attach_media(level,page):
            if not a.get('include_media') or not page:return
            source=Path(self.engine.page(page)['path'])
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            if digest not in media:
                folder=destination.parent/(destination.stem+'.media');folder.mkdir(exist_ok=True)
                target=folder/(digest+source.suffix.lower())
                if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise ValueError('Existing media file has changed.')
                if not target.exists():shutil.copyfile(source,target)
                media[digest]={'ref':'@M'+str(len(media)+1)+'@','path':target.relative_to(destination.parent).as_posix(),'mime':mimetypes.guess_type(source.name)[0] or 'application/octet-stream','title':self.engine.page(page)['name']}
            lines.append(f"{level} OBJE {media[digest]['ref']}")
        def cite(level,text,page=None):
            if not text:return
            if text not in sources:sources[text]='@S'+str(len(sources)+1)+'@'
            if page:source_pages[text]=page
            lines.append(f'{level} SOUR {sources[text]}')
        def event(level,tag,data,family_event=False):
            marriage=tag=='MARR' and not family_event
            if marriage:tag='EVEN'
            if tag not in ['BIRT','DEAT','MARR','EVEN']:tag='EVEN'
            if tag=='EVEN':
                label='Marriage mention' if marriage else data.get('type') or 'Document mention'
                put(level,'EVEN',label);put(level+1,'TYPE',label)
            else:lines.append(f'{level} {tag}')
            raw_date=data.get('date','');bounds=date_bounds(raw_date) if data.get('calendar','gregorian')=='gregorian' or raw_date.strip().upper().startswith('GREGORIAN ') else None
            if bounds:
                if re.fullmatch(r'\d{4}',raw_date.strip()) or raw_date.upper().startswith('BET '):put(level+1,'DATE',raw_date.upper())
                elif bounds[0]==bounds[1]:put(level+1,'DATE',f'{bounds[0].day} '+['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'][bounds[0].month-1]+f' {bounds[0].year}')
            elif raw_date:
                put(level+1,'NOTE','Original date: '+raw_date);warnings.append({'kind':'unparsed_date_preserved_as_note','value':raw_date})
            if data.get('place'):put(level+1,'PLAC',data['place'])
            if data.get('note'):put(level+1,'NOTE',data['note'])
            cite(level+1,data.get('citation','') or (data.get('source_file','')+' '+str(data.get('person_xref','')) if data.get('import_id') else ''),data.get('page'))
        families=[f for f in self.family_list({}) if (f['status']=='confirmed' and not f['stale'] or include_imported and f['status']=='imported' and (not f['stale'] or not f.get('record'))) and f['left'] in ids and f['right'] in ids]
        for family in families:
            if family['status']=='imported':warnings.append({'kind':'unverified_imported_relationship_included','id':family['id']})
        parent_claims={(f['left'],f['right']):f for f in families if f['kind']=='parent'}
        used=set();groups=[]
        for spouse in (f for f in families if f['kind']=='spouse'):
            left,right=spouse['left'],spouse['right']
            children=sorted(child for parent,child in parent_claims if parent==left and (right,child) in parent_claims)
            claims=[spouse]+[parent_claims[parent,child] for child in children for parent in (left,right)]
            used.update(f['id'] for f in claims)
            groups.append({'parents':[left,right],'children':children,'claims':claims})
        for parent in dict.fromkeys(f['left'] for f in families if f['kind']=='parent' and f['id'] not in used):
            claims=[f for f in families if f['kind']=='parent' and f['left']==parent and f['id'] not in used]
            groups.append({'parents':[parent],'children':[f['right'] for f in claims],'claims':claims})
        # A shared child enters a couple's family only when BOTH parent claims exist.
        # A spouse link alone must never imply parentage of the other person's children.
        links=[('@F'+str(i+1)+'@',group) for i,group in enumerate(groups)]
        for person in people:
            lines.append('0 '+ids[person['id']]+' INDI');put(1,'NAME',person['name'])
            card=self.person_card({'id':person['id']})
            aliases=person.get('aliases',[])+[m['mention']['name'] for m in card['members'] if not m['stale']]
            for alias in dict.fromkeys(aliases):
                if alias!=person['name']:put(1,'NAME',alias)
            if person.get('sex') in ['M','F','X','U']:put(1,'SEX',person['sex'])
            if person.get('notes'):put(1,'NOTE',person['notes'])
            if person.get('source_url'):cite(1,person['source_url']+' node '+person.get('source_node',''))
            for page in person.get('media_pages',[]):attach_media(1,page)
            for data in person.get('events',[]):event(1,data.get('tag','EVEN'),data)
            for member in card['members']:
                mention=member['mention'];record=mention['evidence']
                if member['stale'] or mention['field']!='person':
                    put(1,'NOTE',mention['name']+' — '+mention['citation']);warnings.append({'kind':'stale_or_related_mention_as_note','person':person['id']});continue
                calendar=self.book_profile({'id':mention['page']}).get('calendar','')
                event(1,{'Народження':'BIRT','Смерті':'DEAT','Шлюби':'MARR'}.get(record['kind'],'EVEN'),{'date':record.get('date',''),'place':record.get('place',''),'note':record.get('text',''),'citation':mention['citation'],'calendar':calendar,'page':mention['page']})
                attach_media(2,mention['page'])
            for ref,group in links:
                if person['id'] in group['children']:lines.append('1 FAMC '+ref)
                if person['id'] in group['parents']:lines.append('1 FAMS '+ref)
        for ref,group in links:
            lines.append('0 '+ref+' FAM')
            for role,parent in zip(['HUSB','WIFE'],group['parents']):lines.append('1 '+role+' '+ids[parent])
            for child in group['children']:lines.append('1 CHIL '+ids[child])
            put(1,'NOTE','Role placement does not assert sex. Only explicitly selected relationship claims are exported.')
            for family in group['claims']:
                if family['status']=='imported':put(1,'NOTE','Imported research assertion; not independently verified. Inclusion was explicitly requested.')
                put(1,'NOTE',family['note']);cite(1,family['citation'])
                for item in family.get('events',[]):
                    event(1,item.get('tag','EVEN'),item,family_event=True);attach_media(2,item.get('page'))
                for document in family.get('documents',[]):
                    cite(1,document.get('citation',''),document.get('page'));attach_media(1,document.get('page'))
        for page in dict.fromkeys(list(a.get('extra_media_pages',[]))+[page for person in people for page in person.get('collection_pages',[])]):
            # Documents may belong to the research collection without an identity link.
            title=self.source_card({'id':page})['citation']
            if title not in sources:sources[title]='@S'+str(len(sources)+1)+'@'
            source_pages[title]=page
        for title,ref in sources.items():
            lines.append('0 '+ref+' SOUR');put(1,'TITL',title)
            page=source_pages.get(title)
            if page:
                records=[json.loads(row['data']) for row in self.db.execute('SELECT data FROM records WHERE page=? ORDER BY id',(page,))]
                texts=[r.get('text','') for r in records if r.get('text')]
                if texts:put(1,'TEXT','\n\n'.join(texts))
                for record in records:
                    if record.get('notes'):put(1,'NOTE',record['notes'])
                card=self.source_card({'id':page})
                for note in [card['book'].get('notes'),card['page_values'].get('page_notes')]:
                    if note:put(1,'NOTE',note)
                attach_media(1,page)
        for item in media.values():
            lines.append('0 '+item['ref']+' OBJE');put(1,'FILE',item['path']);put(2,'FORM',item['mime']);put(2,'TITL',item['title'])
        lines.append('0 TRLR');path=Path(a['path']);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('\n'.join(lines)+'\n',encoding='utf8')
        omitted=[{'kind':'unconfirmed_or_stale_relationship','id':f['id']} for f in self.family_list({}) if f not in families]
        result={'path':str(path),'people':len(people),'media_files':len(media),'relationships':len(families),'family_groups':len(groups),'warnings':warnings+omitted,'scope':'GEDCOM 7.0: names, notes, events, citations and explicit family groups. Imported claims and adjacent media files require explicit options. Full audit history is not embedded.'}
        path.with_suffix(path.suffix+'.report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');return result
