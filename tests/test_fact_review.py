from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from backend.archivereader.engine import Engine
from backend.archivereader.fact_review import FactReviewTools


class FactReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'test-output');self.root=Path(self.temp.name);self.engine=Engine(self.root/'library');self.tools=FactReviewTools(self.engine);self.pages=[];self.records=[]
        for i in range(2):
            path=self.root/f'{i}.png';Image.new('RGB',(300,300),['white','ivory'][i]).save(path);self.engine.import_file({'path':str(path)})
        self.pages=[p['id'] for p in self.engine.list_pages({})]
        for page in self.pages:self.records.append(self.engine.save_record({'kind':'Інші записи та примітки','page':page,'person':'Jan Kowalski','place':'Village','house':'34','date':'1832','text':'Original evidence','verified':False})['id'])
    def tearDown(self):self.engine.db.close();self.temp.cleanup()
    def args(self,status='hypothesis'):
        source=self.tools.fact_source(self.records[0]);return {'record':self.records[0],'field':'person','value':'Jan Kowalski','status':status,'note':'Checked evidence manually','signature':source['signature'],'rect':[.1,.1,.7,.2]}
    def test_statuses_history_and_stale_guard_never_edit_record(self):
        before=self.engine.db.execute('SELECT data FROM records WHERE id=?',(self.records[0],)).fetchone()['data'];args=self.args()
        saved=self.tools.fact_save(args);fact=saved['facts'][0];self.assertFalse(fact['stale']);self.assertEqual(fact['assessment']['status'],'hypothesis')
        with self.assertRaises(ValueError):self.tools.fact_save(args)
        args['revision']=fact['assessment']['revision'];args['status']='transcription';self.tools.fact_save(args)
        self.assertEqual(len(self.tools.fact_history({'record':self.records[0],'field':'person'})),2);self.assertEqual(before,self.engine.db.execute('SELECT data FROM records WHERE id=?',(self.records[0],)).fetchone()['data'])
        self.tools.source_card({'id':self.pages[0],'book':{'archive':'Changed source'}})
        self.assertTrue(self.tools.fact_reviews({'record':self.records[0]})['facts'][0]['stale'])
        with self.assertRaises(ValueError):self.tools.fact_save(args)
    def test_corroboration_requires_independent_evidence_and_manual_review(self):
        args=self.args('corroborated')
        with self.assertRaises(ValueError):self.tools.fact_save(args|{'reviewed':True})
        support=self.tools.fact_source(self.records[1]);args['supports']=[{'record':support['record'],'signature':support['signature']}]
        with self.assertRaises(ValueError):self.tools.fact_save(args)
        with patch.object(self.tools,'document_family',return_value={self.tools.fact_source(r)['doc'] for r in self.records}):
            with self.assertRaises(ValueError):self.tools.fact_save(args|{'reviewed':True})
        result=self.tools.fact_save(args|{'reviewed':True});self.assertEqual(result['facts'][0]['assessment']['status'],'corroborated')
        self.engine.save_record({'kind':'Інші записи та примітки','id':support['record'],'page':support['page'],'person':'Changed support','text':'New evidence'})
        self.assertTrue(self.tools.fact_reviews({'record':self.records[0]})['facts'][0]['stale'])
    def test_neighbor_signals_and_differences_do_not_link(self):
        other=self.engine.save_record({'kind':'Інші записи та примітки','page':self.pages[0],'person':'Jan Kowalsky','place':'Village','house':'99','date':'1833','text':'Other event'})['id']
        candidates=self.tools.neighbor_candidates({'record':self.records[0]});match=next(r for r in candidates if r['source']['record']==other)
        self.assertIn('person',[s['field'] for s in match['signals']]);self.assertIn('house',[s['field'] for s in match['differences']]);self.assertFalse(match['linked']);self.assertEqual(self.engine.db.execute('SELECT COUNT(*) FROM person_links').fetchone()[0],0)
        self.assertNotIn(self.records[1],[r['source']['record'] for r in candidates])
    def test_kinship_hypothesis_is_separate_and_does_not_create_family_link(self):
        before=self.engine.db.execute('SELECT data FROM records WHERE id=?',(self.records[0],)).fetchone()['data']
        initial=self.tools.fact_reviews({'record':self.records[0]})
        self.assertEqual(next(f for f in initial['facts'] if f['field']=='kinship')['value'],'')
        result=self.tools.fact_save(self.args()|{'field':'kinship','value':'Ignatius may be Philip’s brother'})
        self.assertEqual(next(f for f in result['facts'] if f['field']=='kinship')['assessment']['status'],'hypothesis')
        self.assertEqual(before,self.engine.db.execute('SELECT data FROM records WHERE id=?',(self.records[0],)).fetchone()['data'])
        self.assertFalse(self.engine.db.execute("SELECT 1 FROM sqlite_master WHERE name='family_links'").fetchone())
