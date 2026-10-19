from tests.support import workspace_tempdir
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from backend.archivereader.engine import Engine
from backend.archivereader.agents import AgentTools


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp=workspace_tempdir();self.root=Path(self.temp.name);self.engine=Engine(self.root/'library')
        source=self.root/'image.png';Image.new('RGB',(400,200),'white').save(source)
        self.engine.import_file({'path':str(source)});self.page=self.engine.list_pages({})[0]['id'];self.tools=AgentTools(self.engine)
        self.region=self.tools.save_annotation({'page':self.page,'data':{'kind':'line','rect':[.1,.1,.8,.2],'text':'','verified':False}})['id']
        self.models=[]
        for i in range(2):
            path=self.root/f'model{i}.mlmodel';path.write_bytes(bytes([i]));self.models.append({'name':str(i),'engine':'kraken','path':str(path)})
    def tearDown(self):self.engine.db.close();self.temp.cleanup()
    def create(self):return self.tools.agent_create({'page':self.page,'annotation':self.region,'models':self.models})['id']
    def test_persistent_steps_feedback_never_changes_source(self):
        job=self.create();self.assertEqual(self.tools.agent_step({'job':job})['state'],'recognition')
        report={'rows':[{'id':self.region,'results':{'0':{'text':'Jan'},'1':{'text':'Jan'}}}],'models':self.models}
        with patch.object(self.tools,'compare_regions',return_value=report):self.assertEqual(self.tools.agent_step({'job':job})['state'],'comparison')
        result=self.tools.agent_step({'job':job});self.assertEqual(result['state'],'review');self.assertFalse(result['verified'])
        self.assertEqual(AgentTools(self.engine).agent_jobs({'page':self.page})[0]['id'],job)
        with self.assertRaises(ValueError):self.tools.agent_review({'job':job,'text':'Jan'})
        result=self.tools.agent_review({'job':job,'text':'Jan','checked':True});self.assertEqual(result['state'],'complete')
        self.assertFalse(self.tools.annotations({'id':self.page})[0]['verified']);self.assertEqual(self.tools.annotations({'id':self.page})[0]['text'],'')
        self.assertEqual(len(self.tools.agent_history({'job':job})),5)
    def test_stale_region_and_changed_model_block(self):
        job=self.create();self.tools.agent_step({'job':job});Path(self.models[0]['path']).write_text('changed')
        self.assertEqual(self.tools.agent_step({'job':job})['state'],'failed')
        self.tools.save_annotation({'page':self.page,'annotation':self.region,'data':{'kind':'line','rect':[.2,.1,.7,.2],'text':'','verified':False}})
        with self.assertRaises(ValueError):self.tools.agent_step({'job':job})
    def test_failure_and_cancel_are_persisted(self):
        job=self.create();self.tools.agent_step({'job':job})
        with patch.object(self.tools,'compare_regions',side_effect=RuntimeError('model failed')):self.assertEqual(self.tools.agent_step({'job':job})['error'],'model failed')
        self.assertEqual(self.tools.agent_cancel({'job':job})['state'],'cancelled');self.assertEqual(self.tools.agent_step({'job':job})['state'],'cancelled')
    def test_failed_second_model_is_not_agreement_and_raw_is_retained(self):
        job=self.create();self.tools.agent_step({'job':job})
        report={'rows':[{'id':self.region,'results':{'0':{'text':'Jan'},'1':{'error':'out of memory'}}}],'models':self.models}
        with patch.object(self.tools,'compare_regions',return_value=report):self.tools.agent_step({'job':job})
        result=self.tools.agent_step({'job':job});row=result['stages']['comparison'][0]
        self.assertEqual(row['ensemble']['status'],'review_required');self.assertIsNone(row['ensemble']['consensus_text']);self.assertEqual(row['results']['1']['error'],'out of memory')

if __name__=='__main__':unittest.main()

