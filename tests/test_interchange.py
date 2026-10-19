from tests.support import workspace_tempdir
import hashlib,json,tempfile,unittest
from pathlib import Path
from PIL import Image
from backend.archivereader.engine import Engine
from backend.archivereader.interchange import InterchangeTools,parse_xml,PAGE,MAX_XML
class InterchangeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=workspace_tempdir();self.root=Path(self.tmp.name);self.e=Engine(self.root/'library');self.t=InterchangeTools(self.e);p=self.root/'image.png';Image.new('RGB',(200,150),'white').save(p);self.e.import_file({'path':str(p)});self.page=self.e.list_pages({})[0]['id'];self.xml=self.root/'external.xml'
  self.raw=f'''<PcGts xmlns="{PAGE}"><Metadata/><Page imageFilename="renamed.png" imageWidth="200" imageHeight="150"><ReadingOrder><OrderedGroup id="order"><RegionRefIndexed index="0" regionRef="r"/></OrderedGroup></ReadingOrder><TextRegion id="r"><Coords points="10,10 190,10 190,100 10,100"/><TextLine id="l" custom="readingOrder {{index:1;}}"><Coords points="20,20 180,20 180,60 20,60"/><Baseline points="20,50 180,52"/><TextEquiv><Unicode>Philippus &amp; Anna</Unicode></TextEquiv></TextLine></TextRegion></Page></PcGts>'''.encode();self.xml.write_bytes(self.raw)
 def tearDown(self):self.e.db.close();self.tmp.cleanup()
 def preview(self):return self.t.interchange_preview({'id':self.page,'path':str(self.xml)})
 def apply(self,r,**values):return self.t.interchange_apply({'id':self.page,'token':r['token'],'confirm':True,'confirm_identity':True}|values)
 def test_preview_persists_exact_xml_and_requires_human_identity(self):
  r=self.preview();self.assertTrue(r['identity_confirmation_required']);self.assertEqual(len(r['parsed']['rows']),2);self.assertEqual(self.t.annotations({'id':self.page}),[])
  stored=self.e.db.execute('SELECT xml,xml_sha256 FROM interchange_previews').fetchone();self.assertEqual(stored['xml'],self.raw);self.assertEqual(stored['xml_sha256'],hashlib.sha256(self.raw).hexdigest())
  with self.assertRaises(ValueError):self.apply(r,confirm_identity=False)
  self.assertEqual(self.apply(r)['added'],2)
  with self.assertRaises(ValueError):self.apply(r)
 def test_apply_never_overwrites_existing_verified_line_or_records(self):
  old=self.t.save_annotation({'page':self.page,'data':{'kind':'line','rect':[.1,.7,.6,.1],'text':'human reference','verified':True}})['id'];r=self.preview();self.apply(r)
  rows=self.t.annotations({'id':self.page});original=next(x for x in rows if x['id']==old);self.assertTrue(original['verified']);self.assertEqual(original['text'],'human reference');self.assertTrue(all(not x['verified'] for x in rows if x['id']!=old));self.assertEqual(self.e.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)
 def test_source_or_annotation_change_rejects_old_token(self):
  r=self.preview();self.t.save_annotation({'page':self.page,'data':{'kind':'line','rect':[.1,.7,.6,.1],'text':'new'}})
  with self.assertRaises(ValueError):self.apply(r)
  r=self.preview();Path(self.e.page(self.page)['path']).write_bytes(b'changed original')
  with self.assertRaises(ValueError):self.apply(r)
 def test_geometry_and_sha_mismatches_block_even_manual_confirmation(self):
  self.xml.write_bytes(self.raw.replace(b'imageWidth="200"',b'imageWidth="201"'));r=self.preview();self.assertIn('dimensions_mismatch',r['blocked'])
  with self.assertRaises(ValueError):self.apply(r)
  self.xml.write_bytes(self.raw.replace(b'<Metadata/>',('<Metadata><Comments>ArchiveReader source_sha256='+'a'*64+'</Comments></Metadata>').encode()));r=self.preview();self.assertIn('source_sha_mismatch',r['blocked'])
  with self.assertRaises(ValueError):self.apply(r)
 def test_unsafe_xml_entities_utf16_size_and_bad_geometry_rejected(self):
  for raw in [b'<!DOCTYPE PcGts [<!ENTITY x SYSTEM "file:///secret">]><PcGts/>','<!DOCTYPE PcGts><PcGts/>'.encode('utf-16'),b'a'*(MAX_XML+1),self.raw.replace(b'20,20 180',b'-20,20 180'),self.raw.replace(b'id="l"',b'id="r"')]:
   with self.subTest(raw=raw[:60]):
    with self.assertRaises(ValueError):parse_xml(raw)
 def test_page_roundtrip_real_polygon_baseline_text_order_and_no_fake_baseline(self):
  self.apply(self.preview());r=self.t.interchange_export({'id':self.page,'format':'page'});parsed=parse_xml(Path(r['path']).read_bytes());line=next(x for x in parsed['rows'] if x['kind']=='line');self.assertEqual(line['text'],'Philippus & Anna');self.assertEqual(line['baseline'],[[.1,50/150],[.9,52/150]]);self.assertEqual(line['reading_order'],2);self.assertEqual(parsed['page_id'],self.page)
  self.assertFalse(self.t.interchange_preview({'id':self.page,'path':r['path']})['identity_confirmation_required'])
  t=self.t.save_annotation({'page':self.page,'data':{'kind':'line','rect':[.1,.7,.6,.1],'text':'manual rectangle'}})['id'];r=self.t.interchange_export({'id':self.page,'format':'page'});import xml.etree.ElementTree as ET
  root=ET.parse(r['path']).getroot();node=next(x for x in root.iter() if x.get('id')=='l_'+t);self.assertFalse(any(x.tag.endswith('Baseline') for x in node))
 def test_alto_roundtrip_line_boxes_and_explicit_order(self):
  self.apply(self.preview());r=self.t.interchange_export({'id':self.page,'format':'alto'});parsed=parse_xml(Path(r['path']).read_bytes());line=next(x for x in parsed['rows'] if x['text']=='Philippus & Anna');self.assertEqual(line['kind'],'line');self.assertIsNotNone(line['baseline']);self.assertEqual(line['reading_order'],2);[self.assertAlmostEqual(actual,expected) for actual,expected in zip(line['rect'],[.1,20/150,.8,40/150])]
 def test_minor_overflow_needs_explicit_clipping_and_keeps_raw_geometry(self):
  self.xml.write_bytes(self.raw.replace(b'190,10',b'202,10').replace(b'190,100',b'202,100'))
  r=self.preview();self.assertTrue(r['clipping_confirmation_required']);self.assertTrue(r['parsed']['rows'][0]['geometry_clipped']);self.assertIn('202,10',r['parsed']['rows'][0]['original_geometry']['polygon'])
  with self.assertRaises(ValueError):self.apply(r)
  self.assertEqual(self.apply(r,confirm_clipping=True)['added'],2)
  imported=self.t.annotations({'id':self.page})[0];self.assertTrue(imported['interchange']['geometry_clipped']);self.assertIn('202,10',imported['interchange']['original_geometry']['polygon'])
  self.xml.write_bytes(self.raw.replace(b'190,10',b'250,10'))
  with self.assertRaises(ValueError):self.preview()
 def test_missing_external_ids_generated_explicitly_and_no_scalar_baseline_invention(self):
  raw=b'<alto xmlns="http://www.loc.gov/standards/alto/ns-v2#"><Description><MeasurementUnit>pixel</MeasurementUnit></Description><Layout><Page WIDTH="200" HEIGHT="150"><PrintSpace><TextBlock ID="b" HPOS="10" VPOS="10" WIDTH="180" HEIGHT="90"><TextLine HPOS="20" VPOS="20" WIDTH="160" HEIGHT="40" BASELINE="50"><String CONTENT="Anna"/></TextLine></TextBlock></PrintSpace></Page></Layout></alto>'
  parsed=parse_xml(raw);line=parsed['rows'][1];self.assertTrue(line['external_id_generated']);self.assertIsNone(line['original_external_id']);self.assertIsNone(line['baseline']);self.assertEqual(line['original_geometry']['scalar_baseline'],'50')
 def test_invalid_child_geometry_rolls_back_all_annotations(self):
  self.xml.write_bytes(self.raw.replace(b'10,10 190,10 190,100 10,100',b'40,10 80,10 80,100 40,100'))
  r=self.preview()
  with self.assertRaises(ValueError):self.apply(r)
  self.assertEqual(self.t.annotations({'id':self.page}),[]);self.assertEqual(self.e.db.execute('SELECT COUNT(*) FROM annotation_history').fetchone()[0],0)
if __name__=='__main__':unittest.main()
