"""Rebuild the pinned Glottolog discovery registry from a local official CSV.

No network access. Obtain the source at SOURCE_URL, then pass --csv. The exact
publisher bytes must match SOURCE_SHA256; newer releases require deliberate code
and provenance updates, rather than silently replacing the pinned dataset.
"""
import argparse,csv,hashlib,json,re
from pathlib import Path

COMMIT='072ca0d0410039fb8b779be8fc165bac575d2cda'
SOURCE_URL=f'https://raw.githubusercontent.com/glottolog/glottolog-cldf/{COMMIT}/cldf/languages.csv'
SOURCE_SHA256='1a50a393bc81568b656f9522be18aa4f80f38e94309ba6c863d583234adfbb89'
ROOT=Path(__file__).resolve().parents[1]
METADATA={
 'provenance_url':f'https://github.com/glottolog/glottolog-cldf/tree/{COMMIT}',
 'source_url':SOURCE_URL,'commit_sha':COMMIT,'source_file_sha256':SOURCE_SHA256,
 'license':'CC-BY-4.0','license_url':'https://creativecommons.org/licenses/by/4.0/',
 'citation':'Hammarström, Harald & Forkel, Robert & Haspelmath, Martin & Bank, Sebastian. 2026. Glottolog 5.3. Leipzig: Max Planck Institute for Evolutionary Anthropology. https://doi.org/10.5281/zenodo.18840967',
 'retrieved_date':'2026-10-15',
 'scope':'Glottolog languoid identifiers and publisher names: families, languages and dialects, including ancient/extinct entries present in this pinned release. Not every historical spelling or manuscript variety; no dictionaries, grammar models or OCR coverage.',
 'notes':'Pinned v5.3 commit README identifies release 5.3; bundled CLDF metadata still labels itself 5.2.1. Original names and level values retained; family/language/dialect have special meanings for non-genealogical trees. No script, date, nationality or recognition model inferred.',
 'source_license_sha256':'945fbcb37deca05bccd7c3ca0e261679f1f5373515504fdbad68f6f3cf6f49b9'}

def build(source,output):
 source=Path(source).resolve();output=Path(output).resolve()
 if source==output:raise ValueError('Source CSV and output must be different files.')
 if source.stat().st_size>8*1024*1024:raise ValueError('Source CSV exceeds 8 MiB limit.')
 raw=source.read_bytes();actual=hashlib.sha256(raw).hexdigest()
 if actual!=SOURCE_SHA256:raise ValueError('Source CSV does not match pinned official SHA-256: '+actual)
 reader=csv.DictReader(raw.decode('utf-8').splitlines());mapping={'id':'ID','glottocode':'Glottocode','iso':'ISO639P3code','name':'Name','level':'Level'}
 if not set(mapping.values()).issubset(reader.fieldnames or []):raise ValueError('Missing publisher CSV columns.')
 rows=[];seen=set()
 for source_row in reader:
  row={key:source_row[column] for key,column in mapping.items()}
  if any(not isinstance(value,str) or len(value)>500 for value in row.values()) or not row['name'] or row['id'] in seen or not re.fullmatch('[a-z0-9]{4}[0-9]{4}',row['glottocode']):raise ValueError('Invalid publisher row.')
  seen.add(row['id']);rows.append(row)
  if len(rows)>100000:raise ValueError('Too many publisher rows.')
 rows.sort(key=lambda row:(row['name'].casefold(),row['id']))
 encoded=json.dumps({'version':1,'dataset':METADATA,'rows':rows},ensure_ascii=False,separators=(',',':')).encode('utf-8')
 output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(encoded)
 return {'source_url':SOURCE_URL,'source_sha256':actual,'output_sha256':hashlib.sha256(encoded).hexdigest(),'rows':len(rows),'bytes':len(encoded),'network_used':False}

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--csv',required=True,type=Path);parser.add_argument('--output',type=Path,default=ROOT/'backend'/'archivereader'/'global_languages.json');args=parser.parse_args()
 try:result=build(args.csv,args.output)
 except (OSError,ValueError) as exc:parser.exit(2,str(exc)+'\n')
 print(json.dumps(result,ensure_ascii=True))

if __name__=='__main__':main()
