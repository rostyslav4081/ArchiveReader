"""Narrow, audited Shapely2 compatibility patch for isolated PERO0.7.0 only."""
import difflib
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
ENV=ROOT/'integration-envs/pero'
TARGET=ENV/'Lib/site-packages/pero_ocr/layout_engines/cnn_layout_engine.py'
REPORT=ROOT/'models/pero-print/compatibility.json'
EXPECTED='dc470c099eaac1c876bd3e89c2cc7a30255c4b8d68beabe7a3385ad642d5fc52'
OLD=b"if region_poly.geom_type == 'MultiPolygon':\n                for poly in region_poly:"
NEW=OLD.replace(b'for poly in region_poly:',b'for poly in region_poly.geoms:')

def main():
    if Path(sys.prefix).resolve()!=ENV.resolve():raise RuntimeError('Use integration-envs/pero interpreter only')
    if importlib.metadata.version('pero-ocr')!='0.7.0':raise RuntimeError('Unexpected PERO version')
    if importlib.metadata.version('shapely')!='2.1.2':raise RuntimeError('Unexpected Shapely version')
    before=TARGET.read_bytes();digest=hashlib.sha256(before).hexdigest()
    if REPORT.exists():
        previous=json.loads(REPORT.read_text(encoding='utf-8'))
        if digest==previous['after_sha256']:
            print('Already patched; exact checksum verified');return
    if digest!=EXPECTED or before.count(OLD)!=1:raise RuntimeError('Unexpected source hash/snippet; refusing edit')
    after=before.replace(OLD,NEW,1)
    compile(after,str(TARGET),'exec')
    report={'package':'pero-ocr','version':'0.7.0','shapely':'2.1.2','target':str(TARGET.relative_to(ROOT)),'before_sha256':digest,'after_sha256':hashlib.sha256(after).hexdigest(),'reason':'Shapely2 MultiPolygon parts are accessed using .geoms, not direct iteration.','official_source':'https://shapely.readthedocs.io/en/stable/migration.html','diff':''.join(difflib.unified_diff(before.decode().splitlines(True),after.decode().splitlines(True),fromfile='before/cnn_layout_engine.py',tofile='after/cnn_layout_engine.py')),'scope':'Isolated integration environment only; no recognition quality claim.'}
    TARGET.write_bytes(after);REPORT.parent.mkdir(parents=True,exist_ok=True);REPORT.write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))

if __name__=='__main__':main()
