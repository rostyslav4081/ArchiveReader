"""Isolated CPU PaddleOCR control on supplied local images; no uploads or accuracy claims."""
import argparse
import hashlib
import html
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
for name in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS']:os.environ[name]='4'
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK']='True'
os.environ['HF_HUB_OFFLINE']='1'
os.environ['PADDLE_PDX_CACHE_HOME']=str(ROOT/'models/paddle-integration/cache')
os.environ['PADDLE_HOME']=str(ROOT/'models/paddle-integration/cache')
os.environ['HF_HOME']=str(ROOT/'models/paddle-integration/huggingface')


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def plain(value):
    if isinstance(value,dict):return {str(k):plain(v) for k,v in value.items() if k not in ['input_img','output_img','rotated_img']}
    if isinstance(value,(tuple,list)):return [plain(v) for v in value]
    if hasattr(value,'tolist'):return value.tolist()
    if isinstance(value,Path):return str(value)
    if value is None or isinstance(value,(str,int,float,bool)):return value
    return {'non_json_visualization_object':type(value).__module__+'.'+type(value).__name__}


def write_report(folder,report):
    temporary=folder/'report.json.partial';temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');os.replace(temporary,folder/'report.json')
    rows=[]
    for case in report['cases']:
        thumbnail=html.escape(os.path.relpath(case['image'],folder).replace('\\','/'),quote=True);texts='\n'.join(case.get('texts',[]));raw=case.get('raw_path')
        rows.append('<tr><td>'+html.escape(case['id'])+'<br>'+html.escape('; '.join(a.get('label','') for a in case['aliases']))+'<br><a href="'+thumbnail+'"><img width="220" src="'+thumbnail+'"></a></td><td>'+html.escape(case['status'])+'<br>'+str(case.get('seconds',''))+' s<br>'+html.escape(case.get('error',''))+'</td><td><pre>'+html.escape(texts[:5000])+'</pre>'+(('<a href="raw/'+html.escape(Path(raw).name)+'">Raw JSON</a>') if raw else '')+'</td></tr>')
    text='<!doctype html><meta charset="utf-8"><title>Local PaddleOCR control</title><style>body{font:16px sans-serif;margin:28px}table{border-collapse:collapse;width:100%}td{border:1px solid #bbb;padding:10px;vertical-align:top}pre{white-space:pre-wrap;max-width:650px}img{max-height:500px;object-fit:contain}</style><h1>Local PaddleOCR control</h1><p>No human reference text: recognition coverage and execution only. Text may be wrong; confidence is not accuracy. No document upload or cloud inference.</p><p>'+html.escape(json.dumps(report.get('summary',{})))+'</p><p>'+html.escape(report.get('startup_error',''))+'</p><table>'+''.join(rows)+'</table>'
    (folder/'report.html').write_text(text,encoding='utf8')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',type=Path,default=ROOT/'test-output/integrations/cases.json');parser.add_argument('--output',type=Path,default=ROOT/'test-output/integrations/paddle');parser.add_argument('--limit',type=int);parser.add_argument('--representative',action='store_true');parser.add_argument('--retry-errors',action='store_true');parser.add_argument('--mkldnn',action='store_true');args=parser.parse_args()
    folder=args.output.resolve();(folder/'raw').mkdir(parents=True,exist_ok=True)
    cases=json.loads(args.manifest.read_text(encoding='utf8'))['cases']
    if args.representative:
        photos=[c for c in cases if any(a.get('origin')=='provided photograph' for a in c['aliases'])][:8];pdf=[];seen=set()
        for case in cases:
            alias=next((a for a in case['aliases'] if str(a.get('source_document','')).lower().endswith('.pdf') and a.get('source_document') not in seen),None)
            if alias:seen.add(alias['source_document']);pdf.append(case)
            if len(pdf)==2:break
        cases=list({c['id']:c for c in photos+pdf}.values())
    if args.limit:cases=cases[:args.limit]
    provenance=json.loads((ROOT/'models/paddle-integration/provenance.json').read_text(encoding='utf8'));models={r['model']:r for r in provenance['models']}
    packages={name:importlib.metadata.version(name) for name in ['paddleocr','paddlepaddle','paddlex','numpy']}
    configuration={'adapter_version':2,'device':'cpu','threads':4,'detector':'PP-OCRv6_small_det','recognizer':'PP-OCRv6_small_rec','language_filter':None,'mkldnn':args.mkldnn,'doc_orientation':False,'doc_unwarping':False,'textline_orientation':False,'raw_policy':'Scalar and array recognition fields retained; visualization-only font objects represented by type; input image pixels retained in source file.','archive_sha256':{k:v['archive_sha256'] for k,v in models.items()},'model_files_sha256':{k:{p.relative_to(Path(v['path'])).as_posix():digest(p) for p in Path(v['path']).rglob('*') if p.is_file()} for k,v in models.items()}}
    signature=hashlib.sha256(json.dumps({'configuration':configuration,'packages':packages},sort_keys=True).encode()).hexdigest();previous={};reused=0
    if (folder/'report.json').exists():
        old=json.loads((folder/'report.json').read_text(encoding='utf8'))
        if old.get('configuration_sha256')==signature:previous={r['id']:r for r in old['cases']}
    report={'tool':'PaddleOCR','status':'running','packages':packages,'configuration':configuration,'configuration_sha256':signature,'manifest':str(args.manifest),'manifest_sha256':digest(args.manifest),'policy':'Local CPU full-page control. No verified ground truth, no CER/WER, no accuracy claim. Raw model outputs are unverified. Originals untouched.','cases':[],'summary':{}}
    started=time.perf_counter()
    try:
        import cv2
        cv2.setNumThreads(4)
        from paddleocr import PaddleOCR
        ocr=PaddleOCR(device='cpu',cpu_threads=4,enable_mkldnn=args.mkldnn,text_detection_model_name='PP-OCRv6_small_det',text_detection_model_dir=models['PP-OCRv6_small_det']['path'],text_recognition_model_name='PP-OCRv6_small_rec',text_recognition_model_dir=models['PP-OCRv6_small_rec']['path'],use_doc_orientation_classify=False,use_doc_unwarping=False,use_textline_orientation=False)
        report['model_load_seconds']=time.perf_counter()-started
    except Exception as exc:
        retained=[previous[c['id']]|c for c in cases if c['id'] in previous and previous[c['id']].get('image_sha256')==c['image_sha256']]
        report.update(status='startup_failed',startup_error=str(exc),traceback=traceback.format_exc(),cases=retained,summary={'attempted':len(retained),'reused_cases':len(retained),'newly_attempted':0,'requested':len(cases)});write_report(folder,report);raise
    for case in cases:
        prior=previous.get(case['id'])
        if prior and prior.get('image_sha256')==case['image_sha256'] and (prior.get('status')!='failed' or not args.retry_errors):
            report['cases'].append(prior|case);reused+=1
        else:
            result=dict(case);start=time.perf_counter()
            try:
                if digest(case['image'])!=case['image_sha256']:raise ValueError('Input checksum changed')
                outputs=[plain(dict(r)) for r in ocr.predict(case['image'])];texts=[str(t) for r in outputs for t in r.get('rec_texts',[])];raw=folder/'raw'/(case['id']+'.json');raw.write_text(json.dumps(outputs,ensure_ascii=False,indent=2),encoding='utf8')
                result.update(status='recognized_unverified' if any(t.strip() for t in texts) else 'empty',texts=texts,recognized_lines=len(texts),characters=sum(len(t) for t in texts),raw_path=str(raw),source_unchanged=digest(case['image'])==case['image_sha256'])
            except Exception as exc:result.update(status='failed',error=str(exc),traceback=traceback.format_exc())
            result['seconds']=time.perf_counter()-start;report['cases'].append(result)
        report['summary']={'attempted':len(report['cases']),'requested':len(cases),'reused_cases':reused,'newly_attempted':len(report['cases'])-reused,'recognized_unverified':sum(r['status']=='recognized_unverified' for r in report['cases']),'empty':sum(r['status']=='empty' for r in report['cases']),'failed':sum(r['status']=='failed' for r in report['cases']),'source_aliases':sum(len(r['aliases']) for r in report['cases'])}
        write_report(folder,report);print(case['id']+': '+report['cases'][-1]['status'],flush=True)
    report['status']='complete';report['run_seconds']=time.perf_counter()-started;write_report(folder,report);print(json.dumps(report['summary']),flush=True)

if __name__=='__main__':main()
