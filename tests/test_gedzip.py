import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from PIL import Image
from backend.archivereader.engine import Engine
from backend.archivereader.gedcom import GedcomTools

GED='''0 HEAD
1 GEDC
2 VERS 7.0
0 @I1@ INDI
1 NAME Jan /Skowyra/
1 OBJE @M1@
0 @I2@ INDI
1 NAME Julia /Skowyra/
0 @I3@ INDI
1 NAME Anna /Skowyra/
1 SOUR @S1@
0 @F1@ FAM
1 HUSB @I1@
1 WIFE @I2@
1 CHIL @I3@
1 OBJE @M2@
0 @S1@ SOUR
1 TITL Archive case 7, page 43
1 TEXT Original reading
1 OBJE @M3@
0 @M1@ OBJE
1 FILE media/one.png
0 @M2@ OBJE
1 FILE media/two.png
0 @M3@ OBJE
1 FILE media/three.png
0 TRLR
'''

class GedzipTests(unittest.TestCase):
    def setUp(self):
        output=Path(__file__).resolve().parents[1]/'test-output';output.mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=output);self.root=Path(self.tmp.name)
        self.engine=Engine(self.root/'library');self.tools=GedcomTools(self.engine)
        self.photos={}
        for name,color in [('one','red'),('two','green'),('three','blue')]:
            buffer=io.BytesIO();Image.new('RGB',(30,40),color).save(buffer,format='PNG');self.photos['media/'+name+'.png']=buffer.getvalue()
    def tearDown(self):self.engine.db.close();self.tmp.cleanup()
    def package(self,files=None):
        path=self.root/'tree.gdz'
        with zipfile.ZipFile(path,'w') as z:
            z.writestr('gedcom.ged',GED)
            for name,raw in (self.photos if files is None else files).items():z.writestr(name,raw)
        return path
    def test_roundtrip_preserves_photos_people_family_and_source_links(self):
        path=self.package();preview=self.tools.gedcom_preview({'path':str(path)})
        self.assertEqual(len(preview['media']),3)
        result=self.tools.gedcom_import({'path':str(path),'sha':preview['sha']})
        self.assertEqual(result['media_files'],3)
        people=self.tools.person_list({});jan=next(p for p in people if p['name']=='Jan Skowyra')
        anna=next(p for p in people if p['name']=='Anna Skowyra')
        self.assertEqual(len(jan['media_pages']),1);self.assertEqual(len(anna['media_pages']),1)
        card=self.tools.person_card({'id':anna['id']})
        self.assertFalse(card['members'][0]['stale'])
        self.assertIn('Original reading',card['members'][0]['mention']['evidence']['text'])
        family=next(f for f in self.tools.family_list({}) if f['kind']=='spouse')
        self.assertEqual(len(family['documents']),1)
        self.assertTrue(Path(self.engine.page(family['documents'][0]['page'])['path']).is_file())
        out=self.root/'export.gdz';self.tools.gedcom_export({'path':str(out),'include_imported':True})
        with zipfile.ZipFile(out) as z:
            restored=[z.read(n) for n in z.namelist() if n.endswith('.png')]
        self.assertEqual(set(restored),set(self.photos.values()))
        self.assertEqual(len(self.tools.gedcom_preview({'path':str(out)})['media']),3)
        plain=self.root/'export.ged';self.tools.gedcom_export({'path':str(plain),'include_imported':True,'include_media':True})
        self.assertEqual(len(list(plain.with_suffix('.media').glob('*.png'))),3)
    def test_changed_package_rejected_even_when_gedcom_is_unchanged(self):
        path=self.package();preview=self.tools.gedcom_preview({'path':str(path)})
        with zipfile.ZipFile(path,'a') as z:z.writestr('extra.txt','changed')
        with self.assertRaises(ValueError):self.tools.gedcom_import({'path':str(path),'sha':preview['sha']})
        self.assertEqual(self.tools.person_list({}),[])
    def test_missing_or_corrupt_photo_does_not_partially_import(self):
        path=self.package({'media/one.png':b'broken','media/two.png':self.photos['media/two.png'],'media/three.png':self.photos['media/three.png']})
        preview=self.tools.gedcom_preview({'path':str(path)})
        with self.assertRaises((ValueError,OSError)):self.tools.gedcom_import({'path':str(path),'sha':preview['sha']})
        self.assertEqual(self.tools.person_list({}),[]);self.assertEqual(self.engine.list_pages({}),[])
        path=self.package({'media/one.png':self.photos['media/one.png']})
        with self.assertRaises(ValueError):self.tools.gedcom_preview({'path':str(path)})
    def test_unsafe_zip_path_is_rejected_without_extraction(self):
        path=self.package(self.photos|{'../outside.png':b'bad'})
        with self.assertRaises(ValueError):self.tools.gedcom_preview({'path':str(path)})
        self.assertFalse((self.root/'outside.png').exists())

if __name__=='__main__':unittest.main()
