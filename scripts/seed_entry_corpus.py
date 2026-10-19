"""Create evaluation drafts from saved entries in the isolated demonstration lab.

Never opens the user's working library and never confirms a reference.
"""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.review_corpus import CorpusTools

if __name__=='__main__':
    library=ROOT/'test-output/htr-lab-20261015/library'
    if not (library/'archive.sqlite').is_file():raise SystemExit('Create the isolated demonstration library first.')
    engine=Engine(library);tools=CorpusTools(engine)
    result=tools.corpus_import({});rows=tools.corpus_list({})
    result['drafts']=sum(not r['human_verified'] for r in rows)
    result['human_verified']=sum(r['human_verified'] for r in rows)
    result['eligible']=sum(r['eligible'] for r in rows)
    (library.parent/'entry-corpus-seed.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    engine.db.close();print(json.dumps(result,ensure_ascii=True))
