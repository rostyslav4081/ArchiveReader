import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image,ImageDraw
from backend.archivereader.engine import Engine
from backend.archivereader.layout import LayoutTools,proposals,horizontal_rules


class LayoutTests(unittest.TestCase):
    def setUp(self):
        output=Path(__file__).resolve().parents[1]/'test-output'; output.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=output); self.root=Path(self.temp.name)
        image=self.root/'scan.png'; Image.new('RGB',(200,300),'white').save(image)
        self.engine=Engine(self.root/'library'); self.engine.import_file({'path':str(image)})
        self.page=self.engine.list_pages({})[0]; self.layout=LayoutTools(self.engine)
        lines=[{'box':[x,y,50,12],'text':str(x)+':'+str(y)} for x in [20,120] for y in [30,55,80,105]]
        with self.engine.db: self.engine.db.execute('UPDATE pages SET text=?,lines=? WHERE id=?',('Original page OCR',json.dumps(lines),self.page['id']))

    def tearDown(self): self.engine.db.close(); self.temp.cleanup()

    def test_column_and_table_orders_differ_on_same_geometry(self):
        lines=[{'rect':[x,y,.2,.04]} for x in [.1,.6] for y in [.1,.2,.3]]
        columns=proposals(lines,[0,0,1,1],'columns')
        table=proposals(lines,[0,0,1,1],'table')
        col_lines=[r['rect'] for r in columns if r['kind']=='line']
        row_lines=[r['rect'] for r in table if r['kind']=='line']
        self.assertEqual([r[0] for r in col_lines],[.1,.1,.1,.6,.6,.6])
        self.assertEqual([r[0] for r in row_lines],[.1,.6,.1,.6,.1,.6])

    def test_table_ruling_groups_multiline_cells_into_one_entry(self):
        image=Image.new('RGB',(300,300),'white'); draw=ImageDraw.Draw(image)
        for y in [60,150,240]: draw.line((10,y,290,y),fill='black',width=2)
        rules=horizontal_rules(image,[0,0,1,1]); self.assertEqual(len(rules),3)
        lines=[{'rect':[x,y,.2,.03]} for x in [.1,.6] for y in [.25,.35,.55,.65]]
        regions=proposals(lines,[0,0,1,1],'table',rules)
        self.assertEqual(sum(r['kind']=='entry' for r in regions),2)

    def test_proposal_acceptance_is_explicit_and_parent_links_are_preserved(self):
        proposal=self.layout.layout_propose({'id':self.page['id']})
        self.assertFalse(self.layout.annotations({'id':self.page['id']}))
        line=next(r for r in proposal['regions'] if r['kind']=='line')
        result=self.layout.layout_apply({'id':self.page['id'],'proposal':proposal['id'],'regions':[line['id']]})
        self.assertEqual(result['added'],3)
        rows=self.layout.annotations({'id':self.page['id']})
        self.assertEqual({r['kind'] for r in rows},{'line','entry','column'})
        self.assertTrue(all(not r['verified'] and not r['text'] for r in rows))
        with self.assertRaises(ValueError): self.layout.layout_apply({'id':self.page['id'],'proposal':proposal['id'],'regions':[line['id']]})

    def test_existing_roi_geometry_maps_back_to_whole_page(self):
        with self.engine.db:
            self.engine.db.execute('UPDATE pages SET roi=?,lines=? WHERE id=?',(json.dumps([.5,0,.5,1]),json.dumps([{'text':'test','box':[10,30,30,20]}]),self.page['id']))
        proposal=self.layout.layout_propose({'id':self.page['id'],'mode':'text'})
        rect=next(r['rect'] for r in proposal['regions'] if r['kind']=='line')
        self.assertAlmostEqual(rect[0],.55); self.assertAlmostEqual(rect[2],.15)

    def test_manual_column_anchors_are_reused_instead_of_replaced(self):
        col=self.layout.save_annotation({'page':self.page['id'],'data':{'kind':'column','rect':[.05,.05,.4,.4],'text':'Manual note','reading_order':1}})['id']
        proposal=self.layout.layout_propose({'id':self.page['id'],'mode':'columns'})
        self.assertTrue(any(r.get('parent')==col for r in proposal['regions']))
        self.assertFalse(any(r['kind']=='column' and r['rect'][0]<.5 for r in proposal['regions']))
        self.layout.layout_apply({'id':self.page['id'],'proposal':proposal['id'],'regions':[r['id'] for r in proposal['regions']]})
        self.assertEqual(next(r['text'] for r in self.layout.annotations({'id':self.page['id']}) if r['id']==col),'Manual note')
        with self.assertRaises(ValueError): self.layout.save_annotation({'page':self.page['id'],'data':{'kind':'line','rect':[.1,.1,.2,.02],'reading_order':'bad'}})

    def test_region_ocr_preserves_verified_data_and_maps_crop_coordinates(self):
        col=self.layout.save_annotation({'page':self.page['id'],'data':{'kind':'column','rect':[.5,.1,.4,.8],'text':'Manual text'}})['id']
        self.engine.save_line({'id':self.page['id'],'line':0,'text':'Verified page line','verified':True})
        model=self.root/'model.mlmodel'; model.write_bytes(b'model fixture')
        def recognize(cmd,timeout):
            with Image.open(cmd[4]) as image: self.assertEqual(image.size,(80,240))
            Path(cmd[5]).write_text('<alto><TextLine HPOS="5" VPOS="10" WIDTH="20" HEIGHT="10"><String CONTENT="Ioannes"/></TextLine></alto>',encoding='utf8')
        with patch('backend.archivereader.layout.run_process',side_effect=recognize):
            result=self.layout.recognize_region({'id':self.page['id'],'annotation':col,'model':str(model)})
        self.assertEqual(result['text'],'Ioannes'); self.assertAlmostEqual(result['lines'][0]['rect'][0],.525)
        self.assertEqual(self.engine.page(self.page['id'])['text'],'Original page OCR')
        self.assertEqual(self.engine.details({'id':self.page['id']})['lines'][0]['corrected'],'Verified page line')
        self.assertEqual(self.layout.region_recognition_apply({'id':self.page['id'],'run':result['id']})['added'],1)
        self.assertEqual(self.layout.region_recognition_apply({'id':self.page['id'],'run':result['id']})['added'],0)
        self.assertEqual(next(r for r in self.layout.annotations({'id':self.page['id']}) if r['id']==col)['text'],'Manual text')

    def test_saved_line_uses_actual_crop_without_broadening_layout_and_damage_blocks(self):
        line=self.layout.save_annotation({'page':self.page['id'],'data':{'kind':'line','rect':[.1,.2,.5,.1],'text':'Old line'}})['id']
        model=self.root/'line.mlmodel';model.write_bytes(b'model')
        def recognize(cmd,timeout):
            self.assertNotIn('segment',cmd);self.assertIn('--no-segmentation',cmd)
            with Image.open(cmd[4]) as crop:self.assertEqual(crop.size,(100,30))
            Path(cmd[5]).write_text('<alto><TextLine HPOS="1" VPOS="1" WIDTH="20" HEIGHT="10"><String CONTENT="Anna"/></TextLine></alto>')
        args={'id':self.page['id'],'annotation':line,'model':str(model)}
        with patch('backend.archivereader.layout.run_process',side_effect=recognize):result=self.layout.recognize_region(args)
        self.assertEqual(result['text'],'Anna')
        with self.assertRaises(ValueError):self.layout.layout_propose(args)
        self.layout.save_annotation({'page':self.page['id'],'data':{'kind':'damage','rect':[.2,.2,.1,.05]}})
        with self.assertRaises(ValueError):self.layout.recognize_region(args)
        with self.assertRaises(ValueError):self.layout.region_recognition_apply({'id':self.page['id'],'run':result['id']})

    def test_region_cache_pins_model_segmentation_configuration_and_raw_output(self):
        col=self.layout.save_annotation({'page':self.page['id'],'data':{'kind':'entry','rect':[.1,.1,.8,.8]}})['id']
        model=self.root/'weights.mlmodel';model.write_bytes(b'one');seg=self.root/'seg.mlmodel';seg.write_bytes(b'seg')
        args={'id':self.page['id'],'annotation':col,'model':str(model),'segmentation':str(seg),'mode':'text'}
        def recognize(cmd,timeout):
            segment=cmd.index('segment');ocr=cmd.index('ocr')
            self.assertEqual(cmd[segment+1:ocr],['-bl','-i',str(seg)])
            self.assertEqual(cmd[cmd.index('--threads')+1],'2')
            self.assertEqual(cmd[ocr+1:ocr+3],['-m',str(model)])
            Path(cmd[5]).write_text('<alto><TextLine HPOS="5" VPOS="10" WIDTH="20" HEIGHT="10"><String CONTENT="Ioannes"/></TextLine></alto>',encoding='utf8')
        with patch('backend.archivereader.layout.run_process',side_effect=recognize) as run:
            first=self.layout.recognize_region(args);second=self.layout.recognize_region(args)
            self.assertEqual(run.call_count,1);self.assertTrue(second['reused']);self.assertEqual(first['id'],second['id'])
            model.write_bytes(b'two');third=self.layout.recognize_region(args);self.assertNotEqual(first['id'],third['id'])
            seg.write_bytes(b'new');self.layout.recognize_region(args);self.assertEqual(run.call_count,3)
            self.layout.recognize_region(args|{'force':True});self.assertEqual(run.call_count,4)
            latest=self.layout.recognize_region(args|{'mode':'columns'});self.assertEqual(run.call_count,5)
            (Path(latest['path'])/'result.alto.xml').write_text('broken')
            retried=self.layout.recognize_region(args|{'mode':'columns'});self.assertEqual(run.call_count,6);self.assertFalse(retried['reused'])
        self.assertEqual(self.engine.page(self.page['id'])['text'],'Original page OCR')

    def test_region_inference_mutation_and_stale_apply_rejected_with_conflicts_preserved(self):
        col=self.layout.save_annotation({'page':self.page['id'],'data':{'kind':'entry','rect':[.1,.1,.8,.8],'text':'Manual'}})['id']
        model=self.root/'weights.mlmodel';model.write_bytes(b'one');args={'id':self.page['id'],'annotation':col,'model':str(model)}
        def recognize(cmd,timeout):Path(cmd[5]).write_text('<alto><TextLine HPOS="5" VPOS="10" WIDTH="20" HEIGHT="10"><String CONTENT="Ioannes"/></TextLine></alto>',encoding='utf8')
        with patch('backend.archivereader.layout.run_process',side_effect=recognize):result=self.layout.recognize_region(args)
        self.layout.region_recognition_apply({'id':self.page['id'],'run':result['id']})
        child=next(r for r in self.layout.annotations({'id':self.page['id']}) if r.get('parent')==col)
        self.layout.save_annotation({'page':self.page['id'],'annotation':child['id'],'data':child|{'text':'Human correction','verified':True}})
        outcome=self.layout.region_recognition_apply({'id':self.page['id'],'run':result['id']})
        self.assertEqual(outcome['conflicts'][0]['existing_text'],'Human correction');self.assertFalse(outcome['overwritten'])
        def changing(cmd,timeout):recognize(cmd,timeout);model.write_bytes(b'two')
        with patch('backend.archivereader.layout.run_process',side_effect=changing),self.assertRaises(ValueError):self.layout.recognize_region(args|{'force':True})
        Path(self.engine.page(self.page['id'])['path']).write_bytes(b'changed original')
        with self.assertRaises(ValueError):self.layout.region_recognition_apply({'id':self.page['id'],'run':result['id']})

    def test_manual_order_is_used_when_assembling_saved_text(self):
        col=self.layout.save_annotation({'page':self.page['id'],'data':{'kind':'column','rect':[0,0,1,1]}})['id']
        first=self.layout.save_annotation({'page':self.page['id'],'data':{'kind':'line','rect':[.1,.1,.3,.05],'parent':col,'text':'First'}})['id']
        second=self.layout.save_annotation({'page':self.page['id'],'data':{'kind':'line','rect':[.1,.2,.3,.05],'parent':col,'text':'Second'}})['id']
        self.layout.layout_order({'id':self.page['id'],'regions':[col,second,first]})
        self.assertEqual(self.layout.region_ordered_text({'id':self.page['id'],'annotation':col})['text'],'Second\nFirst')
        with self.assertRaises(ValueError): self.layout.layout_order({'id':self.page['id'],'regions':[first,first]})

if __name__=='__main__': unittest.main()
