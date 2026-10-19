import json,tempfile,unittest
from pathlib import Path
from PIL import Image
from backend.archivereader.engine import Engine,KINDS
from backend.archivereader.library import LibraryTools

class IncrementalIndexTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'test-output');self.root=Path(self.tmp.name);f=self.root/'pages.tif';Image.new('RGB',(20,20),'white').save(f,save_all=True,append_images=[Image.new('RGB',(20,20),'red') for _ in range(11)]);self.e=Engine(self.root/'library');self.e.import_file({'path':str(f)});self.t=LibraryTools(self.e);self.pages=self.e.list_pages({})
 def tearDown(self):self.e.db.close();self.tmp.cleanup()
 def test_bounded_progress_resumes_and_excludes_stale_search_hits(self):
  page=self.e.db.execute('SELECT page FROM search_dirty ORDER BY rowid LIMIT 1').fetchone()['page'];record=self.e.save_record({'page':page,'kind':KINDS[0],'person':'OldSurname'})['id']
  result=self.t.index_step({'limit':2,'budget_ms':1000});self.assertEqual(2,result['processed']);self.assertEqual(10,result['remaining'])
  self.assertTrue(self.t.library_search({'query':'OldSurname','refresh_limit':0})['rows'])
  self.e.save_record({'id':record,'page':page,'kind':KINDS[0],'person':'NewSurname'})
  search=self.t.library_search({'query':'OldSurname','refresh_limit':0});self.assertFalse(search['rows']);self.assertEqual(11,search['coverage']['index_remaining'])
  self.e.db.close();self.e=Engine(self.root/'library');self.t=LibraryTools(self.e)
  for _ in range(10):
   if self.t.index_step({'limit':2,'budget_ms':1000})['complete']:break
  self.assertTrue(self.t.library_search({'query':'NewSurname','refresh_limit':0})['rows']);self.assertTrue(self.t.index_status({})['complete'])
 def test_record_move_invalidates_both_old_and_new_pages_and_delete_is_indexed(self):
  first,second=[p['id'] for p in self.pages[:2]];record=self.e.save_record({'page':first,'kind':KINDS[0],'person':'Surname'})['id'];self.t.index_step({'limit':100,'budget_ms':1000})
  with self.e.db:self.e.db.execute('UPDATE records SET page=? WHERE id=?',(second,record))
  dirty={r['page'] for r in self.e.db.execute('SELECT page FROM search_dirty')};self.assertEqual({first,second},dirty);self.t.index_step({'limit':100,'budget_ms':1000})
  self.assertEqual(second,self.t.library_search({'query':'Surname','refresh_limit':0})['rows'][0]['page'])
  with self.e.db:self.e.db.execute('DELETE FROM records WHERE id=?',(record,))
  self.assertFalse(self.t.library_search({'query':'Surname','refresh_limit':0})['rows']);self.t.index_step({'limit':100,'budget_ms':1000});self.assertFalse(self.t.library_search({'query':'Surname','refresh_limit':0})['rows'])

 def test_existing_fts_upgrade_keeps_search_and_indexes_replacement_by_page(self):
  page=self.pages[0]['id'];self.e.save_record({'page':page,'kind':KINDS[0],'person':'UpgradeSurname'})
  self.t.index_step({'limit':100,'budget_ms':1000})
  # Simulate an existing pre-mapping library: FTS rows survive the upgrade.
  with self.e.db:self.e.db.execute('DROP TABLE search_fts_rows')
  self.t=LibraryTools(self.e)
  self.assertTrue(self.t.library_search({'query':'UpgradeSurname','refresh_limit':0})['rows'])
  self.assertEqual(self.e.db.execute('SELECT COUNT(*) FROM library_fts').fetchone()[0],self.e.db.execute('SELECT COUNT(*) FROM search_fts_rows').fetchone()[0])
  plan=' '.join(str(tuple(r)) for r in self.e.db.execute('EXPLAIN QUERY PLAN SELECT entry FROM search_fts_rows WHERE page=?',(page,)))
  self.assertIn('idx_search_fts_rows_page',plan)
  with self.e.db:self.e.db.execute('DELETE FROM records WHERE page=?',(page,))
  self.t.index_step({'limit':100,'budget_ms':1000})
  self.assertFalse(self.t.library_search({'query':'UpgradeSurname','refresh_limit':0})['rows'])
  self.assertEqual(0,self.e.db.execute('SELECT COUNT(*) FROM search_fts_rows m LEFT JOIN library_fts f ON f.rowid=m.entry WHERE f.rowid IS NULL').fetchone()[0])

 def test_two_workers_can_upgrade_legacy_fts_mapping_concurrently(self):
  import sqlite3,threading
  from concurrent.futures import ThreadPoolExecutor
  from types import SimpleNamespace
  from unittest.mock import patch
  barrier=threading.Barrier(2);original_connect=sqlite3.connect
  with self.e.db:self.e.db.execute('DROP TABLE search_fts_rows')
  class Connection(sqlite3.Connection):
   checked=False
   def execute(connection,sql,*args,**kwargs):
    cursor=super(Connection,connection).execute(sql,*args,**kwargs)
    if sql=="SELECT 1 FROM sqlite_master WHERE type='table' AND name='search_fts_rows'" and not connection.checked:
     connection.checked=True;result=cursor.fetchone();cursor.close();barrier.wait(timeout=15)
     return SimpleNamespace(fetchone=lambda:result)
    return cursor
  def connect(*args,**kwargs):return original_connect(*args,**kwargs,factory=Connection)
  def upgrade():
   engine=Engine(self.e.root)
   try:return LibraryTools(engine).index_status({})
   finally:engine.db.close()
  with patch('sqlite3.connect',connect),ThreadPoolExecutor(max_workers=2) as pool:
   futures=[pool.submit(upgrade) for _ in range(2)]
   results=[future.result(timeout=30) for future in futures]
  self.assertEqual([12,12],[r['total'] for r in results])
  self.assertEqual(1,self.e.db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='idx_search_fts_rows_page'").fetchone()[0])

if __name__=='__main__':unittest.main()
