"""Import user board only into the isolated test library; never the working library."""
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.archivereader.engine import Engine
from backend.archivereader.board_import import BoardTools

root=Path(__file__).resolve().parents[1]/'test-output/figma-family-tree'
engine=Engine(root/'library');tools=BoardTools(engine)
args={'path':str(root/'raw-board.json'),'assets':str(root/'asset-manifest.json'),'people':['1:41','1:65','1:94','1:153','1:208','1:279','1:443','1:446','1:549','1:622','1:662','1:746','1:767','1:1082','1:1108']}
args['sha']=tools.board_preview(args)['sha'];result=tools.board_import(args);again=tools.board_import(args)
assert again['already_imported'] and len(result['persons'])==15 and len(tools.person_list({}))==15
assert not tools.family_list({})
export=tools.board_get({'id':result['id'],'export':str(root/'export')})
assert (root/'export/board.json').read_bytes()==(root/'raw-board.json').read_bytes()
for asset in export['assets']:assert hashlib.sha256(Path(asset['path']).read_bytes()).hexdigest()==asset['sha']
engine.db.close();engine=Engine(root/'library');reopened=BoardTools(engine).board_get({'id':result['id']});assert reopened['snapshot']==result['snapshot'];engine.db.close()
report={'people':len(result['persons']),'nodes':len(result['snapshot']['nodes']),'assets':len(result['assets']),'connectors':result['counts']['connectors'],'source_sha':result['sha'],'idempotency':True,'reopen':True,'family_links_confirmed':0}
(root/'import-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
