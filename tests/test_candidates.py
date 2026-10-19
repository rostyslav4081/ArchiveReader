import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from backend.archivereader.engine import Engine
from backend.archivereader.candidate_models import CandidateTools,candidate_verdict

def scored(a,b):
    return {'results':{name:{'text':'text','score':{'characters':10,'character_errors':errors}} for name,errors in [('base',a),('candidate',b)]}}

class CandidateTests(unittest.TestCase):
    def test_common_success_denominator_and_failures(self):
        self.assertEqual(candidate_verdict([scored(4,2)])['status'],'improved')
        self.assertEqual(candidate_verdict([scored(2,2)])['status'],'rejected')
        self.assertEqual(candidate_verdict([{'results':{'base':{'text':'a'},'candidate':{'error':'failed'}}}])['status'],'inconclusive')
        result=candidate_verdict([scored(4,2),{'results':{'base':{'text':'a'},'candidate':{'error':'failed'}}}])
        self.assertEqual(result['status'],'rejected');self.assertEqual(result['characters'],10);self.assertFalse(result['promoted'])
    def test_train_and_heldout_check_keeps_base_and_persists(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'test-output') as temp:
            root=Path(temp);engine=Engine(root/'library');tools=CandidateTools(engine);base=root/'base.mlmodel';base.write_bytes(b'base');candidate=root/'candidate.safetensors';candidate.write_bytes(b'candidate')
            frozen=root/'frozen';frozen.mkdir();run=root/'run';(run/'dataset').mkdir(parents=True)
            rows=[{'document':role,'split':role,'text':'human','image_sha256':role} for role in ['train','validation','test']]
            for folder in [frozen,run/'dataset']:(folder/'manifest.json').write_text(json.dumps(rows),encoding='utf8')
            inventory=[{'split':role,'verified_lines':1} for role in ['train','validation','test']]
            with patch.object(tools,'benchmark_inventory',return_value=inventory),patch.object(tools,'benchmark_freeze',return_value={'path':str(frozen),'train':1,'validation':1,'test':1}),patch.object(tools,'document_family',side_effect=lambda doc:{doc}),patch.object(engine,'train_model',return_value={'path':str(run),'models':[str(candidate)]}) as train,patch.object(tools,'benchmark_compare',return_value={'rows':[scored(4,1)]}) as compare:
                result=tools.candidate_train_check({'model':str(base),'epochs':1})
                self.assertEqual(result['status'],'improved');self.assertFalse(result['promoted']);self.assertEqual(base.read_bytes(),b'base');self.assertTrue(train.call_args.args[0]['explicit']);self.assertEqual(compare.call_args.args[0]['path'],str(frozen));self.assertEqual(tools.candidate_list({})[0]['id'],result['id'])
            (run/'dataset'/'manifest.json').write_text(json.dumps([r|{'text':'changed'} for r in rows]),encoding='utf8')
            with patch.object(tools,'benchmark_inventory',return_value=inventory),patch.object(tools,'benchmark_freeze',return_value={'path':str(frozen),'train':1,'validation':1,'test':1}),patch.object(tools,'document_family',side_effect=lambda doc:{doc}),patch.object(engine,'train_model',return_value={'path':str(run),'models':[str(candidate)]}),patch.object(tools,'benchmark_compare') as compare:
                self.assertEqual(tools.candidate_train_check({'model':str(base)})['status'],'failed');compare.assert_not_called()
            with patch.object(tools,'benchmark_inventory',return_value=inventory),patch.object(tools,'benchmark_freeze',return_value={'path':str(frozen),'train':1,'validation':1,'test':1}),patch.object(tools,'document_family',return_value={'train','test'}),patch.object(engine,'train_model') as train:
                with self.assertRaises(ValueError):tools.candidate_train_check({'model':str(base)})
                train.assert_not_called()
            with patch.object(tools,'benchmark_inventory',return_value=[]),patch.object(engine,'train_model') as train:
                result=tools.candidate_train_check({'model':str(base)});self.assertEqual(result['status'],'preflight_failed');train.assert_not_called()
            engine.db.close()
