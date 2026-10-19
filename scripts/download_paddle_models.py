"""Fetch official Paddle inference weights; no document upload or cloud inference."""
import hashlib
import json
from pathlib import Path
import tarfile
import urllib.request
import os
import uuid
ROOT=Path(__file__).resolve().parents[1]
PINNED={'PP-OCRv6_small_det':'bfb7c1e59f0faa6b540ebdca93aea3f4b1f2477805b389fbee117820d68fe9f5','PP-OCRv6_small_rec':'da460f968ce9f88325ac3a34fa302077d6e9b0dcefb16ba3137cd7796f879d06'}


def main():
    folder=ROOT/'models/paddle-integration';folder.mkdir(parents=True,exist_ok=True);records=[]
    for model in ['PP-OCRv6_small_det','PP-OCRv6_small_rec']:
        url='https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/'+model+'_infer.tar';archive=folder/(model+'.tar')
        if not archive.exists():
            partial=folder/(model+'.'+uuid.uuid4().hex+'.partial')
            try:
                with urllib.request.urlopen(url,timeout=120) as source,partial.open('wb') as out:
                    while block:=source.read(1024*1024):out.write(block)
                with partial.open('rb') as source:downloaded=hashlib.file_digest(source,'sha256').hexdigest()
                if downloaded!=PINNED[model]:raise ValueError('Official download differs from the pinned model: '+model)
                os.rename(partial,archive)
            finally:partial.unlink(missing_ok=True)
        with archive.open('rb') as source:sha=hashlib.file_digest(source,'sha256').hexdigest()
        if sha!=PINNED[model]:raise ValueError('Official archive differs from the pinned experiment: '+model)
        destination=folder/model;destination.mkdir(exist_ok=True)
        configured=bool(list(destination.rglob('inference.yml'))+list(destination.rglob('inference.yaml')))
        with tarfile.open(archive) as bundle:
            if not configured:bundle.extractall(destination,filter='data')
            else:
                for member in bundle.getmembers():
                    if not member.isfile():continue
                    target=destination/member.name
                    with bundle.extractfile(member) as source:expected=hashlib.file_digest(source,'sha256').hexdigest()
                    if not target.is_file():raise ValueError('Model directory is incomplete; it was not overwritten: '+str(target))
                    with target.open('rb') as source:actual=hashlib.file_digest(source,'sha256').hexdigest()
                    if actual!=expected:raise ValueError('Model directory was changed; it was not overwritten: '+str(target))
        configs=list(destination.rglob('inference.yml'))+list(destination.rglob('inference.yaml'))
        if not configs:raise ValueError('Downloaded model lacks inference configuration: '+model)
        records.append({'model':model,'url':url,'archive_sha256':sha,'path':str(configs[0].parent),'bytes':archive.stat().st_size})
    (folder/'provenance.json').write_text(json.dumps({'models':records,'source_documentation':'https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/OCR.en.md','policy':'Official local inference models. No recognition accuracy claim on supplied historical handwriting.'},indent=2),encoding='utf8')
    print(json.dumps(records),flush=True)

if __name__=='__main__':main()
