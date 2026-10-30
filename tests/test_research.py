import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
from PIL import Image,ImageDraw
from backend.archivereader.engine import Engine
from backend.archivereader.research import ResearchTools,date_bounds
from backend.archivereader.gedcom import GedcomTools,parse
from backend.archivereader.duplicates import DuplicateTools


class ResearchTests(unittest.TestCase):
    def setUp(self):
        output=Path(__file__).resolve().parents[1]/'test-output';output.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=output);self.root=Path(self.temp.name);self.engine=Engine(self.root/'library')
        image=Image.new('RGB',(400,600),'white');draw=ImageDraw.Draw(image)
        for i in range(30):draw.rectangle((15+(i*43)%300,20+i*17,70+(i*43)%300,30+i*17),fill=(i*7,i*5,i*3))
        self.image=image;source=self.root/'scan.png';image.save(source);self.engine.import_file({'path':str(source)});self.page=self.engine.list_pages({})[0]['id']
        self.tools=ResearchTools(self.engine);self.people=[self.tools.person_save({'name':name})['id'] for name in ['Jan','Joannes','Paulus']]
        self.tools.book_profile({'id':self.page,'values':{'calendar':'gregorian'}})
        self.records=[]
        for name,kind,when in [('Jan','Народження','1800'),('Joannes','Смерті','1870')]:
            self.records.append(self.engine.save_record({'page':self.page,'kind':kind,'person':name,'date':when,'text':name+' evidence'})['id'])
        self.mentions=[next(m for m in self.tools.mentions() if m['record']==record and m['field']=='person') for record in self.records]
        for person,mention in zip(self.people,self.mentions):self.tools.person_attach({'person':person,'mention':mention,'signature':mention['signature'],'note':'Checked original'})

    def tearDown(self):self.engine.db.close();self.temp.cleanup()

    def test_merge_split_and_undo_preserve_evidence_and_reject_later_edits(self):
        before=self.tools.snapshot();change=self.tools.card_change({'mode':'merge','source':self.people[1],'target':self.people[0],'note':'Same identity'})
        self.assertEqual(len(self.tools.person_list({})),2);card=self.tools.person_card({'id':self.people[0]});self.assertEqual(len(card['members']),2)
        self.assertIn('Joannes',card['variants']);self.tools.card_undo({'id':change['id']});self.assertEqual(self.tools.snapshot(),before)
        change=self.tools.card_change({'mode':'split','source':self.people[0],'mentions':[self.tools.key(self.mentions[0])],'name':'Different Jan','note':'Different identity'})
        self.assertEqual(len(self.tools.person_card({'id':change['person']})['members']),1)
        self.tools.person_save({'id':change['person'],'name':'Updated name'})
        with self.assertRaises(ValueError):self.tools.card_undo({'id':change['id']})

    def test_merge_blocks_self_relationships_and_cycles_without_partial_changes(self):
        mention=self.mentions[0]
        self.tools.family_save({'left':self.people[0],'right':self.people[1],'kind':'parent','record':mention['record'],'signature':mention['signature'],'note':'Source proof'})
        before=self.tools.snapshot()
        with self.assertRaises(ValueError):self.tools.card_change({'mode':'merge','source':self.people[1],'target':self.people[0],'note':'Mistaken merge'})
        self.assertEqual(self.tools.snapshot(),before)

    def test_fact_specific_crop_preserves_original_and_returns_full_page_without_geometry(self):
        before=Path(self.engine.page(self.page)['path']).read_bytes()
        self.assertTrue(self.tools.fact_crop({'mention':self.mentions[0],'fact':'date'})['whole_page'])
        result=self.tools.fact_crop({'mention':self.mentions[0],'fact':'date','rect':[.1,.1,.4,.2]})
        with Image.open(result['path']) as image:self.assertEqual(image.size,(160,120))
        self.assertFalse(result['whole_page']);self.assertTrue(self.tools.fact_crop({'mention':self.mentions[0],'fact':'person'})['whole_page'])
        self.assertEqual(Path(self.engine.page(self.page)['path']).read_bytes(),before)

    def test_uncertain_calendars_and_overlapping_ranges_do_not_create_false_chronology(self):
        self.assertIsNone(date_bounds('ABT 1800'));self.assertIsNone(date_bounds('JULIAN 1 JAN 1800'));self.assertIsNone(date_bounds('12/03/1800'))
        self.assertIsNotNone(date_bounds('BET 1800 AND 1820'));self.assertIsNone(date_bounds('2020-02-31'))
        self.tools.card_change({'mode':'merge','source':self.people[1],'target':self.people[0],'note':'Checked same identity'})
        self.assertEqual(self.tools.chronology_hints({})['hints'],[])
        self.engine.save_record({'page':self.page,'kind':'Інші записи та примітки','person':'Jan','date':'1900','text':'Later event'})
        mention=self.tools.mentions()[-1];self.tools.person_attach({'person':self.people[0],'mention':mention,'signature':mention['signature'],'note':'Check this event'})
        self.assertEqual(self.tools.chronology_hints({})['hints'][0]['kind'],'after_death')
        self.tools.book_profile({'id':self.page,'values':{'calendar':''}})
        unknown=self.tools.chronology_hints({});self.assertEqual(unknown['hints'],[]);self.assertEqual(unknown['uncompared'],3)

    def test_book_dictionary_requires_verification_and_is_scoped(self):
        with self.assertRaises(ValueError):self.tools.book_dictionary({'page':self.page,'term':'Kowalski','meaning':'Surname'})
        words=self.tools.book_dictionary({'page':self.page,'term':'Kowalski','meaning':'Verified surname','verified':True})
        self.assertEqual(words[0]['term'],'Kowalski');self.assertTrue(self.tools.book_dictionary({'page':self.page,'query':'Kowalsky'}))
        other=self.root/'other.png';Image.new('RGB',(400,600),'red').save(other);doc=self.engine.import_file({'path':str(other)})['id'];page=next(p for p in self.engine.list_pages({}) if p['doc']==doc)
        self.assertEqual(self.tools.book_dictionary({'page':page['id']}),[])

    def test_gedcom_preview_import_roundtrip_and_unmapped_report(self):
        source=self.root/'tree.ged';source.write_text('0 HEAD\n1 GEDC\n2 VERS 7.0\n0 @I1@ INDI\n1 NAME Jan /Kowalski/\n1 BIRT\n2 DATE ABT 1800\n2 SOUR @S1@\n1 OBJE @O1@\n0 @I2@ INDI\n1 NAME Anna\n0 @F1@ FAM\n1 HUSB @I1@\n1 WIFE @I2@\n0 @S1@ SOUR\n1 TITL Archive 42\n0 TRLR\n',encoding='utf8')
        gedcom=GedcomTools(self.engine);preview=gedcom.gedcom_preview({'path':str(source)})
        self.assertEqual(len(preview['people']),2);self.assertTrue(preview['unsupported'])
        gedcom.gedcom_import({'path':str(source),'sha':preview['sha']})
        imported=[p for p in gedcom.person_list({}) if p.get('unverified_import')];self.assertEqual(imported[0]['events'][0]['date'],'ABT 1800')
        self.assertEqual(gedcom.family_list({})[0]['status'],'imported')
        with self.assertRaises(ValueError):gedcom.gedcom_import({'path':str(source),'sha':preview['sha']})
        out=self.root/'out.ged';report=gedcom.gedcom_export({'path':str(out)})
        self.assertTrue(report['warnings']);self.assertTrue(out.with_suffix('.ged.report.json').is_file());self.assertEqual(parse(out.read_bytes())[-1]['tag'],'TRLR')
        self.assertIn('Archive 42',out.read_text(encoding='utf8'));self.assertEqual(self.engine.db.execute('SELECT raw FROM gedcom_imports').fetchone()[0],source.read_bytes())

    def test_perceptual_candidates_find_cropped_image_but_never_auto_confirm(self):
        crop=self.root/'crop.png';self.image.crop((60,90,340,510)).save(crop);self.engine.import_file({'path':str(crop)})
        duplicates=DuplicateTools(self.engine);duplicates.duplicate_index({})
        results=duplicates.duplicate_find({'page':self.page});self.assertTrue(results)
        self.assertGreaterEqual(results[0]['similarity'],.94);self.assertIsNone(results[0]['decision'])
        duplicates.duplicate_decide({'left':results[0]['left'],'right':results[0]['right'],'status':'related_fragment','note':'Only a crop'})
        self.assertEqual(duplicates.duplicate_find({'page':self.page})[0]['decision']['status'],'related_fragment')

    def test_gedcom_imported_claims_are_opt_in_and_coparents_form_one_family(self):
        gedcom=GedcomTools(self.engine)
        for i,(left,right,kind) in enumerate([(0,1,'spouse'),(0,2,'parent'),(1,2,'parent')]):
            gedcom.write('family_links','claim'+str(i),{'left':self.people[left],'right':self.people[right],'kind':kind,'status':'imported','record':None,'signature':None,'note':'User board, not verified','citation':'Board source'})
        path=self.root/'claims.ged'
        self.assertEqual(gedcom.gedcom_export({'path':str(path)})['relationships'],0)
        result=gedcom.gedcom_export({'path':str(path),'include_imported':True})
        self.assertEqual((result['relationships'],result['family_groups']),(3,1))
        preview=gedcom.gedcom_preview({'path':str(path)})
        self.assertEqual(len(preview['families'][0]['parents']),2)
        self.assertEqual(len(preview['families'][0]['children']),1)
        self.assertIn('not independently verified',path.read_text('utf-8'))
        self.assertTrue(all(f['status']=='imported' for f in gedcom.family_list({})))

    def test_gedcom_spouse_does_not_imply_parentage_of_a_child(self):
        gedcom=GedcomTools(self.engine)
        for i,(left,right,kind) in enumerate([(0,1,'spouse'),(0,2,'parent')]):
            gedcom.write('family_links','claim'+str(i),{'left':self.people[left],'right':self.people[right],'kind':kind,'status':'imported','record':None,'signature':None,'note':'Unverified','citation':'Board'})
        path=self.root/'single-parent.ged';gedcom.gedcom_export({'path':str(path),'include_imported':True})
        families=gedcom.gedcom_preview({'path':str(path)})['families']
        self.assertEqual(len(families),2)
        self.assertTrue(all(len(f['parents'])==1 for f in families if f['children']))

    def test_gedcom_media_is_portable_deduplicated_and_never_overwrites_changed_files(self):
        gedcom=GedcomTools(self.engine);person=gedcom.require_person(self.people[0]);person['media_pages']=[self.page,self.page]
        gedcom.write('persons',self.people[0],person)
        path=self.root/'photos.ged';before=Path(self.engine.page(self.page)['path']).read_bytes()
        self.assertEqual(gedcom.gedcom_export({'path':str(path)})['media_files'],0)
        result=gedcom.gedcom_export({'path':str(path),'include_media':True,'extra_media_pages':[self.page]})
        self.assertEqual(result['media_files'],1)
        media=next(n for n in parse(path.read_bytes()) if n['tag']=='OBJE')
        file=next(n for n in media['children'] if n['tag']=='FILE')
        self.assertEqual(next(n['value'] for n in file['children'] if n['tag']=='FORM'),'image/png')
        copied=path.parent/file['value'];self.assertEqual(copied.read_bytes(),before)
        copied.write_bytes(b'Changed outside ArchiveReader')
        with self.assertRaises(ValueError):gedcom.gedcom_export({'path':str(path),'include_media':True})
        self.assertEqual(Path(self.engine.page(self.page)['path']).read_bytes(),before)

    def test_gedcom_document_mentions_have_required_generic_event_payload_and_type(self):
        rec=self.engine.save_record({'page':self.page,'kind':'Інші записи та примітки','person':'Jan','text':'Court record, not a birth or a death'})['id']
        gedcom=GedcomTools(self.engine);mention=next(m for m in gedcom.mentions(records=[rec]) if m['field']=='person')
        gedcom.person_attach({'person':self.people[0],'mention':mention,'signature':mention['signature'],'note':'Court source'})
        path=self.root/'court.ged';gedcom.gedcom_export({'path':str(path)})
        events=[child for node in parse(path.read_bytes()) if node['tag']=='INDI' for child in node['children'] if child['tag']=='EVEN']
        self.assertTrue(events)
        self.assertTrue(all(e['value'] and any(c['tag']=='TYPE' and c['value'] for c in e['children']) for e in events))

    def test_only_confirmed_full_duplicate_with_done_source_is_skipped(self):
        from backend.archivereader.operations import Operations
        other=self.root/'other.png';self.image.resize((200,300)).save(other);doc=self.engine.import_file({'path':str(other)})['id'];target=next(p for p in self.engine.list_pages({}) if p['doc']==doc)['id']
        with self.engine.db:self.engine.db.execute('UPDATE pages SET status="done",text="Source text" WHERE id=?',(self.page,))
        duplicate=DuplicateTools(self.engine);duplicate.duplicate_decide({'left':self.page,'right':target,'status':'related_fragment','note':'Not a full page'})
        operations=Operations(self.engine);job=operations.batch_create({'documents':[doc],'options':{}})['id']
        duplicate.duplicate_decide({'left':self.page,'right':target,'status':'confirmed_full','note':'Checked full-page match'})
        result=operations.batch_step({'job':job});self.assertEqual(result['counts']['skipped'],1);self.assertEqual(self.engine.page(target)['text'],'')

    def test_research_commands_are_registered_in_real_worker(self):
        worker=Path(__file__).resolve().parents[1]/'backend/archivereader/engine.py'
        for command,args in [('card_operations',{}),('chronology_hints',{}),('fact_crop',{'mention':self.mentions[0],'fact':'date'}),('book_dictionary',{'page':self.page}),('duplicate_index',{}),('duplicate_find',{'page':self.page})]:
            result=subprocess.run([sys.executable,'-X','utf8',str(worker)],input=json.dumps({'command':command,'root':str(self.engine.root)}|args),text=True,encoding='utf8',capture_output=True,check=True)
            self.assertTrue(json.loads(result.stdout)['ok'],result.stdout)
