import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch
from PIL import Image
from backend.archivereader.engine import Engine
from backend.archivereader.recognizers import RecognizerTools,model_metadata
from backend.archivereader.htr_compare import ensemble_vote


class RecognizerTests(unittest.TestCase):
    def test_safetensors_page_uses_modern_adapter_and_retains_geometry(self):
        from backend.archivereader.recognizers import kraken_page
        expected=[{'text':'Český','box':[1,2,30,8],'confidence':.8}]
        with patch('backend.archivereader.recognizers.kraken_region',return_value=expected) as run:
            self.assertEqual(kraken_page('scan.png','medium.safetensors',alto_path='result.xml'),expected)
            self.assertEqual(run.call_args.args,('scan.png','medium.safetensors','result.xml',None))
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'test-output');self.root=Path(self.tmp.name);self.engine=Engine(self.root/'library')
        source=self.root/'image.png';Image.new('RGB',(100,100),'white').save(source);self.engine.import_file({'path':str(source)});self.page=self.engine.list_pages({})[0]['id']
    def tearDown(self):self.engine.db.close();self.tmp.cleanup()

    def test_ensemble_never_promotes_agreement_to_ground_truth(self):
        models=[{'name':'A','engine':'kraken'},{'name':'B','engine':'trocr'}]
        same=ensemble_vote({'A':{'text':'Šimek'},'B':{'text':'Šimek'}},models)
        self.assertEqual(same['status'],'agreed_unverified');self.assertFalse(same['verified']);self.assertEqual(same['consensus_text'],'Šimek')
        disagree=ensemble_vote({'A':{'text':'Šimek'},'B':{'text':'Simek'}},models)
        self.assertEqual(disagree['status'],'review_required');self.assertIsNone(disagree['consensus_text']);self.assertEqual(len(disagree['options']),2)
        failed=ensemble_vote({'A':{'text':'Šimek'},'B':{'error':'failed'}},models)
        self.assertEqual(failed['status'],'review_required');self.assertEqual(failed['failures'],['B'])

    def test_model_metadata_preserves_modern_rectangular_contract(self):
        folder=self.root/'model';folder.mkdir();(folder/'config.json').write_text(json.dumps({'model_type':'vision-encoder-decoder'}));(folder/'processor_config.json').write_text(json.dumps({'image_processor':{'size':{'height':192,'width':1024}}}))
        result=model_metadata(folder);self.assertEqual(result['engine'],'trocr');self.assertEqual(result['input_size'],{'height':192,'width':1024});self.assertIsNone(result['alphabet'])

    def test_metadata_cache_is_invalidated_by_changed_model(self):
        model=self.root/'model.mlmodel';model.write_bytes(b'first')
        tools=RecognizerTools(self.engine)
        with patch('backend.archivereader.recognizers.model_metadata',return_value={'engine':'kraken','alphabet':'abc'}) as load:
            first=tools.model_inspect({'model':str(model)});self.assertEqual(first,tools.model_inspect({'model':str(model)}));self.assertEqual(load.call_count,1)
            model.write_bytes(b'second model');second=tools.model_inspect({'model':str(model)});self.assertNotEqual(first['identity'],second['identity']);self.assertEqual(load.call_count,2)

    def test_whole_page_trocr_dispatch_retains_boxes_and_correction_guard(self):
        folder=self.root/'trocr';folder.mkdir()
        with patch('backend.archivereader.recognizers.trocr_page',return_value=[{'text':'Wieś Lipowce','box':[10,20,60,10],'confidence':None}]):
            self.engine.recognize({'id':self.page,'engine':'trocr','model':str(folder)})
        page=self.engine.details({'id':self.page});self.assertEqual(page['engine'],'trocr');self.assertEqual(page['lines'][0]['box'],[10,20,60,10])
        self.engine.save_line({'id':self.page,'line':0,'text':'Corrected','verified':True})
        with self.assertRaises(ValueError):self.engine.recognize({'id':self.page,'engine':'trocr','model':str(folder),'force':True})

    def test_new_workflows_registered_through_actual_worker(self):
        worker=Path(__file__).resolve().parents[1]/'backend/archivereader/engine.py'
        for command,args in [('tutor_lessons',{'id':self.page}),('agent_jobs',{'page':self.page}),('board_list',{}),('candidate_list',{})]:
            request={'root':str(self.engine.root),'command':command}|args
            result=subprocess.run([sys.executable,'-X','utf8',str(worker)],input=json.dumps(request),capture_output=True,text=True,encoding='utf8',check=True)
            self.assertTrue(json.loads(result.stdout)['ok'],command+': '+result.stdout)


if __name__=='__main__':unittest.main()
