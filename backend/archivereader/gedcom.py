"""Reviewable UTF-8 GEDCOM subset import/export; preserve raw imports and report losses."""
import hashlib
import json
from pathlib import Path
import re
import uuid
try:
    from .research import ResearchTools,date_bounds
except ImportError:
    from research import ResearchTools,date_bounds


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
        if path.stat().st_size>20*1024*1024:raise ValueError('GEDCOM перевищує ліміт імпорту 20 МБ.')
        raw=path.read_bytes()
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
        return {'sha':hashlib.sha256(raw).hexdigest(),'people':people,'families':families,'unsupported':unsupported,'unresolved':unresolved,
                'policy':'UTF-8 subset. Imported people/events/relationships remain unverified; media are not fetched. Raw bytes are retained in the database.'},raw

    def gedcom_preview(self,a):return self.preview(a['path'])[0]

    def gedcom_import(self,a):
        report,raw=self.preview(a['path'])
        if a.get('sha')!=report['sha']:raise ValueError('GEDCOM змінився після перегляду.')
        old=self.db.execute('SELECT id FROM gedcom_imports WHERE sha=?',(report['sha'],)).fetchone()
        if old:raise ValueError('Цей GEDCOM уже імпортовано.')
        ident=uuid.uuid4().hex;mapping={p['xref']:uuid.uuid4().hex for p in report['people']}
        with self.db:
            for person in report['people']:
                data={k:v for k,v in person.items() if k!='xref'};data['import_id']=ident;data['unverified_import']=True
                data['events']=[event|{'import_id':ident,'person_xref':person['xref'],'source_file':Path(a['path']).name} for event in data['events']]
                self.db.execute('INSERT INTO persons VALUES (?,?)',(mapping[person['xref']],json.dumps(data,ensure_ascii=False)))
            for family in report['families']:
                parents=[mapping[x] for x in family['parents'] if x in mapping];kids=[mapping[x] for x in family['children'] if x in mapping]
                pairs=[(parents[0],parents[1],'spouse')] if len(parents)==2 and parents[0]!=parents[1] else []
                pairs += [(parent,child,'parent') for parent in parents for child in kids if parent!=child]
                for left,right,kind in pairs:
                    data={'left':left,'right':right,'kind':kind,'status':'imported','record':None,'signature':None,'evidence':{},'page':None,'note':family['note'],
                          'citation':family['citation'] or Path(a['path']).name+' '+str(family['xref']),'import_id':ident}
                    self.db.execute('INSERT INTO family_links VALUES (?,?)',(uuid.uuid4().hex,json.dumps(data,ensure_ascii=False)))
            self.db.execute('INSERT INTO gedcom_imports VALUES (?,?,?,?)',(ident,report['sha'],raw,json.dumps(report,ensure_ascii=False)))
        return {'id':ident,'people':len(mapping),'unsupported':report['unsupported'],'unresolved':report['unresolved']}

    def gedcom_export(self,a):
        people=self.person_list({});ids={p['id']:'@I'+str(i+1)+'@' for i,p in enumerate(people)};lines=['0 HEAD','1 SOUR ArchiveReader','1 GEDC','2 VERS 7.0'];warnings=[];sources={};links=[]
        def put(level,tag,text=''):
            parts=str(text).replace('\r','').replace('@','@@').split('\n');lines.append(f'{level} {tag}'+(' '+parts[0] if parts[0] else ''))
            for part in parts[1:]:lines.append(f'{level+1} CONT '+part)
        def cite(level,text):
            if not text:return
            if text not in sources:sources[text]='@S'+str(len(sources)+1)+'@'
            lines.append(f'{level} SOUR {sources[text]}')
        def event(level,tag,data):
            marriage=tag=='MARR'
            if marriage:tag='EVEN'
            if tag not in ['BIRT','DEAT','MARR','EVEN']:tag='EVEN'
            lines.append(f'{level} {tag}')
            if marriage:put(level+1,'TYPE','Marriage mention')
            raw_date=data.get('date','');bounds=date_bounds(raw_date) if data.get('calendar','gregorian')=='gregorian' or raw_date.strip().upper().startswith('GREGORIAN ') else None
            if bounds:
                if re.fullmatch(r'\d{4}',raw_date.strip()) or raw_date.upper().startswith('BET '):put(level+1,'DATE',raw_date.upper())
                elif bounds[0]==bounds[1]:put(level+1,'DATE',f'{bounds[0].day} '+['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'][bounds[0].month-1]+f' {bounds[0].year}')
            elif raw_date:
                put(level+1,'NOTE','Original date: '+raw_date);warnings.append({'kind':'unparsed_date_preserved_as_note','value':raw_date})
            if data.get('place'):put(level+1,'PLAC',data['place'])
            if data.get('note'):put(level+1,'NOTE',data['note'])
            cite(level+1,data.get('citation','') or (data.get('source_file','')+' '+str(data.get('person_xref','')) if data.get('import_id') else ''))
        families=[f for f in self.family_list({}) if f['status']=='confirmed' and not f['stale'] and f['left'] in ids and f['right'] in ids]
        for i,family in enumerate(families):
            ref='@F'+str(i+1)+'@';links.append((ref,family))
        for person in people:
            lines.append('0 '+ids[person['id']]+' INDI');put(1,'NAME',person['name'])
            for alias in person.get('aliases',[]):put(1,'NAME',alias)
            if person.get('sex') in ['M','F','X','U']:put(1,'SEX',person['sex'])
            if person.get('notes'):put(1,'NOTE',person['notes'])
            for data in person.get('events',[]):event(1,data.get('tag','EVEN'),data)
            card=self.person_card({'id':person['id']})
            for member in card['members']:
                mention=member['mention'];record=mention['evidence']
                if member['stale'] or mention['field']!='person':
                    put(1,'NOTE',mention['name']+' — '+mention['citation']);warnings.append({'kind':'stale_or_related_mention_as_note','person':person['id']});continue
                calendar=self.book_profile({'id':mention['page']}).get('calendar','')
                event(1,{'Народження':'BIRT','Смерті':'DEAT','Шлюби':'MARR'}.get(record['kind'],'EVEN'),{'date':record.get('date',''),'place':record.get('place',''),'note':record.get('text',''),'citation':mention['citation'],'calendar':calendar})
            for ref,family in links:
                if family['kind']=='parent' and family['right']==person['id']:lines.append('1 FAMC '+ref)
                elif person['id'] in [family['left'],family['right']]:lines.append('1 FAMS '+ref)
        for ref,family in links:
            lines.append('0 '+ref+' FAM');lines.append('1 HUSB '+ids[family['left']])
            lines.append(('1 CHIL ' if family['kind']=='parent' else '1 WIFE ')+ids[family['right']])
            put(1,'NOTE',family['note']+'\nRole placement does not assert sex; parent links are exported as separate partial families.');cite(1,family['citation'])
        for title,ref in sources.items():lines.append('0 '+ref+' SOUR');put(1,'TITL',title)
        lines.append('0 TRLR');path=Path(a['path']);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('\n'.join(lines)+'\n',encoding='utf8')
        omitted=[{'kind':'unconfirmed_or_stale_relationship','id':f['id']} for f in self.family_list({}) if f not in families]
        result={'path':str(path),'people':len(people),'warnings':warnings+omitted,'scope':'Names, notes, selected events, citations and confirmed pairwise parent/spouse links. Crops, scan files and complete audit history are not embedded.'}
        if families:result['warnings'].append({'kind':'partial_family_groups','message':'Pairwise parent links are separate partial families; gender is not inferred.'})
        path.with_suffix(path.suffix+'.report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');return result
