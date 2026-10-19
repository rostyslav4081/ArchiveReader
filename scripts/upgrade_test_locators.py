"""Upgrade reviewed source locators in isolated test material, preserving original files."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.sources import SourceTools


def main():
    folder=ROOT/'test-output/philip-source-research';catalog=json.loads((folder/'lipivtsi-catalog.json').read_text(encoding='utf8'))
    scans={v['viewer_url']:v for b in catalog['metric_books'] for v in b.get('scans',[])}
    manifests=['attach-philip.json','stephanus-1838-attachments.json','attach-agad-source.json']
    e=Engine(ROOT/'test-output/htr-lab-20261015/library');tools=SourceTools(e);changed=[]
    try:
        for name in manifests:
            path=folder/name;manifest=json.loads(path.read_text(encoding='utf8'))
            for item in manifest['evidence']:
                values=item['source']['page_values'];url=values['page_url'];scan=scans.get(url)
                if scan:values.update(image_number=str(scan['scan_position']),scan_label=scan['archive_image_label'])
                if item['id'].startswith('philip-death'):values.update(original_page='90',entry_number='18')
                elif item['id']=='lipivtsi-1838-stephanus-birth':values.update(original_page='28')
                elif item['id']=='lipivtsi-1838-stephanus-death':values.update(original_page='92')
                elif item['id'].startswith('agad-298-338'):values.update(original_page='16–17',image_number='13',scan_label='0013')
                doc=e.db.execute('SELECT id FROM documents WHERE sha=?',(item['sha256'],)).fetchone()
                if doc:
                    page=e.db.execute('SELECT id FROM pages WHERE doc=? ORDER BY num',(doc['id'],)).fetchone()['id'];card=tools.source_card({'id':page});updated=tools.source_card({'id':page,'page_values':card['page_values']|values,'expected':card['signature']});changed.append({'page':page,'citation':updated['citation']})
            path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        (folder/'locator-migration.json').write_text(json.dumps(changed,ensure_ascii=False,indent=2),encoding='utf8');print(str(len(changed))+' source locators upgraded')
    finally:e.db.close()

if __name__=='__main__':main()
