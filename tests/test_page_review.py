import json,os,unittest
from pathlib import Path
from unittest.mock import patch
from tests import test_layout as fixtures
from backend.archivereader.page_review import PageReviewTools

class PageReviewTests(unittest.TestCase):
 def setUp(self):
  self.f=fixtures.LayoutTests();self.f.setUp();self.t=PageReviewTools(self.f.engine);self.model=self.f.root/'model.mlmodel';self.model.write_bytes(b'model');self.args={'id':self.f.page['id'],'model':str(self.model)}
 def tearDown(self):self.f.tearDown()
 def prediction(self,a):
  region=next(r for r in self.t.annotations({'id':a['id']}) if r['id']==a['annotation']);return {'id':'run-'+a['annotation'],'text':'raw text','lines':[{'text':'raw text','rect':region['rect']}],'review_flags':[]}
 def test_full_page_spread_order_checkpoint_and_retry_only_failed(self):
  job=self.t.page_review_start(self.args|{'spread':True});ident=job['job'];self.assertEqual([u['rect'] for u in job['units']],[[0,0,.5,1],[.5,0,.5,1]])
  with patch.object(self.t,'recognize_region',side_effect=[self.prediction(self.args|{'annotation':job['units'][0]['annotation']}),RuntimeError('controlled failure')]) as infer:
   a=self.t.page_review_step({'job':ident});self.assertEqual(a['counts']['done'],1);b=self.t.page_review_step({'job':ident});self.assertEqual(b['counts']['failed'],1);self.assertEqual(infer.call_count,2)
  with patch.object(self.t,'recognize_region',side_effect=self.prediction) as infer:
   resumed=self.t.page_review_step({'job':ident,'retry_failed':True});self.assertEqual(resumed['counts']['done'],2);self.assertEqual(infer.call_count,1);self.assertEqual(resumed['units'][0]['attempts'],1);self.assertEqual(resumed['units'][1]['attempts'],2);self.assertFalse(resumed['coverage_complete'])
  self.assertEqual(self.f.engine.page(self.args['id'])['text'],'Original page OCR')
 def test_interrupted_owner_recovered_live_owner_protected(self):
  job=self.t.page_review_start(self.args);ident=job['job'];raw=self.t.load(ident);raw['units'][0].update(state='running',pid=os.getpid());self.t.store(ident,raw)
  with patch.object(self.t,'recognize_region',side_effect=self.prediction):
   with self.assertRaises(ValueError):self.t.page_review_step({'job':ident})
   raw['units'][0]['pid']=999999999;self.t.store(ident,raw);done=self.t.page_review_step({'job':ident});self.assertEqual(done['counts']['done'],1)
 def test_changed_source_or_model_blocks_resume_and_saved_scopes_keep_order(self):
  one=self.t.save_annotation({'page':self.args['id'],'data':{'kind':'column','rect':[.5,0,.5,1],'reading_order':1}})['id'];two=self.t.save_annotation({'page':self.args['id'],'data':{'kind':'column','rect':[0,0,.5,1],'reading_order':2}})['id'];job=self.t.page_review_start(self.args|{'use_saved':True});self.assertEqual([u['annotation'] for u in job['units']],[one,two]);self.model.write_bytes(b'changed')
  with patch.object(self.t,'recognize_region',side_effect=AssertionError('must not infer')):
   with self.assertRaises(ValueError):self.t.page_review_step({'job':job['job']})
 def test_empty_output_explicit_and_geometry_not_coverage_truth(self):
  job=self.t.page_review_start(self.args)
  with patch.object(self.t,'recognize_region',return_value={'id':'empty','text':'','lines':[{'text':'','rect':[.1,.1,.1,.1]}]}):r=self.t.page_review_step({'job':job['job']})
  self.assertEqual(r['counts']['empty'],1);self.assertEqual(r['boxes'][0]['state'],'empty');self.assertFalse(r['coverage_complete']);self.assertEqual(r['state'],'review')

 def test_extreme_aspect_ratio_mask_is_bounded_and_atomic_artifacts_complete(self):
  from PIL import Image
  source=self.f.root/'thin.png';Image.new('RGB',(1,7000),'black').save(source);doc=self.f.engine.import_file({'path':str(source)});page=self.f.engine.db.execute('select id from pages where doc=?',(doc['id'],)).fetchone()[0]
  job=self.t.page_review_start(self.args|{'id':page})
  with Image.open(job['coverage_path']) as mask:self.assertLessEqual(mask.width,768);self.assertLessEqual(mask.height,1600)
  folder=Path(job['report']).parent;self.assertFalse(list(folder.glob('*.tmp')));json.loads((folder/'report.json').read_text('utf-8'))

 def test_book_map_includes_separate_page_job_without_overwriting_page_text(self):
  with self.f.engine.db:self.f.engine.db.execute("update pages set text='',lines='[]' where id=?",(self.args['id'],))
  job=self.t.page_review_start(self.args);self.assertEqual(self.t.book_quality_map({'id':self.args['id']})['pages'][0]['state'],'page_processing')
  with patch.object(self.t,'recognize_region',side_effect=self.prediction):self.t.page_review_step({'job':job['job']})
  row=self.t.book_quality_map({'id':self.args['id']})['pages'][0];self.assertEqual(row['state'],'machine_read');self.assertEqual(row['page_job']['done'],1);self.assertEqual(self.f.engine.page(self.args['id'])['text'],'')

 def test_comparison_preserves_original_and_reuses_same_layout(self):
  original=self.t.page_review_start(self.args)
  with self.assertRaises(ValueError):self.t.page_review_fork({'job':original['job'],'model':str(self.model)})
  with patch.object(self.t,'recognize_region',side_effect=self.prediction):self.t.page_review_step({'job':original['job']})
  before=self.t.load(original['job']);other=self.f.root/'other.mlmodel';other.write_bytes(b'other model')
  with self.assertRaises(ValueError):self.t.page_review_fork({'job':original['job'],'model':str(self.model)})
  fork=self.t.page_review_fork({'job':original['job'],'model':str(other)})
  with patch.object(self.t,'recognize_region',side_effect=self.prediction) as inference:
   self.t.page_review_step({'job':fork['job']})
   self.assertEqual(inference.call_args.args[0]['reuse_layout_run'],before['units'][0]['run'])
   self.assertFalse(inference.call_args.args[0]['use_saved_lines'])
  self.assertEqual(self.t.load(original['job']),before)

if __name__=='__main__':unittest.main()
