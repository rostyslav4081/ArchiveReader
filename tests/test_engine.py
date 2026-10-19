import json
from pathlib import Path
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
from unittest.mock import patch
import pymupdf as fitz
from PIL import Image
from backend.archivereader.engine import Engine, KINDS, error_rate, parse_alto, parse_tsv, suggest_record


class EngineTests(unittest.TestCase):
    def setUp(self):
        (Path(__file__).resolve().parents[1]/'test-output').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'test-output')
        self.root=Path(self.temp.name)
        self.engine=Engine(self.root/'library')

    def tearDown(self):
        self.engine.db.close(); self.temp.cleanup()

    def image(self):
        path=self.root/'метрика.png'; Image.new('RGB',(300,200),'white').save(path)
        self.engine.import_file({'path':str(path)})
        return self.engine.list_pages({})[0]

    def test_import_is_immutable_and_deduplicated(self):
        p=self.image(); original=Path(p['path']).read_bytes()
        (self.root/'метрика.png').write_bytes(b'changed')
        self.assertEqual(Path(p['path']).read_bytes(),original)
        self.assertTrue(self.engine.import_file({'path':p['path']})['duplicate'])
        self.assertEqual(len(self.engine.list_pages({})),1)

    def test_multipage_tiff_and_render_preserve_original(self):
        path=self.root/'book.tiff'
        Image.new('RGB',(100,100),'white').save(path,save_all=True,append_images=[Image.new('RGB',(100,100),'black')])
        self.assertEqual(self.engine.import_file({'path':str(path)})['pages'],2)
        before=path.read_bytes()
        p=self.engine.list_pages({})[1]
        result=self.engine.render({'id':p['id'],'preprocess':'contrast'})
        with Image.open(result['path']) as im: self.assertEqual(im.size,(100,100))
        self.assertEqual(before,path.read_bytes())

    def test_large_pdf_is_lazy_and_extracts_real_text(self):
        path=self.root/'large.pdf'
        with fitz.open() as d:
            for n in range(2500):
                page=d.new_page()
                if n==2499: page.insert_text((50,50),'Joannes 1832')
            d.save(path)
        self.assertEqual(self.engine.import_file({'path':str(path)})['pages'],2500)
        self.assertEqual(list((self.engine.root/'cache').iterdir()),[])
        p=self.engine.list_pages({})[-1]
        result=self.engine.recognize({'id':p['id']})
        self.assertIn('Joannes 1832',result['text'])
        self.assertEqual(result['engine'],'PDF text layer')
        self.assertTrue(self.engine.recognize({'id':p['id']})['skipped'])

    def test_failed_worker_is_recorded_and_resume_recovers(self):
        p=self.image()
        with self.assertRaises(ValueError): self.engine.recognize({'id':p['id'],'engine':'tesseract','executable':'missing-ocr-test-123'})
        self.assertEqual(self.engine.page(p['id'])['status'],'error')
        with self.engine.db: self.engine.db.execute("UPDATE pages SET status='running'")
        self.assertEqual(self.engine.recover({})['recovered'],1)
        self.assertEqual(self.engine.page(p['id'])['status'],'pending')

    def test_photographed_pdf_with_caption_is_not_mistaken_for_complete_text(self):
        source=self.root/'photo.png'; Image.new('RGB',(400,600),'white').save(source)
        pdf=self.root/'photographed-book.pdf'
        with fitz.open() as document:
            page=document.new_page(width=400,height=650)
            page.insert_text((15,20),'Caption only - not the handwritten record')
            page.insert_image(fitz.Rect(0,40,400,640),filename=str(source))
            document.save(pdf)
        self.engine.import_file({'path':str(pdf)}); page=self.engine.list_pages({})[0]
        def fake_ocr(cmd,timeout):
            Path(cmd[2]).with_suffix('.tsv').write_text('level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n5\t1\t1\t1\t1\t1\t10\t50\t100\t20\t80\tJoannes\n',encoding='utf8')
        with patch('backend.archivereader.engine.run_process',side_effect=fake_ocr) as worker:
            self.engine.recognize({'id':page['id'],'engine':'tesseract','useTextLayer':True})
        self.assertTrue(worker.called)
        self.assertEqual(self.engine.page(page['id'])['text'],'Joannes')

    def test_records_and_history_survive_reopen(self):
        p=self.image(); args={'page':p['id'],'kind':KINDS[1],'text':'Cath[…]','person':'Catharina','verified':False}
        r=self.engine.save_record(args)
        self.engine.save_record(args|r|{'person':'Catharina Skowyra','verified':True})
        self.engine.db.close(); self.engine=Engine(self.root/'library')
        self.assertEqual(self.engine.details({'id':p['id']})['records'][0]['person'],'Catharina Skowyra')
        self.assertEqual(self.engine.db.execute('SELECT COUNT(*) FROM corrections').fetchone()[0],2)
        self.assertEqual(len(self.engine.list_pages({'search':'Skowyra'})),1)

    def test_xlsx_has_five_sheets_and_safe_strings(self):
        p=self.image()
        self.engine.save_record({'page':p['id'],'kind':KINDS[1],'person':'=1+1','text':'Cath[…]\x01','verified':False})
        path=self.root/'result.xlsx'; self.engine.export({'path':str(path)})
        with zipfile.ZipFile(path) as z:
            for name in z.namelist(): ET.fromstring(z.read(name))
            self.assertEqual(len(ET.fromstring(z.read('xl/workbook.xml')).findall('.//{*}sheet')),5)
            sheet=ET.fromstring(z.read('xl/worksheets/sheet2.xml'))
            self.assertFalse(sheet.findall('.//{*}f'))
            self.assertIn('=1+1',z.read('xl/worksheets/sheet2.xml').decode())
            self.assertIsNotNone(sheet.find('{*}autoFilter'))

    def test_export_does_not_silently_truncate_long_text(self):
        p=self.image(); self.engine.save_record({'page':p['id'],'kind':KINDS[0],'text':'a'*32768})
        dest=self.root/'existing.xlsx'; dest.write_bytes(b'previous')
        with self.assertRaises(ValueError): self.engine.export({'path':str(dest)})
        self.assertEqual(dest.read_bytes(),b'previous')
        self.engine.export({'path':str(self.root/'full.json')})
        self.assertEqual(len(json.loads((self.root/'full.json').read_text(encoding='utf-8'))[0]['text']),32768)

    def test_verified_line_training_and_rerun_protection(self):
        p=self.image()
        with self.engine.db:
            self.engine.db.execute('UPDATE pages SET lines=? WHERE id=?',(json.dumps([{'text':'Joanncs','box':[10,10,100,30],'confidence':0.5}]),p['id']))
        self.engine.save_line({'id':p['id'],'line':0,'text':'Joannes','verified':True})
        result=self.engine.training({'path':str(self.root/'training')})
        self.assertEqual(result['train']+result['validation'],1)
        self.assertEqual(next((self.root/'training').glob('*.gt.txt')).read_text(encoding='utf-8'),'Joannes')
        with self.assertRaises(ValueError): self.engine.recognize({'id':p['id'],'force':True})

    def test_alto_coordinates_and_confidence(self):
        path=self.root/'alto.xml'; path.write_text('<alto xmlns="urn:test"><TextLine HPOS="2" VPOS="3" WIDTH="40" HEIGHT="10"><String CONTENT="Joannes" WC="0.8"/></TextLine></alto>')
        line=parse_alto(path)[0]
        self.assertEqual(line['box'],[2,3,40,10]); self.assertEqual(line['confidence'],0.8)

    def test_metrics(self):
        self.assertAlmostEqual(error_rate(list('abc'),list('axc')),1/3)
        self.assertEqual(error_rate([],[]),0)
        self.assertIsNone(error_rate([],['a']))

    def test_ocr_region_preserves_original_and_history(self):
        p=self.image(); before=Path(p['path']).read_bytes()
        with self.engine.db: self.engine.db.execute("UPDATE pages SET text='previous result',status='done' WHERE id=?",(p['id'],))
        self.engine.set_region({'id':p['id'],'roi':[0.25,0.25,0.5,0.5]})
        cropped=self.engine.render({'id':p['id'],'full':True})
        full=self.engine.render({'id':p['id']})
        self.assertEqual((cropped['width'],cropped['height']),(150,100))
        self.assertEqual((full['width'],full['height']),(300,200))
        self.assertEqual(Path(p['path']).read_bytes(),before)
        self.assertEqual(self.engine.db.execute('SELECT text FROM recognition_history').fetchone()[0],'previous result')
        self.assertEqual(self.engine.page(p['id'])['status'],'pending')
        with self.assertRaises(ValueError): self.engine.set_region({'id':p['id'],'roi':[0.9,0,0.5,1]})

    def test_mixed_narrative_is_not_forced_into_a_record_type(self):
        self.assertEqual(suggest_record('Baptizatus Joannes. Copulati Paulus et Anna. Mortuus Petrus.')['kind'],KINDS[0])
        self.assertEqual(suggest_record('Unreadable text and a drawing')['kind'],KINDS[0])
        p=self.image()
        with self.engine.db: self.engine.db.execute('UPDATE pages SET text=? WHERE id=?',('Full continuous narrative',p['id']))
        self.engine.save_record({'page':p['id'],'kind':KINDS[1],'text':'One selected entry'})
        path=self.root/'all.json'; self.engine.export({'path':str(path)})
        result=json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(result[0]['page_text'],'Full continuous narrative')
        self.assertEqual(result[0]['text'],'One selected entry')

    def test_lighting_derivative_and_quality_keep_source_intact(self):
        p=self.image(); original=Path(p['path']).read_bytes()
        result=self.engine.render({'id':p['id'],'full':True,'preprocess':'lighting'})
        self.assertTrue(Path(result['path']).is_file())
        self.assertEqual(Path(p['path']).read_bytes(),original)
        hints=self.engine.image_quality({'id':p['id']})
        self.assertIn('small',hints['flags'])
        self.assertNotIn('legible',hints)

    def test_missing_text_is_excluded_from_training_and_accuracy(self):
        p=self.image()
        with self.engine.db:
            self.engine.db.execute('UPDATE pages SET lines=? WHERE id=?',(json.dumps([{'text':'Anna','box':[10,10,100,30]}]),p['id']))
        self.engine.save_line({'id':p['id'],'line':0,'text':'An[lacuna]','verified':True})
        result=self.engine.training({'path':str(self.root/'uncertain-training')})
        self.assertEqual(result['excluded_uncertain'],1)
        self.assertEqual(result['train']+result['validation'],0)
        self.assertEqual(self.engine.quality({})['lines'],0)
        self.assertEqual(self.engine.details({'id':p['id']})['lines'][0]['corrected'],'An[lacuna]')


if __name__=='__main__': unittest.main(verbosity=2)
