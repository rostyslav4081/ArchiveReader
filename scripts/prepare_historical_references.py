"""Test reference metadata separately from real-photograph transcription.

The Parkosz source was checked against the University of Warsaw academic page.
The synthetic ø image below is clearly marked TEST and is not archival evidence.
"""
import json,sys
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.historical_reading import HistoricalTools
REFERENCE={'title':'Jakub Parkoszowic — Traktat o ortografii polskiej (академічний опис UW)','url':'https://gramatyki.uw.edu.pl/book/3','locator':'Характеристика → Traktat o ortografii; абзац про голосні','resource_type':'Academic description of a historical orthography proposal','work_period':'близько1440','witness_period':'Збережена копія копії; тут не датована','edition_period':'Сучасний академічний опис','scope':'Проєкт письма Паркошовіца; не загальна практика XVст і не правило латинських метрик XVIIIст','authenticity':'Опис пропозиції реформи, не універсальна норма','checked':True}

def seed(folder,synthetic=False):
    engine=Engine(folder);tools=HistoricalTools(engine)
    if synthetic:
        path=folder.parent/'SYNTHETIC-TEST-NOT-ARCHIVAL.png';image=Image.new('RGB',(600,200),'white');draw=ImageDraw.Draw(image);draw.text((12,10),'SYNTHETIC TEST - NOT AN ARCHIVAL DOCUMENT',fill='black');font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',100);draw.text((220,50),'ø',font=font,fill='black');image.save(path);doc=engine.import_file({'path':str(path)})['id'];page=engine.db.execute('SELECT id FROM pages WHERE doc=?',(doc,)).fetchone()['id'];tools.save_annotation({'page':page,'annotation':'synthetic-oe','data':{'kind':'line','rect':[.3,.22,.3,.65],'text':'ø','verified':False,'note':'Synthetic literal for reference-display testing; NOT a photo transcription or archival record.'}})
    else:page=engine.db.execute('SELECT id FROM pages ORDER BY rowid LIMIT 1').fetchone()['id']
    state=tools.historical_get({'page':page});before=len(state['terms']);ident='source-rule-parkosz-example';existing=next((r for r in state['terms'] if r['id']==ident),None)
    args={'page':page,'term':ident,'expected':state['signature'],'form':'ø','lemma':'samogłoska nosowa','meaning':'Позначення короткого носового голосного у пропозиції Паркошовіца.','language':'pl','period':'XVст','kind':'orthography','note':'Reference UI fixture. Not a claim about the real photograph. Scope requires manual review.','reference':REFERENCE,'checked':True};tools.historical_term(args);state=tools.historical_get({'page':page});assert len(state['terms'])==before+(0 if existing else 1)
    # Same-id editing must not create another lexical row.
    args['expected']=state['signature'];tools.historical_term(args);state=tools.historical_get({'page':page});assert len(state['terms'])==before+(0 if existing else 1)
    term=next(r for r in state['terms'] if r['id']==ident);assert term['reference']['witness_period']==REFERENCE['witness_period'];assert not term.get('verified')
    if synthetic:
        analysis=tools.historical_analyze({'page':page,'annotation':'synthetic-oe'});assert analysis['original']['text']=='ø';assert any(m.get('reference',{}).get('url')==REFERENCE['url'] for token in analysis['tokens'] for m in token['matches']);assert 'reference_scope_requires_human_review' in analysis['warnings'];(folder.parent/'analysis.json').write_text(json.dumps(analysis,ensure_ascii=False,indent=2),encoding='utf-8')
    engine.db.close();return {'library':str(folder),'page':page,'synthetic':synthetic,'term_id':ident,'same_id_edit_no_duplicate':True}

def main():
    base=ROOT/'test-output/historical-ui';rows=[seed(base/language/'library') for language in ['uk','en','pl','cs']];folder=base/'reference-synthetic/library';folder.mkdir(parents=True,exist_ok=True);rows.append(seed(folder,True));(base/'reference-fixtures.json').write_text(json.dumps({'reference':REFERENCE,'cases':rows},ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(rows,indent=2))

if __name__=='__main__':main()
