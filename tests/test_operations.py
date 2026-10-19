from pathlib import Path
import tempfile
import unittest
import json
import pymupdf
from backend.archivereader.engine import Engine
from backend.archivereader.operations import Operations


class OperationsTests(unittest.TestCase):
    def setUp(self):
        output=Path(__file__).resolve().parents[1]/'test-output';output.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=output);self.root=Path(self.temp.name);self.engine=Engine(self.root/'library');self.docs=[]
        for number in [1,2]:
            source=self.root/f'book{number}.pdf';pdf=pymupdf.open()
            for page in range(2):pdf.new_page().insert_text((50,50),f'Book {number} Page {page}')
            pdf.save(source);pdf.close();self.docs.append(self.engine.import_file({'path':str(source)})['id'])
        self.tools=Operations(self.engine)

    def tearDown(self):self.engine.db.close();self.temp.cleanup()

    def test_queue_processes_books_and_persists_resume_after_reopen(self):
        job=self.tools.batch_create({'documents':self.docs,'options':{'useTextLayer':True}})['id']
        self.assertEqual(self.tools.batch_step({'job':job})['counts']['done'],1)
        self.engine.db.close();self.engine=Engine(self.root/'library');self.tools=Operations(self.engine)
        for _ in range(3):status=self.tools.batch_step({'job':job})
        self.assertEqual(status['counts']['done'],4);self.assertEqual(status['counts']['queued'],0)
        self.assertTrue(all(p['status']=='done' for p in self.engine.list_pages({})))

    def test_queue_recovers_interrupted_page_and_keeps_failed_errors(self):
        job=self.tools.batch_create({'documents':[self.docs[0]],'options':{'useTextLayer':True}})['id'];page=self.engine.list_pages({})[0]['id']
        with self.engine.db:
            self.engine.db.execute('UPDATE book_tasks SET state="running" WHERE job=? AND page=?',(job,page));self.engine.db.execute('UPDATE pages SET status="running" WHERE id=?',(page,))
        self.assertEqual(self.tools.batch_recover({'job':job})['counts']['queued'],2)
        original=self.engine.recognize
        def fail(a):raise RuntimeError('Synthetic worker failure')
        self.engine.recognize=fail
        status=self.tools.batch_step({'job':job});self.assertEqual(status['counts']['failed'],1);self.assertIn('Synthetic',status['errors'][0]['error'])
        self.engine.recognize=original;self.assertEqual(self.tools.batch_recover({'job':job,'retry_errors':True})['counts']['queued'],2)

    def test_corrected_pages_are_skipped_and_changed_model_blocks_resume(self):
        page=self.engine.list_pages({})[0]['id']
        with self.engine.db:self.engine.db.execute('UPDATE pages SET lines=? WHERE id=?',(json.dumps([{'text':'Original','box':[0,0,20,10]}]),page))
        self.engine.save_line({'id':page,'line':0,'text':'Verified','verified':True})
        model=self.root/'model.mlmodel';model.write_bytes(b'first')
        job=self.tools.batch_create({'documents':[self.docs[0]],'options':{'model':str(model),'useTextLayer':True}})['id']
        self.assertEqual(self.tools.batch_status({'job':job})['counts']['skipped'],1)
        model.write_bytes(b'changed model')
        with self.assertRaises(ValueError):self.tools.batch_step({'job':job})
        self.assertEqual(self.engine.details({'id':page})['lines'][0]['corrected'],'Verified')

    def test_coverage_never_treats_unverified_scan_text_as_reference(self):
        coverage=self.tools.evaluation_coverage({});self.assertEqual(len(coverage),2)
        self.assertTrue(all(not b['ready'] and b['verified_lines']==0 for b in coverage))
        self.assertIn('languages',coverage[0]['missing_profile'])
