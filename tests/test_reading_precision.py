import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from backend.archivereader.historical_reading import aligned_span
from backend.archivereader.review_corpus import model_suitability
from backend.archivereader.htr_compare import score
from tests import test_layout as layout_fixture

class ReadingPrecisionTests(unittest.TestCase):
 def test_alignment_preserves_diacritics_insertions_deletions_and_bounds(self):
  a=aligned_span('Jan Šimek natus','Jan Simek natus',4,9)
  self.assertEqual(a['text'],'Simek');self.assertFalse(a['pixel_geometry']);self.assertFalse(a['verified'])
  self.assertEqual(aligned_span('Jan Šimek natus','Jan natus',4,9)['status'],'deleted_or_unresolved')
  self.assertEqual(aligned_span('Jan Šimek natus','Jan de Simek natus',4,9)['text'],'de Simek')
  self.assertEqual(aligned_span('a '*601,'b',0,1)['status'],'limit')
 def test_book_suitability_shared_denominators_ties_and_failures(self):
  def row(book,a,b):return {'document':book,'results':{'A':{'score':score('Anna',a)},'B':{'score':score('Anna',b)}}}
  rows=[row('first','Anna','Anua'),row('second','Anna','Anna')]
  result=model_suitability(rows,['A','B']);self.assertEqual(result['books'][0]['lowest_observed_cer_model'],'A');self.assertIsNone(result['books'][1]['lowest_observed_cer_model']);self.assertTrue(result['books'][0]['small_sample']);self.assertFalse(result['automatic_activation'])
  rows.append({'document':'first','results':{'A':{'error':'failed'},'B':{'score':score('Anna','Anna')}}})
  self.assertIsNone(model_suitability(rows,['A','B'])['books'][0]['lowest_observed_cer_model'])
 def test_native_route_uses_worker_retains_raw_and_cli_custom_executable(self):
  fixture=layout_fixture.LayoutTests();fixture.setUp()
  try:
   l=fixture.layout;p=fixture.page['id'];ann=l.save_annotation({'page':p,'data':{'kind':'line','rect':[.1,.2,.5,.1],'text':'Manual'}})['id'];model=fixture.root/'model.mlmodel';model.write_bytes(b'fixture')
   args={'id':p,'annotation':ann,'model':str(model)}
   def native(source,model,output,*rest):Path(output).write_text('<alto><TextLine HPOS="0" VPOS="0" WIDTH="100" HEIGHT="30"><String CONTENT="Šimek"/></TextLine></alto>',encoding='utf-8')
   with patch.dict(os.environ,{'ARCHIVEREADER_MODEL_SESSION':'1'}),patch('backend.archivereader.recognizers.kraken_region',side_effect=native) as run,patch('backend.archivereader.layout.run_process',side_effect=AssertionError('CLI invoked')):
    first=l.recognize_region(args);cached=l.recognize_region(args);again=l.recognize_region(args|{'force':True});self.assertEqual(run.call_count,2);self.assertEqual(first['text'],'Šimek');self.assertTrue(cached['reused']);self.assertNotEqual(first['id'],again['id']);self.assertEqual(l.annotations({'id':p})[0]['text'],'Manual')
   with patch.dict(os.environ,{'ARCHIVEREADER_MODEL_SESSION':'1'}),patch('backend.archivereader.layout.run_process',side_effect=RuntimeError('custom CLI')):
    with self.assertRaisesRegex(RuntimeError,'custom CLI'):l.recognize_region(args|{'executable':'other-environment-kraken','force':True})
   with patch.dict(os.environ,{'ARCHIVEREADER_MODEL_SESSION':'1'}),patch('backend.archivereader.recognizers.kraken_region',side_effect=lambda source,model,output,*rest:Path(output).write_text('<alto/>',encoding='utf-8')):
    empty=l.recognize_region(args|{'force':True});self.assertEqual(empty['review_flags'],['no_readable_lines']);self.assertFalse(empty['verified'])
  finally:fixture.tearDown()

if __name__=='__main__':unittest.main()
