import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from backend.archivereader.engine import Engine
from backend.archivereader.people import PeopleTools


class PeopleTests(unittest.TestCase):
    def setUp(self):
        output=Path(__file__).resolve().parents[1]/'test-output'; output.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=output); self.root=Path(self.temp.name)
        source=self.root/'book.tif'; Image.new('RGB',(150,200),'white').save(source,save_all=True,append_images=[Image.new('RGB',(150,200),'white')])
        self.engine=Engine(self.root/'library'); self.engine.import_file({'path':str(source)})
        pages=self.engine.list_pages({})
        self.a=self.engine.save_record({'page':pages[0]['id'],'kind':'Інші записи та примітки','person':'Jan Kowalski','place':'Lviv','house':'12','date':'1832','text':'First evidence','verified':True})['id']
        self.b=self.engine.save_record({'page':pages[1]['id'],'kind':'Інші записи та примітки','person':'Jan Kowalsky','related1':'Jan Kowalski','place':'Lviv','house':'15','date':'1840','text':'Second evidence'})['id']
        self.tools=PeopleTools(self.engine); self.left={'record':self.a,'field':'person'}; self.right={'record':self.b,'field':'person'}

    def tearDown(self): self.engine.db.close(); self.temp.cleanup()

    def candidate(self):
        return next(c for c in self.tools.person_candidates({'left':self.left}) if c['right']['field']=='person')

    def decide(self,c,status='confirmed',note='Reviewed both original scans'):
        return self.tools.person_link({'left':c['left'],'right':c['right'],'status':status,'note':note,'expected':c['expected'],
            'signatures':{self.tools.key(c[side]):c[side]['signature'] for side in ['left','right']}})

    def test_candidates_keep_roles_evidence_and_conflicts_without_merging(self):
        candidates=self.tools.person_candidates({'left':self.left}); c=self.candidate()
        self.assertEqual(len(candidates),2); self.assertIn('place',c['agreements']); self.assertIn('house',c['differences'])
        self.assertEqual(c['right']['evidence']['date'],'1840'); self.assertEqual(c['right']['evidence']['text'],'Second evidence')
        self.assertIn('скан 2',c['right']['citation']); self.assertIsNone(c['decision'])
        self.assertEqual(self.engine.db.execute('SELECT COUNT(*) FROM person_links').fetchone()[0],0)

    def test_decisions_are_symmetric_reversible_and_persisted_with_history(self):
        self.decide(self.candidate()); self.assertEqual(self.candidate()['decision']['status'],'confirmed')
        reverse=next(c for c in self.tools.person_candidates({'left':self.right}) if c['right']['record']==self.a)
        self.decide(reverse,'rejected','Different age and family'); self.decide(self.candidate(),'withdrawn','Need more evidence')
        self.assertEqual(self.engine.db.execute('SELECT COUNT(*) FROM person_links').fetchone()[0],1)
        self.assertEqual(self.engine.db.execute('SELECT COUNT(*) FROM person_link_history').fetchone()[0],3)
        self.engine.db.close(); self.engine=Engine(self.root/'library'); self.tools=PeopleTools(self.engine)
        self.assertEqual(self.candidate()['decision']['status'],'withdrawn')

    def test_stale_records_or_decisions_and_missing_reason_are_rejected(self):
        c=self.candidate()
        with self.assertRaises(ValueError): self.decide(c,note=' ')
        self.decide(c)
        with self.assertRaises(ValueError): self.decide(c,'rejected')
        current=self.candidate(); record=next(m for m in self.tools.mentions() if m['record']==self.b)
        self.engine.save_record({'id':self.b,'page':record['page'],'kind':'Інші записи та примітки','person':'Jan Kowalsky','text':'Corrected evidence'})
        self.assertTrue(self.candidate()['stale'])
        with self.assertRaises(ValueError): self.decide(current)
        self.decide(self.candidate(),'rejected','Corrected evidence rules this out'); self.assertFalse(self.candidate()['stale'])

    def test_no_self_links_transitive_merges_or_unreviewed_json_identity(self):
        c=self.candidate(); self.decide(c)
        with self.assertRaises(ValueError): self.tools.person_link({'left':self.left,'right':self.left,'status':'confirmed','note':'self'})
        self.engine.export({'path':str(self.root/'out.json')})
        rows=json.loads((self.root/'out.json').read_text(encoding='utf8'))
        exported=next(r for r in rows if r.get('id')==self.a)['person_links'][0]
        self.assertEqual(exported['status'],'confirmed'); self.assertFalse(exported['stale'])
        self.assertEqual(exported['right']['evidence']['text'],'Second evidence')
        self.assertEqual(len(self.tools.record_links(self.b)),1)
        self.assertEqual(self.engine.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],2)
