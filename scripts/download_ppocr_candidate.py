"""Fetch public pinned safetensors candidate; never uploads documents."""
import hashlib,json,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parents[1];repo='small-models-for-glam/kraken-ppocrv6-medium';folder=root/'models/kraken-ppocrv6-medium';folder.mkdir(exist_ok=True)
with urllib.request.urlopen('https://huggingface.co/api/models/'+repo+'?blobs=true',timeout=40) as r:info=json.load(r)
revision=info['sha'];entry=next(f for f in info['siblings'] if f['rfilename']=='medium.safetensors');expected=entry['lfs']['sha256'];target=folder/'medium.safetensors';tmp=target.with_suffix('.partial')
if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest()!=expected:
 with urllib.request.urlopen('https://huggingface.co/'+repo+'/resolve/'+revision+'/medium.safetensors',timeout=90) as response,tmp.open('wb') as out:
  count=0
  while chunk:=response.read(1024*1024):
   count+=len(chunk)
   if count>300*1024*1024:raise ValueError('Model exceeds size bound')
   out.write(chunk)
 if hashlib.sha256(tmp.read_bytes()).hexdigest()!=expected:raise ValueError('Weight hash mismatch')
 tmp.replace(target)
(folder/'provenance.json').write_text(json.dumps({'repository':repo,'revision':revision,'file':'medium.safetensors','sha256':expected,'bytes':target.stat().st_size,'source':'https://huggingface.co/'+repo,'scope':'Multilingual candidate; not verified on these private books. No training labels or automatic activation.'},indent=2),'utf-8');print(json.dumps({'revision':revision,'sha256':expected,'bytes':target.stat().st_size}))
