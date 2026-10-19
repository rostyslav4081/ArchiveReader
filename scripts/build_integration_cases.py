"""Inventory all available archival attachments and FigJam photos for fair local tests."""
from pathlib import Path
import argparse,hashlib,json
from PIL import Image,ImageOps
ROOT=Path(__file__).resolve().parents[1]

def sha(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--inventory',type=Path,default=ROOT/'test-output/integrations/source-inventory.json');parser.add_argument('--output',type=Path,default=ROOT/'test-output/integrations');parser.add_argument('--replace',action='store_true');args=parser.parse_args()
 out=args.output.resolve()
 if not out.is_relative_to((ROOT/'test-output').resolve()):raise ValueError('Output must stay within test-output')
 if (out/'cases.json').exists() and not args.replace:raise ValueError('Existing manifest: choose a new output or explicitly pass --replace')
 inputs=out/'inputs';inputs.mkdir(parents=True,exist_ok=True);sources=[];missing=[]
 supplied=json.loads(args.inventory.read_text(encoding='utf8'));assets=supplied.get('figma_source_assets',[])
 for source in supplied['sources']:
  item={key:source.get(key) for key in ['path','label','origin','source_document','source_page']};item['source_document']=item['source_document'] or item['path']
  if not Path(item['path']).is_file():missing.append(item);continue
  sources.append(item)
 cases=[];by_pixels={};inventory=[]
 for s in sources:
  path=Path(s['path']);original_sha=sha(path)
  with Image.open(path) as image:
   image=ImageOps.exif_transpose(image).convert('RGB');size=list(image.size);image.thumbnail((2400,2400),Image.Resampling.LANCZOS);pixels=hashlib.sha256(str(image.size).encode()+image.tobytes()).hexdigest()
   if pixels not in by_pixels:
    ident='case-'+str(len(cases)+1).zfill(3);dest=inputs/(ident+'.png');image.save(dest);case={'id':ident,'image':str(dest.resolve()),'image_sha256':sha(dest),'pixel_sha256':pixels,'size':list(image.size),'aliases':[]};cases.append(case);by_pixels[pixels]=case
   case=by_pixels[pixels];case['aliases'].append(s|{'sha256':original_sha,'original_size':size})
  inventory.append(s|{'sha256':original_sha,'case':case['id']})
 report={'scope':'Explicit supplied image inventory with source PDF/page and photo aliases. Exact normalized pixel duplicates share inference while preserving every alias. This tool does not crawl folders or render PDF files.','preparation':'EXIF transpose, RGB, maximum side 2400px; PDF inputs are existing verified 1800px previews. Originals unchanged.','cases':cases,'inventory':inventory,'missing':missing,'figma_source_assets':[a|{'exists':Path(a['path']).is_file()} for a in assets],'ground_truth':'No human-confirmed body-text references. Runtime success is not accuracy.'}
 report['source_documents']={path:{'sha256':sha(path),'bytes':Path(path).stat().st_size} for path in sorted({r['source_document'] for r in sources})}
 (out/'cases.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps({'cases':len(cases),'source_aliases':len(inventory),'missing':len(missing),'figma_nodes':sum(s['origin']=='FigJam photo node' for s in inventory)}))

if __name__=='__main__':main()
