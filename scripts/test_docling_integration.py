"""Reproduce local Docling integration trials in its separate pinned environment.

Install docling[easyocr]==2.139.0 in integration-envs/docling (never core .venv).
Run with integration-envs/docling/Scripts/python.exe -X utf8 this_script.py:
  --profile ocr : eight full photos and PDF page 2, ten functional OCR cases.
  --profile structure --manifest test-output/integrations/cases.json : all prepared
    cases, OCR disabled, empty layout regions retained, table processing enabled.
Checkpoints include manifest hash/profile. No upload, inferred ground truth or CER.
"""
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
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'test-output/integrations/docling';CACHE=OUT/'cache'
for name,value in {'OMP_NUM_THREADS':'4','MKL_NUM_THREADS':'4','OPENBLAS_NUM_THREADS':'4','TOKENIZERS_PARALLELISM':'false','HF_HOME':str(CACHE/'huggingface'),'TORCH_HOME':str(CACHE/'torch'),'XDG_CACHE_HOME':str(CACHE),'HF_HUB_DISABLE_XET':'1'}.items():os.environ[name]=value


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def write_report(report):
    report['processed_cases']=len(report.get('cases',[]));report['successful_cases']=sum(c.get('status','').lower() in ['success','conversionstatus.success'] for c in report.get('cases',[]));report['failed_cases']=sum(c.get('status')=='error' or c.get('status','').lower() in ['failure','conversionstatus.failure'] for c in report.get('cases',[]));report['partial_cases']=sum('partial' in c.get('status','').lower() for c in report.get('cases',[]))
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    esc=html.escape;parts=['<!doctype html><meta charset="utf-8"><title>Docling local integration test</title><style>body{font:16px/1.5 system-ui;max-width:1100px;margin:40px auto;padding:0 20px}td,th{padding:10px;border:1px solid #ddd;text-align:left;vertical-align:top}table{border-collapse:collapse;width:100%}pre{white-space:pre-wrap;background:#f5f4ef;padding:15px}.note{padding:15px;background:#fff0ce}</style><h1>Docling: перевірка на наданих файлах</h1><p class="note">Обсяг: '+esc(report['scope'])+'. Це тест структури/OCR і виконання, а не доведена точність читання рукопису. Еталонних транскрипцій немає; CER/WER не обчислюються. Файли обробляються локально, без завантаження в зовнішні сервіси.</p><p>Версія: '+esc(str(report.get('versions',{})))+'</p><table><tr><th>Файл / сторінка</th><th>Стан</th><th>Час, с</th><th>Структура</th><th>Результати</th></tr>']
    for case in report.get('cases',[]):
        files=case.get('outputs',{});links=' · '.join('<a href="'+esc(value,quote=True)+'">'+esc(key)+'</a>' for key,value in files.items());summary='Текстових блоків: '+str(case.get('text_items',0))+'; таблиць: '+str(case.get('tables',0))+'; символів Markdown: '+str(case.get('markdown_characters',0));parts.append('<tr><td>'+esc(case['id'])+' · '+str(case['selected_page'])+'</td><td>'+esc(case.get('status',''))+'</td><td>'+str(case.get('seconds','—'))+'</td><td>'+summary+'</td><td>'+links+'</td></tr>')
        if case.get('error'):parts.append('<tr><td colspan="5"><pre>'+esc(case['error'])+'</pre></td></tr>')
    parts.append('</table><h2>Межі перевірки</h2><ul>'+''.join('<li>'+esc(x)+'</li>' for x in report['limitations'])+'</ul><p><a href="report.json">Повний звіт</a> · <a href="environment-freeze.txt">Версії залежностей</a></p>');(OUT/'report.html').write_text('\n'.join(parts),encoding='utf-8')


def main():
    global OUT
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',type=Path);parser.add_argument('--profile',choices=['ocr','structure'],default='ocr');parser.add_argument('--retry-errors',action='store_true');args=parser.parse_args()
    OUT=ROOT/'test-output/integrations'/('docling-ocr' if args.profile=='ocr' else 'docling-structure')
    OUT.mkdir(parents=True,exist_ok=True);CACHE.mkdir(parents=True,exist_ok=True)
    freeze=ROOT/'test-output/integrations/docling/environment-freeze.txt'
    if freeze.exists():(OUT/'environment-freeze.txt').write_bytes(freeze.read_bytes())
    manifest_data=json.loads(args.manifest.read_text(encoding='utf-8')) if args.manifest else None
    sources=[{'id':c['id'],'source':c['image'],'expected_sha':c['image_sha256'],'aliases':c['aliases'],'selected_page':1} for c in manifest_data['cases']] if manifest_data else json.loads((ROOT/'test-output/htr-lab-20261015/report.json').read_text(encoding='utf-8'))['files']
    manifest_sha=(sha(args.manifest) if args.manifest else 'functional-10-cases')+':'+args.profile+(':keep-empty-v1' if args.profile=='structure' else '')
    previous=json.loads((OUT/'report.json').read_text(encoding='utf-8')) if (OUT/'report.json').exists() else {}
    if previous and previous.get('manifest_sha')!=manifest_sha:
        (OUT/'previous-report.json').write_text(json.dumps(previous,ensure_ascii=False,indent=2),encoding='utf-8')
        previous={}
    report={'tool':'Docling','requested_version':'2.139.0','environment':sys.executable,'cpu_threads':4,'scope':'8 full image pages plus selected page 2 of each of two PDFs; not whole 77-page PDF OCR.','model_execution':'Local CPU only; remote inference disabled; network used solely for installing packages/downloading public weights.','versions':{},'cases':[],'verified_reference_lines':0,'limitations':['No verified reference transcription: structure/text outputs are unverified and no CER/WER is reported.','Docling layout/table output is not evidence that handwritten text or family relationships are correct.','The first conversion includes model initialization/download time; later cases can reuse models.','Language options are Latin-script English/Polish/German/Czech; historical handwriting remains outside a validated test set.']}
    for name in ['docling','docling-slim','docling-core','docling-ibm-models','easyocr','torch','torchvision','transformers']:
        try:report['versions'][name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:report['versions'][name]=None
    report['manifest_sha']=manifest_sha;report['manifest']=str(args.manifest) if args.manifest else None;report['expected_cases']=len(sources);report['phase']='initializing'
    report['profile']=args.profile;report['ocr_enabled']=args.profile=='ocr'
    report['pipeline_options']={'do_ocr':args.profile=='ocr','do_table_structure':True,'keep_empty_clusters':args.profile=='structure','enable_remote_services':False,'device':'cpu','threads':4}
    if args.profile=='structure':report['limitations']=['OCR is disabled deliberately: this profile tests layout/table processing, not handwritten transcription.','Image-only text blocks may be omitted from the assembled document when no OCR text is available. Raw page layout clusters are exported separately.','Table cells and reading order require manual review; empty text/cells are not successful recognition.','No verified ground truth: no CER/WER or structural accuracy score is reported.']
    if manifest_data:report['scope']=manifest_data['scope']+' Preparation: '+manifest_data['preparation']
    completed={c['id']:c for c in previous.get('cases',[])}
    write_report(report)
    converter=None;initialization_error=None
    try:
        import torch
        torch.set_num_threads(4)
        import cv2
        cv2.setNumThreads(4)
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions,EasyOcrOptions
        from docling.datamodel.accelerator_options import AcceleratorOptions,AcceleratorDevice
        from docling.document_converter import DocumentConverter,PdfFormatOption,ImageFormatOption
        options=PdfPipelineOptions(do_ocr=args.profile=='ocr',do_table_structure=True)
        if args.profile=='structure':options.layout_options.keep_empty_clusters=True
        options.accelerator_options=AcceleratorOptions(num_threads=4,device=AcceleratorDevice.CPU)
        options.ocr_options=EasyOcrOptions(lang=['en','pl','de','cs'],use_gpu=False,force_full_page_ocr=True,model_storage_directory=str(CACHE/'easyocr'),download_enabled=True)
        options.enable_remote_services=False
        converter=DocumentConverter(format_options={InputFormat.PDF:PdfFormatOption(pipeline_options=options),InputFormat.IMAGE:ImageFormatOption(pipeline_options=options)})
    except Exception:
        initialization_error=traceback.format_exc();report['initialization_error']=initialization_error
    for source in sources:
        path=Path(source['source']);original=sha(path)
        if source.get('expected_sha') and original!=source['expected_sha']:raise RuntimeError('Prepared input changed: '+str(path))
        old=completed.get(source['id'])
        if old and old.get('source_sha256')==original and not (args.retry_errors and old.get('status')=='error'):
            report['cases'].append(old);write_report(report);print(source['id'],'checkpoint retained',flush=True);continue
        case={'id':source['id'],'source':str(path),'source_sha256':original,'selected_page':source.get('selected_page',2 if path.suffix.lower()=='.pdf' else 1),'attempted':converter is not None,'status':'not_run','outputs':{}}
        case['aliases']=source.get('aliases',[]);report['phase']='processing'
        started=time.perf_counter();folder=OUT/source['id'].replace('.pdf','');folder.mkdir(exist_ok=True)
        try:
            if converter is None:raise RuntimeError('Pipeline initialization failed: '+str(initialization_error))
            result=converter.convert(path,page_range=(case['selected_page'],case['selected_page']),raises_on_error=False)
            data=result.document.export_to_dict();markdown=result.document.export_to_markdown();tables=data.get('tables',[]);reading_order=[]
            layout=[{'page_no':page.page_no,'size':page.size.model_dump(mode='json') if page.size else None,'predictions':page.predictions.model_dump(mode='json')} for page in result.pages]
            (folder/'layout.json').write_text(json.dumps(layout,ensure_ascii=False,indent=2),encoding='utf-8')
            def visit(ref,depth=0):
                pointer=ref.get('$ref','').removeprefix('#/').split('/')
                try:
                    target=data
                    for key in pointer:target=target[int(key)] if isinstance(target,list) else target[key]
                except (KeyError,ValueError,IndexError,TypeError):return
                reading_order.append({'ref':ref.get('$ref'),'depth':depth,'label':target.get('label'),'text':target.get('text'),'prov':target.get('prov',[])})
                for child in target.get('children',[]):visit(child,depth+1)
            for ref in data.get('body',{}).get('children',[]):visit(ref)
            (folder/'document.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');(folder/'transcription.md').write_text(markdown,encoding='utf-8');(folder/'tables.json').write_text(json.dumps(tables,ensure_ascii=False,indent=2),encoding='utf-8');(folder/'reading-order.json').write_text(json.dumps(reading_order,ensure_ascii=False,indent=2),encoding='utf-8')
            case.update(status=str(result.status),text_items=len(data.get('texts',[])),tables=len(tables),markdown_characters=len(markdown),page_count=len(data.get('pages',{})),errors=[str(e) for e in result.errors],outputs={name:str((folder/file).relative_to(OUT)).replace('\\','/') for name,file in [('JSON','document.json'),('Markdown','transcription.md'),('tables','tables.json'),('reading_order','reading-order.json')]})
            case['layout_clusters']=sum(len((page['predictions'].get('layout') or {}).get('clusters',[])) for page in layout)
            case['outputs']['layout']=str((folder/'layout.json').relative_to(OUT)).replace('\\','/')
        except Exception:case['status']='error';case['error']=traceback.format_exc();(folder/'error.txt').write_text(case['error'],encoding='utf-8');case['outputs']['error']=str((folder/'error.txt').relative_to(OUT)).replace('\\','/')
        case['seconds']=round(time.perf_counter()-started,3);case['source_unchanged']=sha(path)==original
        case['aliases_unchanged']=all(sha(alias['path'])==alias['sha256'] for alias in case.get('aliases',[]) if alias.get('sha256'))
        if not case['source_unchanged']:raise RuntimeError('Original source changed: '+str(path))
        if not case['aliases_unchanged']:raise RuntimeError('Source alias changed for '+source['id'])
        report['cases'].append(case);write_report(report);print(case['id'],case['status'],case['seconds'],flush=True)
    report['phase']='finished';report['failed_cases']=sum(c['status']=='error' for c in report['cases']);report['completed_cases']=len(report['cases']);report['all_sources_unchanged']=all(case['source_unchanged'] for case in report['cases']);write_report(report)

if __name__=='__main__':main()
