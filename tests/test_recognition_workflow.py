import json,unittest
from unittest.mock import patch
from tests import test_layout as fixtures
from backend.archivereader.recognition_workflow import RecognitionWorkflow,review_flags
from backend.archivereader.tutor import TutorTools

class WorkflowTests(unittest.TestCase):
 def setUp(self):self.f=fixtures.LayoutTests();self.f.setUp();self.tools=RecognitionWorkflow(self.f.engine)
 def tearDown(self):self.f.tearDown()
 def test_advisory_flags_never_change_literal_text(self):
  literal='10.1937 '*12;flags=review_flags(literal,{'house':'1937'})
  self.assertIn('repeated_text',flags);self.assertIn('check_dates_numbers',flags);self.assertIn('check_house',flags)
  self.assertEqual(review_flags(''),['empty_output']);self.assertEqual(review_flags('Marianna',{'person':'Marianna'}),['check_person'])
 def test_shared_status_preserves_references_and_test_role_without_inference(self):
  page=self.f.page['id'];tutor=TutorTools(self.f.engine);tutor.tutor_save({'id':page,'rect':[.1,.1,.5,.1],'text':'Anno 1847','verified':True});tutor.tutor_role({'id':page,'role':'test'})
  before=self.f.engine.page(page)
  with patch.object(self.f.engine,'recognize',side_effect=AssertionError('No inference')):state=self.tools.workflow_status({'id':page})
  self.assertEqual(state['examples']['confirmed'],1);self.assertEqual(state['split'],'test');self.assertEqual(self.f.engine.page(page),before)
  self.assertEqual(state['capabilities']['paddle']['training'],'export_only');self.assertEqual(state['capabilities']['kraken']['training'],'kraken_copy')
 def test_missing_dependencies_do_not_claim_readiness_or_book_validation(self):
  model=self.f.root/'model.mlmodel';model.write_bytes(b'fixture')
  with patch('importlib.util.find_spec',return_value=None):status=self.tools.workflow_model_status({'model':str(model),'engine':'kraken'})
  self.assertTrue(status['installed']);self.assertFalse(status['configured']);self.assertEqual(status['book_validation'],'not_assessed_here')
 def test_modern_comparison_routes_each_crop_without_loading_legacy_model(self):
  from backend.archivereader.htr_compare import kraken_lines
  with patch('backend.archivereader.recognizers.kraken_region',side_effect=[[{'text':'Jan'}],RuntimeError('failed')]):
   result=list(kraken_lines('medium.safetensors',['one.png','two.png']))
  self.assertEqual(result[0],{'text':'Jan'});self.assertEqual(result[1],{'error':'failed'})
