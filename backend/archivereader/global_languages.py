"""Offline publisher language identifiers; not an OCR or linguistic model."""
import json,unicodedata,re
from pathlib import Path

_CACHE={}
def _key(value):return unicodedata.normalize('NFC',value).casefold()

def load_registry(path=None):
 path=Path(path) if path else Path(__file__).with_name('global_languages.json')
 try:
  stat=path.stat();stamp=(str(path.resolve()),stat.st_mtime_ns,stat.st_size)
  if stamp in _CACHE:return _CACHE[stamp]
  if stat.st_size>12*1024*1024:raise ValueError('size')
  data=json.loads(path.read_text('utf-8'))
  if not isinstance(data,dict) or data.get('version')!=1 or not isinstance(data.get('dataset'),dict) or not isinstance(data.get('rows'),list) or len(data['rows'])>100000:raise ValueError('format')
  seen=set()
  for row in data['rows']:
   if not isinstance(row,dict) or any(not isinstance(row.get(k),str) or len(row[k])>500 for k in ['id','glottocode','iso','name','level']) or not row['id'] or not row['name'] or row['id'] in seen:raise ValueError('row')
   if not re.fullmatch(r'[a-z0-9]{4}[0-9]{4}',row['glottocode']):raise ValueError('glottocode')
   seen.add(row['id'])
  dataset=data['dataset']
  for field in ['provenance_url','commit_sha','source_file_sha256','license','license_url','citation','retrieved_date','scope']:
   if not isinstance(dataset.get(field),str) or not dataset[field] or len(dataset[field])>8000:raise ValueError('provenance')
  result=(data,[(row,_key(' '.join(row[k] for k in ['id','glottocode','iso','name','level']))) for row in data['rows']]);_CACHE.clear();_CACHE[stamp]=result;return result
 except (OSError,ValueError,TypeError,RecursionError) as exc:raise ValueError('Локальний каталог мов недоступний або пошкоджений.') from exc

class GlobalLanguagesTools:
 def __init__(self,engine=None):self.engine=engine
 def historical_languages(self,args):
  query=args.get('query','');limit=args.get('limit',25);offset=args.get('offset',0)
  if not isinstance(query,str) or len(query)>200 or any(ord(c)<32 for c in query):raise ValueError('Введіть пошуковий запит до 200 символів.')
  if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or not 0<=offset<=100000:raise ValueError('Неправильні межі сторінки каталогу мов.')
  data,index=load_registry();words=_key(query).split();matched=[row for row,search in index if all(word in search for word in words)]
  return {'rows':[dict(row)|{'resource_url':'https://glottolog.org/resource/languoid/id/'+row['glottocode']} for row in matched[offset:offset+limit]],'total':len(matched),'offset':offset,'limit':limit,'has_more':offset+limit<len(matched),'dataset':dict(data['dataset']),'policy':'Discovery identifiers only: selection does not assign language, script, dates, OCR model, translation, ground truth or training data.'}
