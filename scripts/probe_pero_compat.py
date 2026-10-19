"""One actual local photo probe, separate from the running PERO109 report."""
import configparser
import hashlib
import json
import os
from pathlib import Path
import time
import traceback

for key in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMBA_NUM_THREADS'):os.environ[key]='2'
ROOT=Path(__file__).resolve().parents[1]

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    import cv2
    import torch
    from pero_ocr.document_ocr.page_parser import PageParser
    from pero_ocr.core.layout import PageLayout
    cv2.setNumThreads(1);torch.set_num_threads(2)
    folder=ROOT/'test-output/integrations/pero-compat-probe';folder.mkdir(parents=True,exist_ok=True)
    case=json.loads((ROOT/'test-output/integrations/cases.json').read_text(encoding='utf-8'))['cases'][0]
    report={'case':case,'cpu_threads':2,'policy':'Local printed-model execution probe on actual manuscript photo. No ground truth or accuracy claim.','compatibility':json.loads((ROOT/'models/pero-print/compatibility.json').read_text(encoding='utf-8'))}
    started=time.perf_counter()
    try:
        assert digest(case['image'])==case['image_sha256']
        config_path=ROOT/'models/pero-print/engine/pero_eu_cz_print_newspapers_2022-09-26/config_cpu.ini'
        config=configparser.ConfigParser();config.read(config_path,encoding='utf-8')
        pipeline=PageParser(config,device=torch.device('cpu'),config_path=str(config_path.parent))
        report['model_load_seconds']=time.perf_counter()-started
        image=cv2.imread(case['image']);page=pipeline.process_page(image,PageLayout(id=case['id'],page_size=image.shape[:2]))
        lines=[{'id':line.id,'text':line.transcription or '','polygon':line.polygon.tolist() if line.polygon is not None else None,'baseline':line.baseline.tolist() if line.baseline is not None else None} for line in page.lines_iterator()]
        (folder/'lines.json').write_text(json.dumps(lines,ensure_ascii=False,indent=2),encoding='utf-8')
        (folder/'text.txt').write_text('\n'.join(line['text'] for line in lines),encoding='utf-8')
        page.to_pagexml(str(folder/'page.xml'));page.to_altoxml(str(folder/'alto.xml'))
        report.update(status='recognized_unverified' if any(line['text'].strip() for line in lines) else 'empty',lines=len(lines),regions=len(page.regions),patch_runtime_fix_validated=True,outputs=['lines.json','text.txt','page.xml','alto.xml'])
    except Exception:report.update(status='failed',error=traceback.format_exc(),patch_runtime_fix_validated=False)
    report['source_unchanged']=digest(case['image'])==case['image_sha256'];report['seconds']=time.perf_counter()-started
    (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
