import json
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET


class LocalizationTests(unittest.TestCase):
    def test_all_ui_labels_have_three_translations(self):
        root=Path(__file__).resolve().parents[1]/'src'/'ArchiveReader.Desktop'
        catalog=json.loads((root/'translations.json').read_text(encoding='utf-8'))
        for key, translations in catalog.items():
            self.assertEqual(len(translations),3,key)
            for value in translations:
                self.assertTrue(value.strip(),key)
                self.assertEqual(set(re.findall(r'\{\d+\}',key)),set(re.findall(r'\{\d+\}',value)),key)
        for path in root.glob('*.xaml'):
            for element in ET.parse(path).iter():
                for attr in ['Text','Content','Header','ToolTip','Title']:
                    value=element.get(attr,'')
                    if value!='Українська' and re.search('[А-Яа-яІіЇїЄє]',value):
                        self.assertIn(value,catalog)


if __name__=='__main__': unittest.main()
