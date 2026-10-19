"""Install a small set of official Paddle inference packages. No OCR is run."""
import hashlib,json,tarfile,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];folder=ROOT/'models/paddle-asian';folder.mkdir(exist_ok=True)
models=['PP-OCRv5_server_rec','korean_PP-OCRv5_mobile_rec','devanagari_PP-OCRv5_mobile_rec']
def digest(p):
 with p.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
records=[]
for model in models:
 repo='PaddlePaddle/'+model
 with urllib.request.urlopen('https://huggingface.co/api/models/'+repo+'?blobs=true',timeout=40) as response:metadata=json.load(response)
 revision=metadata['sha'];destination=folder/model;destination.mkdir(exist_ok=True);hashes={}
 for item in metadata['siblings']:
  name=item['rfilename']
  if name not in ['inference.json','inference.pdiparams','inference.yml','inference.yaml','config.json','README.md','LICENSE']:continue
  target=destination/name;expected=item.get('lfs',{}).get('sha256')
  if not target.exists() or (expected and digest(target)!=expected):
   temporary=target.with_suffix(target.suffix+'.partial');count=0
   with urllib.request.urlopen('https://huggingface.co/'+repo+'/resolve/'+revision+'/'+name,timeout=90) as response,temporary.open('wb') as out:
    while chunk:=response.read(1024**2):
     count+=len(chunk)
     if count>200*1024**2:raise ValueError('Unexpected file size')
     out.write(chunk)
   if expected and digest(temporary)!=expected:raise ValueError('Checksum mismatch')
   temporary.replace(target)
  hashes[name]=digest(target)
 if not (destination/'inference.pdiparams').is_file() or not (destination/'inference.yml').is_file():raise ValueError('Incomplete model')
 records.append({'model':model,'repository':repo,'revision':revision,'path':str(destination),'files':hashes})
 print(model,flush=True)
det=json.loads((ROOT/'models/paddle-integration/provenance.json').read_text('utf-8'))['models'][0]
for name,model in zip(['chinese-japanese','korean','devanagari'],models,strict=True):
 rec=next(r for r in records if r['model']==model)
 config={'engine':'paddle','detector':det['model'],'detector_path':str(Path(det['path']).relative_to(ROOT)),'recognizer':model,'recognizer_path':str(Path(rec['path']).relative_to(ROOT)),'runtime':'integration-envs/paddle-stable/Scripts/python.exe','root':'../..','verified':False,'accuracy_tested':False,'scope':'Experimental; modern print-oriented language package. Historical handwriting unverified.'}
 (folder/(name+'.json')).write_text(json.dumps(config,indent=2),'utf-8')
(folder/'provenance.json').write_text(json.dumps({'models':records,'policy':'Official HTTPS downloads; local hashes recorded. Recognition not run.'},indent=2),'utf-8')
