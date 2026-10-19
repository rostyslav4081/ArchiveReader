"""Exercise the real WPF window and render all four locales using synthetic data."""
import os
from pathlib import Path
import subprocess
import sys
import argparse
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--roadmap',action='store_true'); parser.add_argument('--backups',action='store_true'); parser.add_argument('--shortcuts',action='store_true'); parser.add_argument('--layout',action='store_true'); parser.add_argument('--library',action='store_true'); parser.add_argument('--workbench',action='store_true'); parser.add_argument('--compare',action='store_true'); parser.add_argument('--language',choices=['uk','en','pl','cs']); args=parser.parse_args()
    output=ROOT/'test-output'/('ui-roadmap' if args.roadmap else 'ui-backups' if args.backups else 'ui-shortcuts' if args.shortcuts else 'ui-layout' if args.layout else 'ui-library' if args.library else 'ui-comparison' if args.compare else 'ui')
    output.mkdir(parents=True,exist_ok=True)
    source=output/'synthetic.png'
    im=Image.new('RGB',(1200,1500),'#fffdf4')
    draw=ImageDraw.Draw(im)
    font=ImageFont.truetype('C:/Windows/Fonts/times.ttf',38)
    draw.text((80,100),'ARCHIVE READER - TEST\n\n14 Martii 1832\nJoannes filius Pauli et Annae\nDomus 34\n\nSynthetic test. Not an archival record.',fill='black',font=font,spacing=25)
    if args.layout:
        for x in [80,650]:
            for y in [650,730,810,890]: draw.text((x,y),'Joannes filius Pauli',fill='black',font=ImageFont.truetype('C:/Windows/Fonts/times.ttf',28))
    im.save(source)
    reference=None
    if args.compare:
        import json
        cases=json.loads((ROOT/'test-output/handwriting/manifest.json').read_text(encoding='utf8'))
        case=next((c for c in cases if c['reference']=='ADRIEN HOLY'),next(c for c in cases if len(c['reference'])>20))
        output=output/'name-differences'; output.mkdir(parents=True,exist_ok=True)
        source=output/'handwritten-sample.png'
        with Image.open(ROOT/'test-output/handwriting'/case['image']) as sample: sample.save(source)
        reference=case['reference']
    app=ROOT/'bin'/'Release'/'net10.0-windows'/'ArchiveReader.exe'
    for language in ([args.language] if args.language else ['uk','en','pl','cs']):
        folder=output/language
        engine=Engine(folder); engine.import_file({'path':str(source)})
        if args.workbench:
            from backend.archivereader.sources import SourceTools
            cards=SourceTools(engine); source_page=engine.list_pages({})[0]
            cards.source_card({'id':source_page['id'],'book':{'archive':'Synthetic archive','fonds':'42','inventory':'7','file':'9','title':'Synthetic register','url':'https://example.org/book'},'page_values':{'folio':'12 verso'}})
            for ident,name,house in [('smoke-person-first','Joannes Kowalski','34'),('smoke-person-second','Joannes Kowalsky','35')]:
                engine.save_record({'id':ident,'page':source_page['id'],'kind':'Інші записи та примітки','person':name,'related1':'Paulus','place':'Synthetic village','house':house,'date':'1832','text':'Synthetic evidence. Not an archival record.'})
        if args.layout:
            import json
            from backend.archivereader.layout import LayoutTools
            layout=LayoutTools(engine); page=engine.list_pages({})[0]
            lines=[{'box':[x,y,300,32],'text':'Joannes filius Pauli'} for x in [80,650] for y in [650,730,810,890]]
            with engine.db: engine.db.execute('UPDATE pages SET lines=? WHERE id=?',(json.dumps(lines),page['id']))
            if not layout.annotations({'id':page['id']}): layout.save_annotation({'page':page['id'],'data':{'kind':'column','rect':[.05,.42,.35,.22],'label':'Manual column','reading_order':1}})
        if args.library:
            from backend.archivereader.library import LibraryTools
            tools=LibraryTools(engine); page=engine.list_pages({})[0]
            records=engine.details({'id':page['id']})['records']
            engine.save_record({'page':page['id'],'kind':'Інші записи та примітки','person':'Joannes','text':'Joannes filius Pauli et Annae'}|({'id':records[0]['id']} if records else {}))
            if not tools.annotations({'id':page['id']}):
                tools.save_annotation({'page':page['id'],'data':{'kind':'missing','rect':[.1,.4,.2,.1],'text':'Synthetic missing area'}})
                tools.save_annotation({'page':page['id'],'data':{'kind':'column','rect':[.1,.1,.8,.8],'label':'Names'}})
            if not tools.template_list({'id':page['id']}): tools.template_save({'id':page['id'],'name':'Synthetic template'})
            tools.book_profile({'id':page['id'],'values':{'languages':'la','script':'Printed synthetic sample','split':'test'}})
        if args.compare:
            from backend.archivereader.workbench import Workbench
            bench=Workbench(engine); page=engine.list_pages({})[0]
            if not bench.annotations({'id':page['id']}): bench.save_annotation({'page':page['id'],'data':{'kind':'line','rect':[0,0,1,1],'text':reference,'verified':True}})
        if args.roadmap:
            from backend.archivereader.genealogy import GenealogyTools
            from backend.archivereader.research import ResearchTools
            genealogy=GenealogyTools(engine);page=engine.list_pages({})[0]
            engine.save_record({'id':'roadmap-child','page':page['id'],'kind':'Народження','person':'Jan Kowalski','date':'12.03.1832','text':'Nomen: Jan Kowalski; pater: Paulus; mater: Anna\nDomus 34\n12.03.1832'})
            engine.save_record({'id':'roadmap-father','page':page['id'],'kind':'Інші записи та примітки','person':'Paulus Kowalski','date':'1802','text':'Synthetic father evidence'})
            existing=genealogy.person_list({})
            if not existing:
                child=genealogy.person_save({'name':'Jan Kowalski'})['id'];father=genealogy.person_save({'name':'Paulus Kowalski'})['id']
                mentions=genealogy.mentions()
                for person,record in [(child,'roadmap-child'),(father,'roadmap-father')]:
                    mention=next(m for m in mentions if m['record']==record and m['field']=='person');genealogy.person_attach({'person':person,'mention':mention,'signature':mention['signature'],'note':'Synthetic manually checked example'})
                mention=next(m for m in mentions if m['record']=='roadmap-child');genealogy.family_save({'left':father,'right':child,'kind':'parent','record':mention['record'],'signature':mention['signature'],'note':'Synthetic family relationship'})
            research=ResearchTools(engine);mention=next(m for m in research.mentions() if m['record']=='roadmap-child' and m['field']=='person')
            research.fact_crop({'mention':mention,'fact':'date','rect':[.06,.12,.65,.15]})
            if not research.book_dictionary({'page':page['id'],'query':'Kowalski'}):research.book_dictionary({'page':page['id'],'term':'Kowalski','meaning':'Synthetic verified surname','verified':True})
            duplicate=output/'synthetic-duplicate.png';im.resize((600,750)).save(duplicate);engine.import_file({'path':str(duplicate)})
            from backend.archivereader.books import BookTools
            books=BookTools(engine)
            if not books.books({}):
                books.book_save({'name':'Synthetic photo book','items':[{'page':p['id'],'label':p['name']} for p in engine.list_pages({})]+[{'label':'Missing folio 3'}]})
                books.research_task({'page':page['id'],'data':{'text':'Synthetic date review','rect':[.1,.1,.5,.2],'done':False}})
            (folder/'smoke-tree.ged').write_text('0 HEAD\n1 GEDC\n2 VERS 7.0\n0 @I1@ INDI\n1 NAME Test /Person/\n1 BIRT\n2 DATE ABT 1800\n1 OBJE @O1@\n0 TRLR\n',encoding='utf8')
        if args.shortcuts:
            import json
            page=engine.list_pages({})[0]
            with engine.db:
                engine.db.execute('DELETE FROM line_corrections WHERE page=?',(page['id'],))
                engine.db.execute('UPDATE pages SET lines=? WHERE id=?',(json.dumps([{'text':'First line','box':[80,100,400,40]},{'text':'Second line','box':[80,180,400,40]}]),page['id']))
        engine.db.close()
        env=os.environ.copy(); env['ARCHIVEREADER_DATA']=str(folder); env['ARCHIVEREADER_LANGUAGE']=language; env['ARCHIVEREADER_PYTHON']=sys.executable
        if args.compare: env['ARCHIVEREADER_SMOKE_COMPARE']='1'
        startup=subprocess.STARTUPINFO(); startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW; startup.wShowWindow=0
        subprocess.run([str(app),'--smoke-test']+(['--smoke-roadmap'] if args.roadmap else [])+(['--smoke-backups'] if args.backups else [])+(['--smoke-shortcuts'] if args.shortcuts else [])+(['--smoke-library'] if args.library else [])+(['--smoke-layout'] if args.layout else [])+(['--smoke-workbench'] if args.workbench or args.compare or args.layout else []),env=env,startupinfo=startup,check=True,timeout=180 if args.compare or args.roadmap else 60)
        if not (folder/'window.png').is_file(): raise RuntimeError(f'No rendered window: {language}')
        if args.roadmap:
            check=Engine(folder)
            try:
                records=check.details({'id':check.list_pages({})[0]['id']})['records']
                if not any(r['text'].endswith('Synthetic close-save regression') for r in records): raise RuntimeError('Close did not save the edited record')
                expected=[folder/'genealogy-ui'/f'tab-{i}.png' for i in range(6)]+[folder/'operations-ui'/f'tab-{i}.png' for i in range(3)]+[folder/'research-ui'/f'tab-{i}.png' for i in range(2)]+[folder/'extraction-ui/window.png']
                expected.extend(folder/'books-ui'/f'tab-{i}.png' for i in range(5))
                if not all(p.is_file() for p in expected):raise RuntimeError('Missing roadmap UI render')
            finally:check.db.close()
        print(f'{language}: OK')


if __name__=='__main__': main()
