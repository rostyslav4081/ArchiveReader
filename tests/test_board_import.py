import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from backend.archivereader.engine import Engine
from backend.archivereader.board_import import BoardTools


class BoardImportTests(unittest.TestCase):
    def setUp(self):
        output=Path(__file__).resolve().parents[1]/"test-output";output.mkdir(exist_ok=True);self.temp=tempfile.TemporaryDirectory(dir=output);self.root=Path(self.temp.name);self.engine=Engine(self.root/'library');self.tools=BoardTools(self.engine)
        self.snapshot={'fileKey':'test','pageId':'0:1','nodes':[{'id':'p','type':'SHAPE_WITH_TEXT','text':'Jan\n1832-?','x':1,'y':2,'images':[]},{'id':'note','type':'TEXT','text':'Surname correction','x':4,'y':6},{'id':'edge','type':'CONNECTOR','start':{'endpointNodeId':'p'},'end':{'position':{'x':100,'y':40}}}]}
        self.path=self.root/'board.json';self.path.write_text(json.dumps(self.snapshot),encoding='utf-8');self.args={'path':str(self.path),'people':['p']};self.args['sha']=self.tools.board_preview(self.args)['sha']
    def tearDown(self):self.engine.db.close();self.temp.cleanup()
    def test_lossless_pending_idempotent_reopen(self):
        result=self.tools.board_import(self.args);self.assertEqual(self.snapshot,result['snapshot']);self.assertEqual(1,len(result['persons']));self.assertEqual([],self.tools.family_list({}));person=self.tools.require_person(result['persons']['p']);self.assertEqual('Jan\n1832-?',person['notes']);self.assertEqual([],person['events']);self.assertTrue(person['unverified_import']);self.assertTrue(self.tools.board_import(self.args)['already_imported']);self.assertEqual(1,len(self.tools.person_list({})))
        self.engine.db.close();self.engine=Engine(self.root/'library');self.tools=BoardTools(self.engine);self.assertEqual(self.snapshot,self.tools.board_get({'id':result['id']})['snapshot'])
    def test_reject_changed_mapping_or_snapshot(self):
        self.tools.board_import(self.args)
        with self.assertRaises(ValueError):self.tools.board_import(self.args|{'people':['p','note']})
        self.snapshot['nodes'].pop();self.path.write_text(json.dumps(self.snapshot));self.args['sha']=self.tools.board_preview(self.args)['sha']
        with self.assertRaises(ValueError):self.tools.board_import(self.args)
        self.assertEqual(1,len(self.tools.person_list({})))
    def test_asset_integrity_and_export(self):
        image=self.root/'image.png';Image.new('RGB',(12,15),'red').save(image);raw=image.read_bytes();asset={'node':'p','path':str(image),'kind':'source','sha256':hashlib.sha256(raw).hexdigest()};manifest=self.root/'assets.json';manifest.write_text(json.dumps([asset]));args=self.args|{'assets':str(manifest)};result=self.tools.board_import(args);export=self.tools.board_get({'id':result['id'],'export':str(self.root/'export')});self.assertEqual(raw,Path(export['assets'][0]['path']).read_bytes());self.assertEqual(self.path.read_bytes(),(self.root/'export/board.json').read_bytes());self.assertTrue(self.tools.board_import(args)['already_imported'])
        with self.assertRaises(ValueError):self.tools.board_import(self.args)
        image.write_bytes(b'broken')
        with self.assertRaises(ValueError):self.tools.board_import(args)

    def test_empty_attachment_rejected_before_any_card_is_written(self):
        image=self.root/'empty.png';image.write_bytes(b'');manifest=self.root/'assets.json';manifest.write_text(json.dumps([{'node':'p','path':str(image),'sha256':hashlib.sha256(b'').hexdigest()}]))
        with self.assertRaises(ValueError):self.tools.board_import(self.args|{'assets':str(manifest)})
        self.assertEqual([],self.tools.person_list({}));self.assertEqual([],self.tools.board_list({}))

    def test_matching_names_are_separate_people_and_notes_stay_raw(self):
        self.snapshot['nodes'].append({'id':'p2','type':'SHAPE_WITH_TEXT','text':'Jan\nDifferent relative'})
        self.path.write_text(json.dumps(self.snapshot));args=self.args|{'people':['p','p2']};args['sha']=self.tools.board_preview(args)['sha'];result=self.tools.board_import(args)
        self.assertEqual(2,len(set(result['persons'].values())));self.assertEqual(['Jan','Jan'],[p['name'] for p in self.tools.person_list({})]);self.assertEqual(self.snapshot,result['snapshot'])

    def semantics(self,result,colors):
        source={'fileKey':'test','pageId':'0:1','legend':{'red':'incorrect','yellow':'unresolved','other':'logically_consistent'},'connectors':[{'id':key,'strokes':[{'type':'SOLID','color':dict(zip(['r','g','b'],color))}]} for key,color in colors.items()]};path=self.root/'semantics.json';path.write_text(json.dumps(source));return {'id':result['id'],'expected_sha':result['sha'],'path':str(path)}

    def test_semantics_classification_preserves_original_and_exports(self):
        self.snapshot['nodes'] += [{'id':i,'type':'CONNECTOR'} for i in ['yellow','grey']];self.path.write_text(json.dumps(self.snapshot));self.args['sha']=self.tools.board_preview(self.args)['sha'];result=self.tools.board_import(self.args)
        args=self.semantics(result,{'edge':(1,.1,.1),'yellow':(1,.8,.1),'grey':(.7,.7,.7)});updated=self.tools.board_set_semantics(args);states=updated['semantics']['connectors'];self.assertEqual(['incorrect','unresolved','logically_consistent'],[states[k]['status'] for k in ['edge','yellow','grey']]);self.assertTrue(all(not s['archive_verified'] for s in states.values()));self.assertEqual(result['sha'],updated['sha']);self.assertEqual(result['snapshot'],updated['snapshot']);self.assertTrue(self.tools.board_import(self.args)['already_imported']);self.assertEqual(1,self.tools.board_set_semantics(args)['semantics']['revision']);self.tools.board_get({'id':result['id'],'export':str(self.root/'export')});self.assertTrue((self.root/'export/connector-semantics.json').exists())

    def test_semantics_reject_wrong_snapshot_or_missing_edges(self):
        result=self.tools.board_import(self.args);args=self.semantics(result,{'edge':(1,0,0)})
        with self.assertRaises(ValueError):self.tools.board_set_semantics(args|{'expected_sha':'wrong'})
        args=self.semantics(result,{})
        with self.assertRaises(ValueError):self.tools.board_set_semantics(args)
        self.assertNotIn('semantics',self.tools.board_get({'id':result['id']}))

    def test_manual_semantics_override_requires_reason_and_keeps_history(self):
        result=self.tools.board_import(self.args);self.tools.board_set_semantics(self.semantics(result,{'edge':(.7,.7,.7)}));args={'id':result['id'],'expected_sha':result['sha'],'expected_revision':1,'overrides':[{'connector':'edge','status':'incorrect','reason':''}]}
        with self.assertRaises(ValueError):self.tools.board_set_semantics(args)
        args['overrides'][0]['reason']='Different person in the linked birth image';updated=self.tools.board_set_semantics(args);self.assertEqual(2,updated['semantics']['revision']);self.assertEqual('manual_override',updated['semantics']['connectors']['edge']['origin']);self.assertEqual(2,self.engine.db.execute('select count(*) from board_semantics_history').fetchone()[0])
        with self.assertRaises(ValueError):self.tools.board_set_semantics(args)
