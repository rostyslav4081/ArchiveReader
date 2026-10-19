"""Pinned local-only Polish HTR candidate download. No archive images are sent."""
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
REPO='meldynamics/polish-metrical-htr-experimental'


def main(repo=REPO,folder_name='polish-metrical-experimental'):
    folder=ROOT/'models'/folder_name;folder.mkdir(exist_ok=True)
    with urllib.request.urlopen('https://huggingface.co/api/models/'+repo+'?blobs=true',timeout=60) as response:metadata=json.load(response)
    revision=metadata['sha'];(folder/'upstream.json').write_text(json.dumps(metadata,indent=2),encoding='utf8')
    allowed={'config.json','generation_config.json','preprocessor_config.json','processor_config.json','tokenizer_config.json','special_tokens_map.json','tokenizer.json','vocab.json','merges.txt','model.safetensors','README.md','LICENSE'}
    selected=[f for f in metadata['siblings'] if f['rfilename'] in allowed]
    total=sum(f.get('size',0) for f in selected)
    if total>3*1024**3 or shutil.disk_usage(folder).free<total+3*1024**3:raise ValueError('Insufficient disk space or unexpected model size')
    if not any(f['rfilename']=='model.safetensors' for f in selected):raise ValueError('Expected single safetensors model')
    files={}
    for item in selected:
        name=item['rfilename'];target=folder/name;expected=item.get('lfs',{}).get('sha256')
        if not target.exists() or (expected and hashlib.sha256(target.read_bytes()).hexdigest()!=expected):
            temp=target.with_suffix(target.suffix+'.partial');count=0
            with urllib.request.urlopen('https://huggingface.co/'+repo+'/resolve/'+revision+'/'+name,timeout=120) as response,temp.open('wb') as output:
                while chunk:=response.read(4*1024*1024):
                    count+=len(chunk)
                    if count>3*1024**3:raise ValueError('Unexpected file size')
                    output.write(chunk)
            with temp.open('rb') as source:digest=hashlib.file_digest(source,'sha256').hexdigest()
            if expected and digest!=expected:raise ValueError('Checksum mismatch: '+name)
            temp.replace(target)
        with target.open('rb') as source:files[name]=hashlib.file_digest(source,'sha256').hexdigest()
        print(name,target.stat().st_size,flush=True)
    (folder/'provenance.json').write_text(json.dumps({'repository':repo,'revision':revision,'sha256':files,'source':'https://huggingface.co/'+repo,'experimental':True,'limits':'Evaluate with human reference text. Historical manuscript suitability is not established; see upstream training scope.'},indent=2),encoding='utf8')


if __name__=='__main__':main()
