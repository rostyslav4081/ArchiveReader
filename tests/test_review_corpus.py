import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image,ImageDraw
from backend.archivereader.engine import Engine
from backend.archivereader.review_corpus import CorpusTools


class ReviewCorpusTests(unittest.TestCase):
    def setUp(self):
        folder=Path(__file__).resolve().parents[1]/'test-output';folder.mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=folder);self.root=Path(self.tmp.name);self.engine=Engine(self.root/'library');self.tools=CorpusTools(self.engine)
        im=Image.new('RGB',(200,150),'white');ImageDraw.Draw(im).rectangle((20,30,170,70),fill='black');f=self.root/'sample.png';im.save(f);self.engine.import_file({'path':str(f)});self.page=self.engine.list_pages({})[0]['id']
        self.annotation=self.tools.save_annotation({'page':self.page,'data':{'kind':'entry','rect':[.1,.1,.8,.6],'text':'assistant draft','verified':True}})['id']
        self.models=[{'name':'A','engine':'kraken','path':str(self.root/'a.mlmodel')},{'name':'B','engine':'trocr','path':str(self.root/'b')}]
        (self.root/'a.mlmodel').write_bytes(b'distinct synthetic model A')
        (self.root/'b').mkdir();(self.root/'b/model.safetensors').write_bytes(b'distinct synthetic model B')
    def tearDown(self):self.engine.db.close();self.tmp.cleanup()
    def imported(self):self.tools.corpus_import({'id':self.page});return self.tools.corpus_list({})[0]
    def confirmed(self,text='Alpha beta',**kwargs):
        row=self.imported();self.tools.corpus_save({'reference':row['id'],'revision':row['revision'],'text':text,'human_verified':True,'single_block':True}|kwargs);return self.tools.corpus_list({})[0]

    def test_field_metrics_require_explicit_confirmation_and_count_missing_failed_predictions(self):
        row=self.confirmed(fields={'person':'Anna','date':'1826-01-28','house':'2'},fields_verified=True)
        frozen=self.tools.corpus_freeze({});args={'path':frozen['path'],'expected_manifest_sha256':frozen['manifest_sha256'],'model':{'name':'Synthetic predictions, no model inference'}}
        result=self.tools.corpus_score_fields(args|{'predictions':[{'id':row['id'],'fields':{'person':'Anna','date':'1826-01-29'}}]})
        self.assertEqual(result['metrics']['person']['exact_rate_all_references'],1)
        self.assertEqual(result['metrics']['date']['exact'],0)
        self.assertEqual(result['metrics']['house']['missing'],1)
        self.assertEqual(result['metrics']['house']['exact_rate_all_references'],0)
        failure=self.tools.corpus_score_fields(args|{'predictions':[{'id':row['id'],'error':'Recognizer failed'}]})
        self.assertEqual(failure['metrics']['person']['failed'],1);self.assertEqual(failure['metrics']['person']['scored'],0)
        missing=self.tools.corpus_score_fields(args|{'predictions':[]})
        self.assertEqual(missing['metrics']['person']['missing'],1)
        with self.assertRaises(ValueError):self.tools.corpus_score_fields(args|{'expected_manifest_sha256':'stale','predictions':[]})
        with self.assertRaises(ValueError):self.tools.corpus_score_fields(args|{'predictions':[{'id':'unknown','fields':{}}]})
        self.tools.save_annotation({'page':self.page,'annotation':self.annotation,'data':{'kind':'entry','rect':[.1,.1,.7,.6],'text':'changed'}})
        with self.assertRaises(ValueError):self.tools.corpus_score_fields(args|{'predictions':[]})

    def test_unconfirmed_fields_are_not_frozen_or_scored_and_edits_reset_confirmation(self):
        row=self.confirmed(fields={'person':'Anna'},fields_verified=False)
        frozen=self.tools.corpus_freeze({});self.assertNotIn('fields',json.loads((Path(frozen['path'])/'manifest.json').read_text())[0])
        with self.assertRaises(ValueError):self.tools.corpus_score_fields({'path':frozen['path'],'expected_manifest_sha256':frozen['manifest_sha256'],'model':{'name':'test'},'predictions':[]})
        saved=self.tools.corpus_save({'reference':row['id'],'revision':row['revision'],'text':'Anna','single_block':True,'human_verified':True,'fields':{'person':'Anna'},'fields_verified':True})
        saved=self.tools.corpus_save({'reference':row['id'],'revision':saved['revision'],'text':'Changed text','single_block':True,'human_verified':True})
        self.assertFalse(saved['fields_verified'])
        with self.assertRaises(ValueError):self.tools.corpus_save({'reference':row['id'],'revision':saved['revision'],'text':'Anna','single_block':True,'human_verified':False,'fields':{'person':'Anna'},'fields_verified':True})

    def test_import_is_draft_and_assigns_test_without_promoting_annotation(self):
        row=self.imported();self.assertFalse(row['human_verified']);self.assertEqual(row['excluded'],'draft');self.assertEqual(self.tools.book_profile({'id':self.page})['split'],'test')
        self.assertFalse(self.tools.annotations({'id':self.page})[0]['verified'])
        self.assertEqual(self.tools.corpus_import({'id':self.page})['unchanged'],1)
        with self.assertRaises(ValueError):self.tools.corpus_freeze({})

    def test_train_family_is_rejected_and_existing_split_preserved(self):
        derivative=self.tools.prepare_photo({'id':self.page,'mode':'rotate','angle':5})
        original=self.engine.page(self.page)['doc']
        with self.engine.db:self.engine.db.execute('INSERT OR REPLACE INTO book_profiles VALUES (?,?)',(original,json.dumps({'split':'train'})))
        with self.assertRaises(ValueError):self.tools.corpus_import({'id':self.page})
        self.assertEqual(self.tools.corpus_list({}),[]);self.assertEqual(self.tools.book_profile({'id':self.page})['split'],'train')

    def test_verification_requires_reading_order_and_excludes_uncertainty_damage(self):
        row=self.imported()
        args={'reference':row['id'],'revision':row['revision'],'text':'Alpha beta','human_verified':True}
        with self.assertRaises(ValueError):self.tools.corpus_save(args)
        with self.assertRaises(ValueError):self.tools.corpus_save(args|{'single_block':True,'text':'Alpha [illegible]'})
        self.confirmed();self.tools.save_annotation({'page':self.page,'data':{'kind':'damage','rect':[.2,.2,.1,.1]}})
        self.assertEqual(self.tools.corpus_list({})[0]['excluded'],'damaged')
        with self.assertRaises(ValueError):self.tools.corpus_freeze({})

    def test_revision_and_changed_entry_invalidate_reference(self):
        row=self.confirmed();self.assertEqual(len(self.tools.corpus_history({'reference':row['id']})),2)
        with self.assertRaises(ValueError):self.tools.corpus_save({'reference':row['id'],'revision':'wrong','text':'bad'})
        self.tools.save_annotation({'page':self.page,'annotation':self.annotation,'data':{'kind':'entry','rect':[.1,.1,.7,.6],'text':'changed'}})
        self.assertEqual(self.tools.corpus_list({})[0]['excluded'],'source_changed')
        self.tools.corpus_import({'id':self.page});row=self.tools.corpus_list({})[0];self.assertFalse(row['human_verified']);self.assertEqual(row['text'],'Alpha beta')

    def test_frozen_entry_does_not_follow_later_reference_edit_and_hashes_guard_it(self):
        row=self.confirmed();snapshot=self.tools.corpus_freeze({});folder=Path(snapshot['path']);manifest=folder/'manifest.json';frozen=json.loads(manifest.read_text('utf-8'))
        self.tools.corpus_save({'reference':row['id'],'revision':row['revision'],'text':'Later reference','single_block':True,'human_verified':True})
        self.assertEqual(frozen[0]['text'],'Alpha beta');self.assertEqual(hashlib.sha256(manifest.read_bytes()).hexdigest(),snapshot['manifest_sha256'])
        manifest.write_text('[]',encoding='utf-8')
        with self.assertRaises(ValueError):self.tools.corpus_compare({'path':str(folder),'models':self.models})

    def test_shared_segments_and_whole_entry_scoring_count_model_failure(self):
        self.confirmed();snapshot=self.tools.corpus_freeze({})
        def fake_compare(manifest,models,folder):
            cases=json.loads(Path(manifest).read_text('utf-8'));self.assertEqual(len(cases),2);self.assertTrue(all('reference' not in r for r in cases))
            return {'models':[{'name':'A','seconds_including_model_load':1},{'name':'B','seconds_including_model_load':2}], 'rows':[r|{'results':{'A':{'text':word},'B':{'error':'recognizer failed'} if i else {'text':word}}} for i,(r,word) in enumerate(zip(cases,['Alpha','beta']))]}
        with patch('backend.archivereader.review_corpus.segment_entry',return_value=[[0,0,1,.45],[0,.5,1,.45]]) as segmentation, patch('backend.archivereader.review_corpus.compare',side_effect=fake_compare):
            result=self.tools.corpus_compare({'path':snapshot['path'],'models':self.models})
        self.assertEqual(segmentation.call_count,1);self.assertEqual(result['models'][0]['micro_cer'],0);self.assertEqual(result['models'][0]['micro_wer'],0)
        self.assertEqual(result['models'][1]['failed_entries'],1);self.assertIsNone(result['models'][1]['micro_cer']);self.assertEqual(result['common_entries'],0)
        self.assertTrue((Path(result['path'])/'entry-report.json').exists())

    def test_manual_order_is_frozen_and_automatic_segmentation_not_used(self):
        for order,rect in [(2,[.2,.4,.6,.1]),(1,[.2,.2,.6,.1])]:self.tools.save_annotation({'page':self.page,'data':{'kind':'line','rect':rect,'parent':self.annotation,'reading_order':order,'text':'','verified':False}})
        self.confirmed(single_block=False);snapshot=self.tools.corpus_freeze({});rows=json.loads((Path(snapshot['path'])/'manifest.json').read_text('utf-8'))
        self.assertEqual(rows[0]['reading_policy'],'manual');self.assertLess(rows[0]['reading_regions'][0][1],rows[0]['reading_regions'][1][1])
        def fake(manifest,models,folder):return {'models':[],'rows':[r|{'results':{'A':{'text':'Alpha' if i==0 else 'beta'},'B':{'text':'Alpha' if i==0 else 'beta'}}} for i,r in enumerate(json.loads(Path(manifest).read_text('utf-8')))]}
        with patch('backend.archivereader.review_corpus.segment_entry',side_effect=AssertionError('must not segment')),patch('backend.archivereader.review_corpus.compare',side_effect=fake):r=self.tools.corpus_compare({'path':snapshot['path'],'models':self.models})
        self.assertEqual(r['common_entries'],1);self.assertEqual(r['models'][1]['common_cer'],0)

    def test_changed_frozen_image_rejected_before_models_run(self):
        self.confirmed();snapshot=self.tools.corpus_freeze({});image=next(Path(snapshot['path']).glob('*.png'));image.write_bytes(b'changed')
        with patch('backend.archivereader.review_corpus.compare',side_effect=AssertionError('must not run')):
            with self.assertRaises(ValueError):self.tools.corpus_compare({'path':snapshot['path'],'models':self.models})

    def test_copied_weights_at_different_paths_are_not_independent_models(self):
        self.confirmed();snapshot=self.tools.corpus_freeze({})
        copy=self.root/'renamed-copy.safetensors';copy.write_bytes((self.root/'a.mlmodel').read_bytes())
        models=[self.models[0],{'name':'B','engine':'kraken','path':str(copy)}]
        with patch('backend.archivereader.review_corpus.compare',side_effect=AssertionError('must not run')):
            with self.assertRaises(ValueError):self.tools.corpus_compare({'path':snapshot['path'],'models':models})
        # Folder metadata and different weight filenames do not hide a copy.
        (self.root/'b/model.safetensors').write_bytes((self.root/'a.mlmodel').read_bytes())
        (self.root/'b/config.json').write_text('{"different":"metadata"}',encoding='utf-8')
        with patch('backend.archivereader.review_corpus.compare',side_effect=AssertionError('must not run')):
            with self.assertRaises(ValueError):self.tools.corpus_compare({'path':snapshot['path'],'models':self.models})

if __name__=='__main__':unittest.main()
