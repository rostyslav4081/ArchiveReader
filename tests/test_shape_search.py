import json,unittest
from pathlib import Path
from PIL import Image,ImageDraw
from tests import test_layout as fixtures
from backend.archivereader.shape_search import ShapeSearch,features,dtw

class ShapeTests(unittest.TestCase):
 def setUp(self):self.f=fixtures.LayoutTests();self.f.setUp()
 def tearDown(self):self.f.tearDown()
 def test_stretched_strokes_are_closer_than_unrelated_shape(self):
  image=Image.new('L',(120,40),'white');d=ImageDraw.Draw(image)
  for x in [10,30,50,70]:d.line((x,30,x+12,7,x+20,30),fill=0,width=3)
  stretched=image.resize((150,40));other=Image.new('L',(120,40),'white');ImageDraw.Draw(other).ellipse((5,2,110,37),outline=0,width=5)
  self.assertIsNone(features(Image.new('L',(50,30),'white')))
  self.assertLess(dtw(features(image)[0],features(stretched)[0]),dtw(features(image)[0],features(other)[0]))
 def test_same_book_only_no_label_promotion_or_annotation_changes(self):
  image=Image.new('RGB',(200,300),'white');d=ImageDraw.Draw(image)
  for y in [30,90]:d.text((20,y),'John',fill='black')
  source=self.f.root/'real-shapes.png';image.save(source);doc=self.f.engine.import_file({'path':str(source)});page=self.f.engine.db.execute('select id from pages where doc=?',(doc['id'],)).fetchone()[0];s=ShapeSearch(self.f.engine)
  s.save_annotation({'page':page,'data':{'kind':'line','rect':[.08,.28,.5,.07],'text':'Whole line context','verified':True}})
  s.save_annotation({'page':self.f.page['id'],'data':{'kind':'line','rect':[.1,.1,.5,.1],'text':'Other book','verified':True}})
  before=s.annotations({'id':page});r=s.shape_search({'id':page,'rect':[.08,.08,.5,.1]})
  self.assertTrue(r['results']);self.assertEqual(s.annotations({'id':page}),before)
  for candidate in r['results']:
   self.assertEqual(candidate['page'],page);self.assertIsNone(candidate['fragment_text']);self.assertFalse(candidate['verified']);self.assertFalse(candidate['writer_known']);self.assertNotEqual(candidate['whole_region_text'],'Other book')
  Path(self.f.engine.page(page)['path']).write_bytes(b'changed')
  with self.assertRaises(ValueError):s.shape_search({'id':page,'rect':[.08,.08,.5,.1]})
