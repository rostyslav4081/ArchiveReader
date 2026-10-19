"""Attach explicitly reviewed board evidence to the isolated lab's person cards.

Input JSON: {"evidence":[{"id":"stable-key","image":"local image path",
"sha256":"...","record":{...},"source":{"book":{...},"page_values":{...}},
"members":[{"node":"1:662","field":"person"}],"note":"What the image establishes",
"rect":[x,y,w,h],"relationships":[{"left_node":"...","right_node":"...",
"kind":"parent","reviewed":true,"note":"Exact reading supporting this link"}]}]}.
Unverified records stay unverified. Relationships require explicit reviewed assertions;
an arrow from the board does not qualify. Never opens the user's working library.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import uuid
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.board_import import BoardTools


def attach(path):
    lab=ROOT/'test-output/htr-lab-20261015';engine=Engine(lab/'library');tools=BoardTools(engine)
    boards=tools.board_list({})
    if len(boards)!=1:raise ValueError('Expected exactly one isolated imported board.')
    people=boards[0]['persons'];manifest=json.loads(Path(path).read_text(encoding='utf-8'));out=[]
    for item in manifest['evidence']:
        image=Path(item['image']);raw=image.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Evidence image changed.')
        if not item.get('note','').strip():raise ValueError('Provide the reading and its limits.')
        for member in item['members']:
            if member['node'] not in people or member['field'] not in ['person','related1','related2']:raise ValueError('Invalid explicit person mapping.')
        for link in item.get('relationships',[]):
            if link.get('reviewed') is not True or not link.get('note','').strip():raise ValueError('Relationship has no reviewed evidence assertion.')
            if link['left_node'] not in people or link['right_node'] not in people:raise ValueError('Unknown relationship node.')
        doc=engine.import_file({'path':str(image)})['id'];page=next(p for p in engine.list_pages({}) if p['doc']==doc and p['num']==item.get('image_page',0))
        profile=tools.book_profile({'id':page['id']});profile['split']='test';tools.book_profile({'id':page['id'],'values':profile})
        if item.get('profile'):tools.book_profile({'id':page['id'],'values':item['profile']})
        source=item.get('source',{});tools.source_card({'id':page['id'],'book':source.get('book',{}),'page_values':source.get('page_values',{})})
        ident=uuid.uuid5(uuid.NAMESPACE_URL,'archivereader-test-board-evidence:'+item['id']).hex
        fields=dict(item['record']);fields.setdefault('kind','Інші записи та примітки');fields.setdefault('verified',False);fields['notes']=(fields.get('notes','')+'\n'+item['note']).strip()
        engine.save_record(fields|{'id':ident,'page':page['id']})
        if item.get('rect'):tools.save_annotation({'page':page['id'],'annotation':'evidence-'+ident,'data':{'kind':'entry','rect':item['rect'],'text':fields.get('text',''),'verified':False,'record':ident,'note':item['note']}})
        mentions=tools.mentions()
        for member in item['members']:
            mention=next(m for m in mentions if m['record']==ident and m['field']==member['field']);tools.person_attach({'person':people[member['node']],'mention':mention,'signature':mention['signature'],'note':item['note']})
        signature=hashlib.sha256(engine.db.execute('select data from records where id=?',(ident,)).fetchone()['data'].encode('utf-8')).hexdigest()
        for link in item.get('relationships',[]):
            previous=next((r for r in tools.family_list({}) if r['record']==ident and r['left']==people[link['left_node']] and r['right']==people[link['right_node']] and r['kind']==link['kind']),None)
            tools.family_save({'id':previous['id'] if previous else None,'left':people[link['left_node']],'right':people[link['right_node']],'kind':link['kind'],'record':ident,'signature':signature,'note':link['note'],'status':'confirmed'})
        out.append({'evidence':item['id'],'page':page['id'],'record':ident,'citation':tools.source_card({'id':page['id']})['citation']})
    engine.db.close();report=lab/'attached-evidence.json';previous=json.loads(report.read_text(encoding='utf-8')) if report.is_file() else [];merged={i['evidence']:i for i in previous};merged.update({i['evidence']:i for i in out});report.write_text(json.dumps(list(merged.values()),ensure_ascii=False,indent=2),encoding='utf-8');return out

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('manifest');args=parser.parse_args();print(json.dumps(attach(args.manifest),ensure_ascii=True))
