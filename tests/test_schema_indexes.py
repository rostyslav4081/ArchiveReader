from pathlib import Path
import tempfile,unittest
from PIL import Image
from backend.archivereader.engine import Engine,handle_request
from backend.archivereader.books import BookTools
from backend.archivereader.operations import Operations
from backend.archivereader.genealogy import GenealogyTools
from backend.archivereader.schema_indexes import INDEXES,ensure_indexes

class SchemaIndexTests(unittest.TestCase):
 def test_fresh_and_reopened_feature_tables_use_covering_lookup_indexes(self):
  root=Path(__file__).resolve().parents[1]/'test-output'
  with tempfile.TemporaryDirectory(dir=root) as tmp:
   e=Engine(Path(tmp)/'library')
   try:
    BookTools(e);Operations(e);GenealogyTools(e)
    before=list(e.db.execute('SELECT * FROM records'));ensure_indexes(e.db);ensure_indexes(e.db)
    names={r['name'] for r in e.db.execute("SELECT name FROM sqlite_master WHERE type='index'")};self.assertTrue(set(INDEXES)<=names)
    for name,(table,columns) in INDEXES.items():
     predicate=' AND '.join(c+'=?' for c in columns.split(','));plan=' '.join(str(tuple(r)) for r in e.db.execute('EXPLAIN QUERY PLAN SELECT * FROM '+table+' WHERE '+predicate,['x']*len(columns.split(','))))
     self.assertIn(name,plan)
    self.assertEqual(before,list(e.db.execute('SELECT * FROM records')))
   finally:e.db.close()
   result=handle_request({'root':str(Path(tmp)/'library'),'command':'list_pages'});self.assertEqual([],result)

if __name__=='__main__':unittest.main()
