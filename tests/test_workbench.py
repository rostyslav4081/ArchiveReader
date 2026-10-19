import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from backend.archivereader.engine import Engine, KINDS
from backend.archivereader.workbench import Workbench, name_key, perspective_coefficients


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        output=Path(__file__).resolve().parents[1]/'test-output'
        output.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=output)
        self.root=Path(self.temp.name)
        self.engine=Engine(self.root/'library')
        self.workbench=Workbench(self.engine)

    def tearDown(self):
        self.engine.db.close(); self.temp.cleanup()

    def page(self,color='white'):
        source=self.root/(color+'.png')
        Image.new('RGB',(200,100),color).save(source)
        result=self.engine.import_file({'path':str(source)})
        return next(p for p in self.engine.list_pages({}) if p['doc']==result['id'])

    def region(self,page,kind='line',rect=None,**values):
        return self.workbench.save_annotation({'page':page['id'],'data':{'kind':kind,'rect':rect or [.1,.2,.7,.3],'text':'Joannes','verified':True}|values})['id']

    def test_annotations_keep_coordinates_on_whole_original_with_roi(self):
        page=self.page(); ident=self.region(page)
        self.engine.set_region({'id':page['id'],'roi':[.5,0,.5,1]})
        cropped=self.workbench.region_crop({'id':page['id'],'annotation':ident})
        self.assertEqual((cropped['width'],cropped['height']),(140,30))
        self.workbench.save_annotation({'page':page['id'],'annotation':ident,'data':{'kind':'line','rect':[.1,.2,.7,.3],'text':'Johannes','verified':True}})
        self.assertEqual(self.engine.db.execute('SELECT COUNT(*) FROM annotation_history').fetchone()[0],2)

    def test_record_link_cannot_cross_pages(self):
        first,second=self.page(),self.page('red')
        record=self.engine.save_record({'page':first['id'],'kind':KINDS[0],'person':'Anna'})
        with self.assertRaises(ValueError): self.region(second,record=record['id'])
        parent=self.region(first,'column',[.1,.1,.4,.8])
        with self.assertRaises(ValueError): self.region(first,parent=parent)

    def test_missing_and_damaged_lines_are_not_training_data(self):
        page=self.page(); self.region(page); self.region(page,'missing',[.2,.2,.05,.05])
        self.workbench.book_profile({'id':page['id'],'values':{'split':'train'}})
        result=self.workbench.dataset_explicit({'path':str(self.root/'dataset')})
        self.assertEqual(result['train'],0); self.assertEqual(result['excluded'],1)

    def test_region_edits_preserve_hierarchy(self):
        page=self.page()
        parent=self.region(page,'column',[.1,.1,.8,.8])
        child=self.region(page,'entry',[.1,.1,.8,.8],parent=parent)
        values={'kind':'column','rect':[.1,.1,.8,.8],'parent':child}
        with self.assertRaises(ValueError):
            self.workbench.save_annotation({'page':page['id'],'annotation':parent,'data':values})
        values['parent']=''; values['rect']=[.1,.1,.4,.4]
        with self.assertRaises(ValueError):
            self.workbench.save_annotation({'page':page['id'],'annotation':parent,'data':values})
        self.assertEqual(len(self.workbench.annotations({'id':page['id']})),2)

    def test_document_splits_and_legacy_training_exclude_test_books(self):
        train,test=self.page(),self.page('red')
        self.region(train); self.region(test)
        for page,split in [(train,'train'),(test,'test')]: self.workbench.book_profile({'id':page['id'],'values':{'split':split}})
        result=self.workbench.dataset_explicit({'path':str(self.root/'dataset')})
        self.assertEqual((result['train'],result['test']),(1,1))
        with self.engine.db: self.engine.db.execute('UPDATE pages SET lines=? WHERE id=?',(json.dumps([{'text':'Joanncs','box':[20,20,100,30]}]),test['id']))
        self.engine.save_line({'id':test['id'],'line':0,'text':'Joannes','verified':True})
        self.assertEqual(self.engine.training({'path':str(self.root/'legacy')})['train'],0)

    def test_photo_operations_preserve_sources_and_lineage(self):
        page=self.page('red'); original=Path(page['path']).read_bytes()
        rotated=self.workbench.prepare_photo({'id':page['id'],'mode':'rotate','angle':90})
        with Image.open(rotated['paths'][0]) as image: self.assertEqual(image.size,(100,200))
        copies=self.workbench.import_derivative(rotated)
        self.assertEqual(self.engine.db.execute('SELECT parent_page FROM derivatives WHERE doc=?',(copies[0]['id'],)).fetchone()[0],page['id'])
        spread=self.workbench.prepare_photo({'id':page['id'],'mode':'split','position':.5})
        self.assertEqual(len(spread['paths']),2)
        perspective=self.workbench.prepare_photo({'id':page['id'],'mode':'perspective','points':[[0,0],[1,0],[1,1],[0,1]]})
        with Image.open(perspective['paths'][0]) as image: self.assertEqual(image.size,(200,100))
        dewarped=self.workbench.prepare_photo({'id':page['id'],'mode':'dewarp','points':[[0,0],[.5,0],[1,0],[0,1],[.5,1],[1,1]]})
        with Image.open(dewarped['paths'][0]) as image: self.assertEqual(image.size,(200,100))
        self.assertEqual(Path(page['path']).read_bytes(),original)
        derivative=next(p for p in self.engine.list_pages({}) if p['doc']==copies[0]['id'])
        self.workbench.book_profile({'id':page['id'],'values':{'split':'train'}})
        with self.assertRaises(ValueError): self.workbench.book_profile({'id':derivative['id'],'values':{'split':'test'}})
        with self.assertRaises(ValueError): self.workbench.prepare_photo({'id':page['id'],'mode':'perspective','points':[[0,0],[1,1],[1,0],[0,1]]})

    def test_perspective_mapping_and_curved_guides_have_correct_orientation(self):
        source=self.root/'gradient.png'
        image=Image.new('RGB',(200,100)); image.putdata([(x,y,0) for y in range(100) for x in range(200)]); image.save(source)
        doc=self.engine.import_file({'path':str(source)})['id']; page=next(p for p in self.engine.list_pages({}) if p['doc']==doc)
        result=self.workbench.prepare_photo({'id':page['id'],'mode':'perspective','points':[[.1,.1],[.9,.1],[.9,.9],[.1,.9]]})
        with Image.open(result['paths'][0]) as mapped:
            self.assertEqual(mapped.size,(160,80))
            x,y,_=mapped.getpixel((80,40)); self.assertLess(abs(x-100),2); self.assertLess(abs(y-50),2)
        result=self.workbench.prepare_photo({'id':page['id'],'mode':'dewarp','points':[[0,.1],[.5,.2],[1,.1],[0,.9],[.5,.8],[1,.9]]})
        with Image.open(result['paths'][0]) as mapped:
            self.assertEqual(mapped.width,200)
            _,y,_=mapped.getpixel((100,mapped.height//2)); self.assertLess(abs(y-50),3)

    def test_fuzzy_name_matches_link_back_to_source(self):
        page=self.page(); record=self.engine.save_record({'page':page['id'],'kind':KINDS[0],'person':'Jan Šimek'})
        matches=self.workbench.similar_names({'query':'Simek'})
        self.assertEqual(matches[0]['record'],record['id']); self.assertEqual(matches[0]['page'],page['id'])
        self.assertEqual(name_key('Šimek'),'simek')
        self.assertEqual(name_key('Łukasz'),'lukasz')

    def test_known_trained_model_cannot_claim_its_training_book_as_test(self):
        page=self.page(); region=self.region(page)
        model=self.root/'trained.safetensors'; model.write_bytes(b'synthetic model identity')
        run=self.engine.root/'models'/'training-synthetic'; (run/'dataset').mkdir(parents=True)
        (run/'run.json').write_text(json.dumps({'output_models':[{'sha256':hashlib.sha256(model.read_bytes()).hexdigest()}]}))
        (run/'dataset'/'manifest.json').write_text(json.dumps([{'document':page['doc'],'split':'train'}]))
        with self.assertRaises(ValueError):
            self.workbench.check_known_training_overlap([(page,{'id':region})],[{'path':str(model)}])

    def test_comparison_only_uses_verified_reference_and_never_rewrites_ocr(self):
        page=self.page(); self.region(page,verified=False)
        def comparison(manifest,models,output):
            rows=json.loads(manifest.read_text(encoding='utf8'))
            self.assertNotIn('reference',rows[0])
            return {'rows':rows,'models':[]}
        with patch('backend.archivereader.workbench.compare',side_effect=comparison):
            self.workbench.compare_regions({'id':page['id'],'models':[]})
        self.assertEqual(self.engine.details({'id':page['id']})['text'],'')


if __name__=='__main__': unittest.main()
