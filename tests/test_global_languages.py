import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from backend.archivereader.global_languages import GlobalLanguagesTools,load_registry

class GlobalLanguagesTests(unittest.TestCase):
 def setUp(self):self.tools=GlobalLanguagesTools()
 def test_real_catalog_identifiers_historical_languages_provenance_and_paging(self):
  allrows=self.tools.historical_languages({});self.assertEqual(allrows['total'],27177);self.assertEqual(len(allrows['rows']),25);self.assertTrue(allrows['has_more']);self.assertEqual(len(allrows['dataset']['commit_sha']),40);self.assertEqual(len(allrows['dataset']['source_file_sha256']),64);self.assertEqual(allrows['dataset']['license'],'CC-BY-4.0');self.assertIn('5.2.1',allrows['dataset']['notes'])
  latin=self.tools.historical_languages({'query':'lati1261'});self.assertEqual(latin['rows'][0]['iso'],'lat');self.assertEqual(latin['rows'][0]['name'],'Latin');self.assertEqual(latin['rows'][0]['resource_url'],'https://glottolog.org/resource/languoid/id/lati1261');self.assertTrue(any(r['iso']=='grc' for r in self.tools.historical_languages({'query':'grc'})['rows']))
  second=self.tools.historical_languages({'offset':25});self.assertNotEqual(allrows['rows'],second['rows']);self.assertEqual(self.tools.historical_languages({'offset':27177})['rows'],[]);self.assertFalse(self.tools.historical_languages({'offset':27177})['has_more']);self.assertNotIn('model',latin['rows'][0]);self.assertNotIn('verified',latin['rows'][0])
 def test_unicode_name_query_is_preserved_without_translation(self):
  data={'rows':[{'id':'test1234','glottocode':'test1234','iso':'','name':'Українська','level':'language'}],'dataset':{'scope':'fixture'}}
  with patch('backend.archivereader.global_languages.load_registry',return_value=(data,[(data['rows'][0],'test1234 українська language')])):
   self.assertEqual(self.tools.historical_languages({'query':'УКРАЇНСЬКА'})['total'],1)
 def test_invalid_queries_and_broken_catalog_rejected(self):
  for args in [{'query':[]},{'query':'x'*201},{'query':'name\ntext'},{'limit':True},{'limit':101},{'offset':-1},{'offset':100001}]:
   with self.subTest(args=args),self.assertRaises(ValueError):self.tools.historical_languages(args)
  with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'test-output') as tmp:
   p=Path(tmp)/'registry.json'
   for value in ['invalid',json.dumps({'version':2,'rows':[]}),json.dumps({'version':1,'dataset':{},'rows':[{'id':'a'}]})]:
    p.write_text(value,encoding='utf-8')
    with self.assertRaisesRegex(ValueError,'каталог мов'):load_registry(p)
 def test_caller_mutation_does_not_change_cached_catalog(self):
  found=self.tools.historical_languages({'query':'lati1261'});found['rows'][0]['name']='tampered';found['dataset']['license']='tampered';new=self.tools.historical_languages({'query':'lati1261'});self.assertEqual(new['rows'][0]['name'],'Latin');self.assertEqual(new['dataset']['license'],'CC-BY-4.0')

if __name__=='__main__':unittest.main()
