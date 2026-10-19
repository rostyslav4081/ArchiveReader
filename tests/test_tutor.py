from tests.support import workspace_tempdir
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from backend.archivereader.engine import Engine
from backend.archivereader.tutor import TutorTools


class TutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=workspace_tempdir()
        self.root=Path(self.tmp.name)
        self.engine=Engine(self.root/'library')
        source=self.root/'sample.png';Image.new('RGB',(100,100),'white').save(source)
        self.engine.import_file({'path':str(source)})
        self.page=self.engine.list_pages({})[0]['id'];self.tutor=TutorTools(self.engine)
    def tearDown(self):
        self.engine.db.close();self.tmp.cleanup()
    def save(self,**kw):
        return self.tutor.tutor_save({'id':self.page,'rect':[.1,.1,.7,.2],'text':'Human reference','verified':True}|kw)

    def test_human_revision_history_and_external_annotation_edits(self):
        lesson=self.save();self.assertFalse(lesson['weights_changed'])
        rows=self.tutor.tutor_lessons({'id':self.page});self.assertFalse(rows[0]['stale'])
        new=self.save(lesson=lesson['id'],revision=lesson['revision'],text='Human correction')
        self.assertEqual(len(self.tutor.tutor_history({'lesson':lesson['id']})),2)
        with self.assertRaises(ValueError):self.save(lesson=lesson['id'],revision=lesson['revision'])
        self.tutor.save_annotation({'page':self.page,'annotation':new['annotation'],'data':{'kind':'line','rect':[.1,.1,.7,.2],'text':'Other editor','verified':False}})
        self.assertTrue(self.tutor.tutor_lessons({'id':self.page})[0]['stale'])

    def test_uncertainty_and_damage_cannot_be_ground_truth(self):
        with self.assertRaises(ValueError):self.save(text='[illegible]')
        self.save(text='[illegible]',verified=False)
        self.tutor.save_annotation({'page':self.page,'data':{'kind':'missing','rect':[.2,.15,.1,.1]}})
        with self.assertRaises(ValueError):self.save()
        self.save(verified=False)
        self.tutor.tutor_role({'id':self.page,'role':'train'})
        result=self.tutor.dataset_explicit({'path':str(self.root/'dataset')})
        self.assertEqual(result['train'],0);self.assertEqual(result['excluded'],2)

    def test_model_reading_never_creates_a_verified_lesson(self):
        def capture(selected,models):
            annotations=self.tutor.annotations({'id':self.page})
            self.assertEqual(len(annotations),0);self.assertFalse(selected[0][1]['verified'])
            self.assertEqual(selected[0][1]['text'],'')
            crop=self.tutor.region_crop({'id':self.page,'annotation':selected[0][1]['id']})
            self.assertEqual((crop['width'],crop['height']),(70,20))
            return {'rows':[{'ensemble':{'consensus_text':'Not reference'}}]}
        with patch.object(self.tutor,'run_comparison',side_effect=capture):
            result=self.tutor.tutor_compare({'id':self.page,'rect':[.1,.1,.7,.2],'models':[]})
        self.assertEqual(len(result['rows']),1)
        self.assertEqual(self.tutor.tutor_lessons({'id':self.page}),[])
        self.assertEqual(self.tutor.annotations({'id':self.page}),[])
        with patch.object(self.tutor,'run_comparison',side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError):self.tutor.tutor_compare({'id':self.page,'rect':[.1,.1,.7,.2],'models':[]})
        self.assertEqual(self.tutor.annotations({'id':self.page}),[])

    def test_role_preserves_book_profile_and_export_keeps_test_separate(self):
        self.tutor.book_profile({'id':self.page,'values':{'languages':'pol+lat','calendar':'julian'}})
        self.tutor.tutor_role({'id':self.page,'role':'test'});self.save()
        result=self.tutor.dataset_explicit({'path':str(self.root/'dataset')})
        self.assertEqual((result['train'],result['validation'],result['test']),(0,0,1))
        profile=self.tutor.tutor_role({'id':self.page});self.assertEqual(profile['languages'],'pol+lat');self.assertEqual(profile['calendar'],'julian')
        with self.assertRaises(ValueError):self.tutor.tutor_role({'id':self.page,'role':'invalid'})

    def test_training_requires_explicit_confirmation_and_copy_mode(self):
        with patch.object(self.engine,'train_model',return_value={'promoted':False}) as train:
            with self.assertRaises(ValueError):self.tutor.tutor_train({'model':'base.mlmodel'})
            result=self.tutor.tutor_train({'model':'base.mlmodel','confirmed':True,'epochs':2})
            self.assertFalse(result['promoted']);self.assertTrue(train.call_args.args[0]['explicit'])

if __name__=='__main__':unittest.main()
