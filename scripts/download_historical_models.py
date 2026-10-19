"""Download explicitly selected public HTR candidates; never uploads source images."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
CANDIDATES={'catmus-medieval':('21488839','catmus-medieval-1.6.0.mlmodel','326a6ea675661ec9ce0bb6b1958de495'),
            'german-print':('10519596','german_print.mlmodel','707720bff8e9f0e7848c1c859d1bc60e'),
            'german-handwriting':('7933463','german_handwriting.mlmodel','6c41ae2cc0a990f018bf549490041a06'),
            'bohemica':('11673242','rec_bohemica.mlmodel','b58821cab5e2b3cf5f6d260aad3365f5')}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('names',nargs='*',choices=list(CANDIDATES));args=parser.parse_args()
    for name in args.names or CANDIDATES:
        record,filename,md5=CANDIDATES[name];folder=ROOT/'models'/name;folder.mkdir(exist_ok=True)
        with urllib.request.urlopen('https://zenodo.org/api/records/'+record,timeout=60) as response:data=json.load(response)
        (folder/'zenodo-record.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
        selected=next(f for f in data['files'] if f['key']==filename)
        if selected['checksum']!='md5:'+md5:raise ValueError('Upstream checksum changed')
        destination=folder/'model.mlmodel'
        if not destination.exists() or hashlib.md5(destination.read_bytes()).hexdigest()!=md5:
            request=urllib.request.Request(selected['links']['self'],headers={'User-Agent':'ArchiveReader-local-model-evaluation/1.0'})
            temp=destination.with_suffix('.partial')
            with urllib.request.urlopen(request,timeout=90) as response,temp.open('wb') as output:
                while chunk:=response.read(1024*1024):output.write(chunk)
            if hashlib.md5(temp.read_bytes()).hexdigest()!=md5:raise ValueError('Model checksum mismatch')
            temp.replace(destination)
        provenance={'url':'https://zenodo.org/records/'+record,'file':filename,'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'md5':md5,'license':data['metadata'].get('license'),'scope':'Candidate; validate against separate manually verified lines. Not a universal handwriting model.'}
        (folder/'provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({'name':name,'bytes':destination.stat().st_size,'license':provenance['license']},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
