"""Separate four-language UI fixtures using the real death334scan5 JPEG.

All readings are partial test drafts, never verified reference text or genealogy.
"""
import hashlib,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.historical_reading import HistoricalTools

def main():
    source=ROOT/'test-output/gologory-source-research/PL_1_301_334_0003.jpg';before=hashlib.sha256(source.read_bytes()).hexdigest()
    metadata=json.loads((ROOT/'test-output/gologory-surname-review/manual-lines.json').read_text(encoding='utf-8'));reports=[]
    for language in ['uk','en','pl','cs']:
        folder=ROOT/'test-output/historical-ui'/language;engine=Engine(folder/'library');tools=HistoricalTools(engine);doc=engine.import_file({'path':str(source)})['id'];page=engine.db.execute('SELECT id FROM pages WHERE doc=?',(doc,)).fetchone()['id']
        draft=['Die 12 ... Sepelivi ... Mariannam [Sko?]','[wra?] annorum circiter ...','... Ecclesiae Parochialis ...']
        for index,line in enumerate(metadata['lines']):tools.save_annotation({'page':page,'annotation':'historical-smoke-line'+str(index+1),'data':{'kind':'line','rect':line['source_region']['rect_normalized'],'text':draft[index],'verified':False,'note':'Partial uncertain test draft; not ground truth.'}})
        state=tools.historical_get({'page':page});tools.historical_profile({'page':page,'expected':state['profile']['signature'],'values':{'origin':'Gologory / AGAD301/334','period':'1755–1795','institution':'Parish / archive microfilm','rite':'Roman Catholic','script':'Latin cursive','writer':'Unknown; test profile','languages':['la','pl'],'notes':'Real source image; all drafts below remain uncertain test material.'}})
        state=tools.historical_get({'page':page});tools.historical_term({'page':page,'expected':state['signature'],'form':'Sepelivi','lemma':'sepelio','meaning':'to bury / поховати','language':'la','period':'18th century','writer':'','kind':'word','note':'Lexicon UI fixture; does not confirm the reading of this scan.','checked':True})
        state=tools.historical_get({'page':page});tools.historical_layout({'page':page,'expected':state['signature'],'role':'text','rect':[.07,.10,.43,.125],'note':'Manual first-entry boundary for UI testing.','checked':True})
        state=tools.historical_get({'page':page});parent=metadata['lines'][0]['source_region']['rect_normalized'];tools.historical_exemplar({'page':page,'expected':state['signature'],'annotation':'historical-smoke-line1','rect':[parent[0]+parent[2]*.72,parent[1]+parent[3]*.12,parent[2]*.07,parent[3]*.72],'label':'?','note':'Uncertain stroke sample, not a training label.','checked':True})
        analysis=tools.historical_analyze({'page':page,'annotation':'historical-smoke-line1'});tools.historical_decide({'page':page,'annotation':'historical-smoke-line1','signature':analysis['signature'],'reading':draft[0],'interpretation':'Surname candidate requires independent review.','note':'UI test only. No person identity or family relation confirmed.','checked':True,'uncertain':True})
        engine.settings({'values':{'uiLanguage':language}});reopened=tools.historical_get({'page':page});assert not any(r.get('verified') for r in reopened['regions']);assert all(not r.get('gt_eligible') for r in reopened['decisions']);reports.append({'language':language,'library':str(folder/'library'),'page':page,'terms':len(reopened['terms']),'decisions':len(reopened['decisions']),'exemplars':len(reopened['exemplars']),'layouts':len(reopened['layout'])});engine.db.close()
    assert hashlib.sha256(source.read_bytes()).hexdigest()==before
    (ROOT/'test-output/historical-ui/fixtures.json').write_text(json.dumps({'source':str(source),'source_sha256':before,'source_unchanged':True,'cases':reports},ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(reports,indent=2))

if __name__=='__main__':main()
