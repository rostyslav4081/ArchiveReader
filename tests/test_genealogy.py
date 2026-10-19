import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
from PIL import Image
from backend.archivereader.engine import Engine
from backend.archivereader.genealogy import GenealogyTools
from backend.archivereader.extraction import ExtractionTools


class GenealogyTests(unittest.TestCase):
    def setUp(self):
        output=Path(__file__).resolve().parents[1]/'test-output';output.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=output);self.root=Path(self.temp.name)
        image=self.root/'scan.png';Image.new('RGB',(200,300),'white').save(image)
        self.engine=Engine(self.root/'library');self.engine.import_file({'path':str(image)})
        self.page=self.engine.list_pages({})[0]['id'];self.tools=GenealogyTools(self.engine)
        self.record=self.engine.save_record({'page':self.page,'kind':'Народження','person':'Jan','date':'12.03.1832','text':'Nomen: Jan; pater: Paulus; mater: Anna\nDomus 34\n12.03.1832'})['id']
        self.mention=next(m for m in self.tools.mentions() if m['record']==self.record)
        self.people=[self.tools.person_save({'name':name})['id'] for name in ['Jan','Paulus','Anna']]

    def tearDown(self):self.engine.db.close();self.temp.cleanup()

    def attach(self,person,mention=None):
        mention=mention or self.mention
        return self.tools.person_attach({'person':person,'mention':mention,'signature':mention['signature'],'note':'Checked original'})

    def family(self,left,right,kind='parent'):
        mention=next(m for m in self.tools.mentions() if m['record']==self.record)
        return self.tools.family_save({'left':left,'right':right,'kind':kind,'record':self.record,'signature':mention['signature'],'note':'Explicit record evidence'})

    def test_membership_is_explicit_unique_stale_and_reversible(self):
        self.assertEqual(self.tools.person_card({'id':self.people[0]})['members'],[])
        card=self.attach(self.people[0]);self.assertEqual(card['variants'],['Jan']);self.assertFalse(card['members'][0]['stale'])
        with self.assertRaises(ValueError):self.attach(self.people[1])
        self.engine.save_record({'id':self.record,'page':self.page,'kind':'Народження','person':'Joannes','text':'Corrected original'})
        card=self.tools.person_card({'id':self.people[0]});self.assertTrue(card['members'][0]['stale']);self.assertEqual(card['members'][0]['mention']['name'],'Jan')
        self.assertEqual(card['members'][0]['current']['name'],'Joannes')
        with self.assertRaises(ValueError):self.attach(self.people[0])
        self.tools.person_detach({'person':self.people[0],'mention':self.tools.key(self.mention)})
        self.assertEqual(self.tools.person_card({'id':self.people[0]})['members'],[])

    def test_parent_cycles_spouse_duplicates_and_withdrawal_after_record_change(self):
        parent=self.family(self.people[1],self.people[0]);self.family(self.people[1],self.people[2],'spouse')
        with self.assertRaises(ValueError):self.family(self.people[0],self.people[1])
        with self.assertRaises(ValueError):self.family(self.people[2],self.people[1],'spouse')
        self.engine.save_record({'id':self.record,'page':self.page,'kind':'Народження','person':'Changed','text':'Changed evidence'})
        self.assertTrue(self.tools.family_list({})[0]['stale'])
        self.tools.family_save(parent|{'status':'withdrawn','note':'Needs rechecking'})
        self.assertEqual(self.tools.family_list({})[0]['status'],'withdrawn')

    def test_json_export_and_reopen_preserve_evidence(self):
        self.attach(self.people[0]);self.family(self.people[1],self.people[0]);path=self.root/'tree.json'
        self.tools.genealogy_export({'path':str(path)});data=json.loads(path.read_text(encoding='utf8'))
        self.assertEqual(len(data['people']),3);self.assertIn('скан 1',data['relationships'][0]['citation'])
        self.assertEqual(data['people'][0]['members'][0]['mention']['evidence']['text'],self.mention['evidence']['text'])
        self.engine.db.close();self.engine=Engine(self.root/'library');self.tools=GenealogyTools(self.engine)
        self.assertEqual(len(self.tools.person_card({'id':self.people[0]})['members']),1)

    def test_fields_are_bound_to_exact_text_and_apply_only_selected_unverified(self):
        extraction=ExtractionTools(self.engine);run=extraction.field_propose({'page':self.page,'record':self.record})
        for proposal in run['candidates']:self.assertEqual(run['text'][proposal['start']:proposal['end']].strip(),proposal['value'])
        index=next(i for i,c in enumerate(run['candidates']) if c['field']=='house')
        extraction.field_apply({'run':run['id'],'selected':[index]})
        record=self.engine.details({'id':self.page})['records'][0]
        self.assertEqual(record['house'],'34');self.assertFalse(record['verified']);self.assertEqual(record['related1'],'')
        output=self.root/'fields.json';self.engine.export({'path':str(output)})
        provenance=json.loads(output.read_text(encoding='utf8'))[0]['field_evidence'][0]
        self.assertEqual(provenance['selected'][0]['value'],'34');self.assertEqual(provenance['source_text'],run['text'])
        with self.assertRaises(ValueError):extraction.field_apply({'run':run['id'],'selected':[index]})

    def test_field_replacement_and_duplicate_choices_require_explicit_review(self):
        extraction=ExtractionTools(self.engine)
        self.engine.save_record({'id':self.record,'page':self.page,'kind':'Народження','person':'Other','text':'Nomen: Jan\nNomen: Ivan'})
        run=extraction.field_propose({'page':self.page,'record':self.record})
        with self.assertRaises(ValueError):extraction.field_apply({'run':run['id'],'selected':[0,1],'replace':True})
        with self.assertRaises(ValueError):extraction.field_apply({'run':run['id'],'selected':[0]})
        extraction.field_apply({'run':run['id'],'selected':[0],'replace':True})
        self.assertEqual(self.engine.details({'id':self.page})['records'][0]['person'],'Jan')

    def test_new_commands_are_registered_in_the_real_worker_bridge(self):
        worker=Path(__file__).resolve().parents[1]/'backend/archivereader/engine.py'
        for command,args in [('person_list',{}),('family_list',{}),('genealogy_mentions',{'page':self.page}),('field_propose',{'page':self.page,'record':self.record}),('batch_books',{}),('batch_status',{}),('evaluation_coverage',{})]:
            result=subprocess.run([sys.executable,'-X','utf8',str(worker)],input=json.dumps({'command':command,'root':str(self.engine.root)}|args),text=True,encoding='utf8',capture_output=True,check=True)
            self.assertTrue(json.loads(result.stdout)['ok'],command+result.stdout)
