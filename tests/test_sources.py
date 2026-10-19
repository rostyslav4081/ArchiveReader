import csv
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from PIL import Image
from backend.archivereader.engine import Engine
from backend.archivereader.sources import SourceTools


class SourceTests(unittest.TestCase):
    def setUp(self):
        output=Path(__file__).resolve().parents[1]/'test-output'; output.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=output); self.root=Path(self.temp.name)
        image=self.root/'book.tif'; Image.new('RGB',(200,300),'white').save(image,save_all=True,append_images=[Image.new('RGB',(200,300),'red')])
        self.engine=Engine(self.root/'library'); self.engine.import_file({'path':str(image)})
        self.pages=self.engine.list_pages({}); self.sources=SourceTools(self.engine)

    def tearDown(self): self.engine.db.close(); self.temp.cleanup()

    def test_book_metadata_is_shared_but_folios_and_urls_are_page_specific(self):
        first,second=[p['id'] for p in self.pages]
        card=self.sources.source_card({'id':first,'book':{'archive':'Archive A','fonds':'42','inventory':'7','file':'9','url':'https://example.org/book'},'page_values':{'folio':'12 зв.','page_url':'https://example.org/page/1'}})
        self.assertIn('арк. 12 зв.',card['citation']); self.assertIn('скан 1',card['citation'])
        other=self.sources.source_card({'id':second})
        self.assertEqual(other['book']['archive'],'Archive A'); self.assertEqual(other['page_values']['folio'],'')
        self.assertIn('https://example.org/book',other['citation']); self.assertIn('скан 2',other['citation'])
        self.sources.source_card({'id':second,'page_values':{'folio':'13'}})
        self.assertEqual(self.sources.source_card({'id':first})['page_values']['folio'],'12 зв.')

    def test_derived_page_keeps_original_locator_until_its_card_is_saved(self):
        page=self.pages[1]
        self.sources.source_card({'id':page['id'],'book':{'archive':'Archive A'},'page_values':{'folio':'13'}})
        photo=self.sources.prepare_photo({'id':page['id'],'mode':'rotate','angle':90})
        doc=self.sources.import_derivative(photo)[0]['id']; child=next(p for p in self.engine.list_pages({}) if p['doc']==doc)
        card=self.sources.source_card({'id':child['id']})
        self.assertTrue(card['inherited']); self.assertEqual(card['origin_page'],page['id']); self.assertEqual(card['scan_page'],2)
        self.assertIn('арк. 13',card['citation'])
        saved=self.sources.source_card({'id':child['id'],'page_values':{'folio':'13 verso'}})
        self.assertFalse(saved['inherited']); self.assertEqual(saved['book']['archive'],'Archive A')
        self.assertEqual(self.sources.source_card({'id':page['id']})['page_values']['folio'],'13')

    def test_original_locators_are_distinct_and_survive_exports(self):
        page=self.pages[0]['id']
        card=self.sources.source_card({'id':page,'page_values':{'folio':'45v','original_page':'90','image_number':'63','scan_label':'9062','entry_number':'18'}})
        for value in ['арк. 45v','стор. 90','скан 63','зображення 9062','запис 18']:self.assertIn(value,card['citation'])
        self.assertEqual(card['scan_page'],1)
        self.engine.export({'path':str(self.root/'locators.json')})
        row=json.loads((self.root/'locators.json').read_text(encoding='utf8'))[0]
        for key,value in [('original_page','90'),('image_number','63'),('scan_label','9062'),('entry_number','18')]:self.assertEqual(row['source_'+key],value)

    def test_stale_edits_and_unsafe_openable_links_are_rejected(self):
        page=self.pages[0]['id']; old=self.sources.source_card({'id':page})
        self.sources.source_card({'id':page,'book':{'archive':'Changed'}})
        with self.assertRaises(ValueError): self.sources.source_card({'id':page,'book':{'archive':'Old'},'expected':old['signature']})
        for url in ['file:///C:/program.exe','javascript:alert(1)','https://']:
            with self.assertRaises(ValueError): self.sources.source_card({'id':page,'book':{'url':url}})
        self.assertEqual(self.sources.source_card({'id':page})['book']['archive'],'Changed')

    def test_all_exports_keep_source_fields_and_excel_columns_beyond_z(self):
        page=self.pages[0]['id']
        self.sources.source_card({'id':page,'book':{'archive':'Archive & A','fonds':'=1+1','place':'Village','url':'https://example.org/book'},'page_values':{'folio':'12r'}})
        for suffix in ['json','csv','txt','xlsx']: self.engine.export({'path':str(self.root/('out.'+suffix))})
        data=json.loads((self.root/'out.json').read_text(encoding='utf8'))
        row=next(r for r in data if r['page']==1)
        self.assertEqual(row['source_archive'],'Archive & A'); self.assertEqual(row['source_folio'],'12r')
        self.assertEqual(row['source_card']['page_values']['folio'],'12r')
        with (self.root/'out.csv').open(encoding='utf-8-sig',newline='') as source: rows=list(csv.DictReader(source))
        self.assertEqual(rows[0]['source_fonds'],"'=1+1")
        self.assertIn('арк. 12r',(self.root/'out.txt').read_text(encoding='utf8'))
        ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        with zipfile.ZipFile(self.root/'out.xlsx') as archive: xml=ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        self.assertEqual(xml.find('s:autoFilter',ns).get('ref'),'A1:AL3')
        self.assertEqual(xml.find(".//s:c[@r='AA2']/s:is/s:t",ns).text,'Village')
        self.assertEqual(xml.find(".//s:c[@r='W2']/s:is/s:t",ns).text,'=1+1')
        self.assertFalse(xml.findall('.//s:f',ns))

if __name__=='__main__': unittest.main()
