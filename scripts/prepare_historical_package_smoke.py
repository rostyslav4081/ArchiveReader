"""Isolated real-photo package and literal-word compatibility checks, never ground truth."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.historical_reading import HistoricalTools
rows=[]
for lang in ['uk','en','pl','cs','reference-synthetic']:
 folder=ROOT/'test-output/historical-ui'/lang/'library';engine=Engine(folder);t=HistoricalTools(engine);page=engine.db.execute('select id from pages order by rowid limit 1').fetchone()['id'];state=t.historical_get({'page':page});region=next(r for r in state['regions'] if r['kind']=='line' and r['text']);literal=region['text'];p=t.historical_package_get({'page':page});termids=[r['id'] for r in p['available_terms']];sourceids=[r['id'] for r in p['reference_sources'][:1]]
 args={'page':page,'expected':p['signature'],'configured':True,'term_ids':[],'source_ids':sourceids,'notes':'Explicit isolated UI test selection; not document verification.','checked':True};empty=t.historical_package_save(args);a=t.historical_analyze({'page':page,'annotation':region['id']});assert all(not token['matches'] for token in a['tokens']);args.update(expected=empty['signature'],term_ids=termids);saved=t.historical_package_save(args);assert saved['term_ids']==termids
 token=next(iter(t.historical_analyze({'page':page,'annotation':region['id']})['tokens']));word=t.historical_word({'page':page,'annotation':region['id'],'start':token['start'],'end':token['end']});assert word['literal']==literal[token['start']:token['end']];assert word['crop']['geometry_basis']=='whole_saved_region';assert word['saved'] is False
 parent=region['rect'];rect=[parent[0]+parent[2]*.1,parent[1]+parent[3]*.1,parent[2]*.2,parent[3]*.8];manual=t.historical_word({'page':page,'annotation':region['id'],'start':token['start'],'end':token['end'],'rect':rect});assert manual['crop']['geometry_basis']=='human_manual_word_rect';assert t.historical_analyze({'page':page,'annotation':region['id']})['original']['text']==literal
 out=folder.parent/'package-word-fixture.json';out.write_text(json.dumps({'page':page,'annotation':region['id'],'literal':literal,'package':saved,'word':word,'manual_crop':manual,'empty_package_disables_hints':True,'gt_eligible':False},ensure_ascii=False,indent=2),encoding='utf-8');rows.append({'language':lang,'page':page,'empty_package_disables_hints':True,'literal_preserved':True,'whole_line_and_manual_crop':True,'term_count':len(termids),'source_count':len(sourceids)});engine.db.close()
(ROOT/'test-output/historical-ui/package-word-fixtures.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(rows))
