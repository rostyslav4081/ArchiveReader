from tests.support import workspace_tempdir
import json,tempfile,unittest,hashlib
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from backend.archivereader.engine import Engine
from backend.archivereader.research_hub import HubTools
class ResearchHubTests(unittest.TestCase):
 def setUp(self):
  self.tmp=workspace_tempdir();self.root=Path(self.tmp.name);self.e=Engine(self.root/'library');self.h=HubTools(self.e);self.source=self.root/'photo.png';Image.new('RGB',(120,150),'white').save(self.source);self.e.import_file({'path':str(self.source)});self.page=self.e.list_pages({})[0]['id'];self.doc=self.e.page(self.page)['doc'];self.annotation=self.h.save_annotation({'page':self.page,'data':{'kind':'line','rect':[.1,.1,.7,.1]}})['id']
 def tearDown(self):self.e.db.close();self.tmp.cleanup()
 def comparison(self):
  folder=self.e.root/'results'/'saved';folder.mkdir(parents=True,exist_ok=True);(folder/'report.json').write_text(json.dumps({'rows':[{'id':self.annotation,'rect':[.1,.1,.7,.1],'results':{'a':{'text':'1838 Skowyra 34'},'b':{'text':'1839 Skowyra 35'}}}]}),'utf-8');self.e.db.execute('INSERT OR REPLACE INTO comparison_runs(id,doc,path) VALUES (?,?,?)',('run',self.doc,str(folder)));self.e.db.commit()
 def test_disagreement_has_no_guessed_semantic_field_and_stale_rejected(self):
  self.comparison();row=self.h.hub_queue({'id':self.page})['rows'][0];self.assertEqual(row['field'],'unknown');self.assertEqual(row['field_binding'],'unbound')
  self.h.hub_review({'id':self.page,'key':row['key'],'signature':row['signature'],'priority':3,'field':'house','note':'Check against source'})
  self.assertEqual(self.h.hub_queue({'id':self.page})['rows'][0]['priority'],3)
  self.h.save_annotation({'page':self.page,'annotation':self.annotation,'data':{'kind':'line','rect':[.2,.1,.7,.1]}})
  changed=self.h.hub_queue({'id':self.page})['rows'][0];self.assertTrue(changed['stale']);self.assertTrue(changed['action_stale'])
  with self.assertRaises(ValueError):self.h.hub_review({'id':self.page,'key':changed['key'],'signature':changed['signature'],'priority':2,'note':'stale'})
  self.assertEqual(self.e.db.execute('SELECT COUNT(*) FROM hub_review_history').fetchone()[0],1)
 def test_photo_preview_preserves_original_and_database(self):
  before=hashlib.sha256(self.source.read_bytes()).hexdigest();docs=self.e.db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]
  r=self.h.hub_photo({'id':self.page,'mode':'contrast','angle':5});self.assertTrue(r['preview_only']);self.assertTrue(Path(r['processed']['path']).is_file());self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),before);self.assertEqual(self.e.db.execute('SELECT COUNT(*) FROM documents').fetchone()[0],docs)
 def test_compound_search_explains_differences_without_links(self):
  self.e.db.execute('INSERT INTO records VALUES (?,?,?)',('r',self.page,json.dumps({'person':'Jan Skowyra','place':'Lipivtsi','house':'34','date':'1838','related1':'Ignatius'})));self.e.db.commit()
  r=self.h.hub_family_search({'id':self.page,'person':'Skowyra','house':'35','related1':'Ignatius','include_differences':True});self.assertEqual(len(r['rows']),1);self.assertEqual(r['rows'][0]['differences'],1);self.assertFalse(r['rows'][0]['automatic_link']);self.assertEqual(self.h.hub_family_search({'id':self.page,'person':'Skowyra','house':'35'})['rows'],[])
 def test_gap_report_no_recognition_and_unverified_count(self):
  self.e.db.execute('INSERT INTO records VALUES (?,?,?)',('r',self.page,json.dumps({'person':'Jan','verified':False})));self.e.db.commit()
  with patch.object(self.e,'render',side_effect=AssertionError('report must not render')):
   r=self.h.hub_gaps({'id':self.page});self.assertEqual(r['counts']['pages'],1);self.assertEqual(r['counts']['unverified_records'],1);self.assertEqual(r['counts']['explicit_gaps'],0);self.assertEqual(r['counts']['indexed_pages'],0)
 def test_reports_scoped_before_limit_and_missing_report_safe(self):
  self.comparison()
  for i in range(110):self.e.db.execute('INSERT INTO comparison_runs(id,doc,path) VALUES (?,?,?)',(str(i),'other','absent'))
  self.e.db.commit();r=self.h.hub_queue({'id':self.page});self.assertEqual(len(r['rows']),1);self.assertEqual(r['reports_considered'],1)
 def test_explicit_gap_and_profile_template_preserve_manual_exception(self):
  book=self.h.book_save({'name':'Test book','items':[{'page':self.page},{'label':'folio 7 missing','note':'known tear'}]})
  self.h.book_template({'book':book['id'],'columns':[{'rect':[.1,.1,.3,.8],'field':'person','label':'Name'}]})
  self.h.save_annotation({'page':self.page,'data':{'kind':'column','rect':[.2,.1,.3,.8],'field':'house','label':'manual exception'}})
  profile=self.h.hub_profile({'id':self.page});self.assertEqual(profile['book']['id'],book['id']);self.assertEqual(profile['current_page_columns'],1)
  applied=self.h.book_template({'book':book['id'],'apply':True,'pages':[self.page]});self.assertEqual(applied['skipped'],1);self.assertEqual(applied['added'],0)
  gap=self.h.hub_gaps({'id':self.page});self.assertEqual(gap['counts']['explicit_gaps'],1);self.assertEqual(gap['issues'][0]['label'],'folio 7 missing')
if __name__=='__main__':unittest.main()
