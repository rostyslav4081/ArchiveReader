import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image,ImageDraw
import pymupdf
from backend.archivereader.engine import Engine
from backend.archivereader.books import BookTools
from backend.archivereader.research import ResearchTools
from backend.archivereader.sources import SourceTools


class BookTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'test-output');self.root=Path(self.temp.name)
        self.photos=self.root/'photos';self.photos.mkdir()
        for n in [10,2,1]:
            im=Image.new('RGB',(300,500),'white');ImageDraw.Draw(im).text((20,30),'page '+str(n),fill='black');im.save(self.photos/f'page{n}.jpg')
        self.engine=Engine(self.root/'library');self.tools=BookTools(self.engine)
        self.book=self.tools.book_import_folder({'path':str(self.photos)})
        self.pages=[i['page'] for i in self.book['items']]

    def tearDown(self):self.engine.db.close();self.temp.cleanup()

    def test_natural_order_gaps_reorder_and_source_identity(self):
        self.assertEqual([i['source'] for i in self.book['items']],['page1.jpg','page2.jpg','page10.jpg'])
        sha={r['id']:hashlib.sha256(Path(r['path']).read_bytes()).hexdigest() for r in self.engine.db.execute('SELECT * FROM documents')}
        record=self.engine.save_record({'page':self.pages[0],'kind':'Народження','person':'Anna','text':'Evidence'})['id']
        items=[self.book['items'][2],{'label':'missing folio 2'},self.book['items'][0],self.book['items'][1]]
        self.tools.book_save({'book':self.book['id'],'name':'Ordered','items':items})
        self.assertEqual(self.tools.book_index({'book':self.book['id']})['gaps'],1)
        self.assertEqual(self.engine.db.execute('SELECT page FROM records WHERE id=?',(record,)).fetchone()['page'],self.pages[0])
        self.assertEqual(self.engine.page(self.pages[0])['num'],0)
        for r in self.engine.db.execute('SELECT * FROM documents'):self.assertEqual(sha[r['id']],hashlib.sha256(Path(r['path']).read_bytes()).hexdigest())
        with self.assertRaises(ValueError):self.tools.book_save({'name':'duplicate group','items':[items[0]]})
        with self.assertRaises(ValueError):self.tools.book_save({'book':self.book['id'],'name':'dup','items':[items[0],items[0]]})

    def test_shared_profile_dictionary_source_and_split_protection(self):
        self.tools.book_profile({'id':self.pages[0],'values':{'languages':'uk,pl','calendar':'gregorian','split':'test'}})
        self.assertEqual(self.tools.book_profile({'id':self.pages[2]})['languages'],'uk,pl')
        self.assertEqual(len(self.tools.document_family(self.engine.page(self.pages[0])['doc'])),3)
        source=SourceTools(self.engine);source.source_card({'id':self.pages[0],'book':{'archive':'Archive','title':'Book','fonds':'42'}})
        self.assertEqual(source.source_card({'id':self.pages[2]})['book']['fonds'],'42')
        self.assertIn('сторінка збірки 3',source.source_card({'id':self.pages[2]})['citation'])
        research=ResearchTools(self.engine);research.book_dictionary({'page':self.pages[0],'term':'Kowalski','meaning':'surname','verified':True})
        self.assertEqual(len(research.book_dictionary({'page':self.pages[2]})),1)
        self.tools.book_profile({'id':self.pages[1],'values':{'split':'train'}})
        self.assertTrue(all(self.tools.book_profile({'id':p})['split']=='train' for p in self.pages))

    def test_pdf_unicode_corrected_layer_and_gap_and_missing_geometry(self):
        self.engine.db.execute("UPDATE pages SET status='done',text=?,lines=? WHERE id=?",('wrong',json.dumps([{'text':'wrong','box':[20,30,220,30]}]),self.pages[0]));self.engine.db.commit()
        self.engine.save_line({'id':self.pages[0],'line':0,'text':'Ковальський Jan Šimek','verified':True})
        items=[self.book['items'][0],{'label':'Відсутній аркуш'},self.book['items'][1]]
        self.tools.book_save({'book':self.book['id'],'name':'PDF book','items':items})
        path=self.root/'book.pdf';report=self.tools.book_pdf({'book':self.book['id'],'path':str(path)})
        with pymupdf.open(path) as pdf:
            self.assertEqual(len(pdf),3);self.assertIn('Ковальський',pdf[0].get_text());self.assertIn('Šimek',pdf[0].get_text())
            self.assertNotIn('wrong',pdf[0].get_text());self.assertTrue(pdf[0].search_for('Jan'));self.assertIn('Відсутній',pdf[1].get_text())
            self.assertEqual(len(pdf.get_toc()),3)
        self.assertEqual(report['pages'][0]['placed_lines'],1);self.assertEqual(report['pages'][2]['placed_lines'],0)
        with self.assertRaises(ValueError):self.tools.book_pdf({'book':self.book['id'],'path':self.engine.page(self.pages[0])['path']})

    def test_combined_filters_fulltext_scope_and_task_regions(self):
        record=self.engine.save_record({'page':self.pages[0],'kind':'Народження','person':'Anna Kowalska','place':'Łódź','date':'12.03.1832','house':'34','text':'context'})['id']
        self.engine.save_record({'page':self.pages[1],'kind':'Народження','person':'Anna Kowalska','place':'Łódź','date':'BET 1830 AND 1840','house':'34'})
        result=self.tools.record_search({'person':'kowalska','place':'lodz','house':'34','year_from':'1832','year_to':'1832','book':self.book['id']})
        self.assertEqual([r['id'] for r in result['rows']],[record]);self.assertEqual(self.tools.record_search({'person':'Anna','house':'35'})['rows'],[])
        self.engine.db.execute('UPDATE pages SET text=? WHERE id=?',('Znaleziono контекст',self.pages[0]));self.engine.db.commit()
        self.assertEqual(len(self.tools.library_search({'book':self.book['id'],'query':'контекст'})['rows']),1)
        task=self.tools.research_task({'page':self.pages[0],'data':{'text':'Check date','rect':[.1,.2,.3,.4],'done':False}})[0]
        self.tools.research_task({'id':task['id'],'page':task['page'],'data':task['data']|{'done':True}})
        self.assertEqual(self.tools.research_task({'open_only':True}),[])
        with self.assertRaises(ValueError):self.tools.research_task({'id':task['id'],'page':self.pages[1],'data':task['data']})

    def test_template_semantics_skip_existing_and_invalid_target_atomicity(self):
        cols=[{'rect':[0,0,.4,1],'field':'person','label':'Nomen','meaning':'Name of deceased'}]
        self.tools.book_template({'book':self.book['id'],'columns':cols})
        self.tools.save_annotation({'page':self.pages[0],'data':{'kind':'column','rect':[0,0,1,1],'field':'notes','label':'custom'}})
        r=self.tools.book_template({'book':self.book['id'],'apply':True})
        self.assertEqual((r['added'],r['skipped']),(2,1))
        self.assertEqual(self.tools.annotations({'id':self.pages[1]})[0]['meaning'],'Name of deceased')
        self.assertEqual(self.tools.annotations({'id':self.pages[0]})[0]['label'],'custom')
        with self.assertRaises(ValueError):self.tools.book_template({'book':self.book['id'],'apply':True,'pages':['invalid']})

    def test_worker_book_commands(self):
        request={'root':str(self.engine.root),'command':'book_get','book':self.book['id']}
        result=subprocess.run([sys.executable,'-X','utf8',str(Path(__file__).resolve().parents[1]/'backend/archivereader/engine.py')],input=json.dumps(request),capture_output=True,text=True,encoding='utf8',check=True)
        payload=json.loads(result.stdout);self.assertTrue(payload['ok']);self.assertEqual(len(payload['result']['items']),3)

    def test_mixed_pdf_uses_htr_for_image_page_and_preserves_native_text(self):
        source=self.root/'mixed.pdf'
        with pymupdf.open() as pdf:
            page=pdf.new_page();page.insert_text((40,60),'Printed native text')
            page=pdf.new_page(width=300,height=500);page.insert_image(page.rect,filename=str(self.photos/'page1.jpg'));page.insert_text((10,490),'caption')
            pdf.save(source)
        doc=self.engine.import_file({'path':str(source)})['id']
        pages=[r['id'] for r in self.engine.db.execute('SELECT id FROM pages WHERE doc=? ORDER BY num',(doc,))]
        self.assertEqual(self.engine.recognize({'id':pages[0]})['engine'],'PDF text layer')
        model=self.root/'synthetic.mlmodel';model.write_text('test stub')
        def recognize_stub(cmd,timeout):
            output=Path(cmd[cmd.index('-i')+2]);self.assertEqual(output.suffix,'.xml')
            output.write_text('<alto><TextLine HPOS="50" VPOS="100" WIDTH="200" HEIGHT="30"><String CONTENT="Рукописний запис"/></TextLine></alto>',encoding='utf8')
        with patch('backend.archivereader.engine.run_process',side_effect=recognize_stub) as run:
            self.assertEqual(self.engine.recognize({'id':pages[1],'engine':'kraken','model':str(model),'useTextLayer':True})['engine'],'kraken');run.assert_called_once()
        book=self.tools.book_save({'name':'Mixed PDF','items':[{'page':p} for p in pages]})
        with self.assertRaises(ValueError):self.tools.book_pdf({'book':book['id'],'path':str(source)})
        output=self.root/'indexed-mixed.pdf';self.tools.book_pdf({'book':book['id'],'path':str(output)})
        with pymupdf.open(output) as pdf:
            self.assertIn('Printed native text',' '.join(pdf[0].get_text().split()));self.assertIn('Рукописний запис',' '.join(pdf[1].get_text().split()))
            self.assertTrue(pdf[0].search_for('Printed native text'));self.assertTrue(pdf[1].search_for('Рукописний запис'))
        # This verifies routing and export with a stub recognizer, not handwriting accuracy.

    def test_common_model_scores_keep_failed_lines_visible(self):
        from backend.archivereader.htr_compare import book_scores,score
        rows=[{'book':'b','book_name':'Book','results':{'A':{'text':'Anna','score':score('Anna','Anna')},'B':{'text':'Anma','score':score('Anna','Anma')}}},
              {'book':'b','results':{'A':{'text':'Maria','score':score('Maria','Maria')},'B':{'error':'failed'}}}]
        result=book_scores(rows,['A','B'])[0]
        self.assertEqual((result['lines'],result['common_scored_lines']),(2,1));self.assertEqual(result['models'][1]['failed_lines'],1)
        self.assertEqual(result['models'][1]['common_cer'],.25)

    def test_hundreds_of_photos_keep_book_order_in_main_page_list(self):
        folder=self.root/'large';folder.mkdir()
        for n in range(200):
            Image.new('RGB',(60,80),(n,255-n,40)).save(folder/f'folio{n+1}.png')
        book=self.tools.book_import_folder({'path':str(folder)})
        self.assertEqual(len(book['items']),200)
        expected=[i['page'] for i in reversed(book['items'])]
        self.tools.book_save({'book':book['id'],'name':'200 photos','items':list(reversed(book['items']))})
        displayed=[p for p in self.engine.list_pages({}) if p.get('book')==book['id']]
        self.assertEqual([p['id'] for p in displayed],expected)
        self.assertEqual(displayed[0]['book_position'],1)
        self.assertEqual(self.tools.book_index({'book':book['id']})['pages'],200)


if __name__=='__main__':unittest.main()
