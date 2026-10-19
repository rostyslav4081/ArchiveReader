"""Historical-layer compatibility sweep on every normalized109 input.

Empty arbitrary test rectangles exercise source/crop handling only: they are not
detected lines, entries, transcriptions or verified reference material. No ML.
"""
import hashlib,html,json,sys,time,traceback
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.historical_reading import HistoricalTools
OUT=ROOT/'test-output/historical-input-matrix'

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def save(report):
    report['processed']=len(report['cases']);report['successful']=sum(c['status']=='compatible' for c in report['cases']);report['failed']=sum(c['status']=='failed' for c in report['cases'])
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    esc=html.escape;parts=['<!doctype html><meta charset=utf-8><title>Historical input compatibility</title><style>body{font:16px system-ui;max-width:1150px;margin:30px auto}table{border-collapse:collapse;width:100%}td,th{padding:9px;border:1px solid #ccc;text-align:left}pre{white-space:pre-wrap}</style><h1>Історичний шар: сумісність на всіх109 входах</h1><p>Перевірено імпорт, відкриття джерела, відтворення пікселів і аналіз порожньої довільної тестової ділянки. Це не виявлений рядок, не прочитаний текст і не оцінка точності. Розпізнавання моделей не запускалося.</p><p>'+esc(str({k:report[k] for k in ['processed','successful','failed']}))+'</p><table><tr><th>Вхід</th><th>Стан</th><th>Час, с</th><th>Результат</th></tr>']
    for case in report['cases']:
        parts.append('<tr><td>'+esc(case['id'])+'</td><td>'+esc(case['status'])+'</td><td>'+str(case['seconds'])+'</td><td>'+('<a href="raw/'+esc(case['id'])+'.json">Походження й результат</a>' if case['status']=='compatible' else '<pre>'+esc(case.get('error',''))+'</pre>')+'</td></tr>')
    parts.append('</table><p><a href=report.json>Повний звіт</a></p>');(OUT/'report.html').write_text('\n'.join(parts),encoding='utf-8')

def main():
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'raw').mkdir(exist_ok=True)
    path=ROOT/'test-output/integrations/cases.json';manifest=json.loads(path.read_text(encoding='utf-8'));engine=Engine(OUT/'library');tools=HistoricalTools(engine)
    report={'scope':manifest['scope'],'manifest':str(path),'manifest_sha256':sha(path),'requested':len(manifest['cases']),'policy':'Compatibility only. Empty arbitrary test ROI, not detected lines/entries. No OCR/HTR, lexical accuracy or ground-truth claim. Originals never edited.','cases':[],'phase':'running'}
    started=time.perf_counter()
    for case in manifest['cases']:
        row={'id':case['id'],'image':case['image'],'expected_sha256':case['image_sha256'],'aliases':case['aliases']};tick=time.perf_counter()
        try:
            assert sha(case['image'])==case['image_sha256'],'Normalized source hash changed'
            doc=engine.import_file({'path':case['image']})['id'];page=engine.db.execute('SELECT id FROM pages WHERE doc=? ORDER BY num LIMIT 1',(doc,)).fetchone()['id'];state=tools.historical_get({'page':page})
            render=engine.render({'id':page,'whole':True,'full':True,'preprocess':'original'})
            with Image.open(case['image']) as source,Image.open(render['path']) as viewed:
                original=source.convert('RGB');actual=viewed.convert('RGB');assert original.size==actual.size and original.tobytes()==actual.tobytes(),'Render changed source pixels'
            annotation='empty-compatibility-roi-'+case['id'];tools.save_annotation({'page':page,'annotation':annotation,'data':{'kind':'entry','rect':[.1,.1,.2,.05],'text':'','verified':False,'note':'EMPTY arbitrary compatibility rectangle. Not detected content or verified reference.'}})
            analysis=tools.historical_analyze({'page':page,'annotation':annotation});assert analysis['original']['text']=='' and not analysis['tokens'] and analysis['gt_eligible'] is False
            crop=tools.region_crop({'id':page,'annotation':annotation});
            with Image.open(crop['path']) as image:image.verify()
            assert sha(case['image'])==case['image_sha256']
            aliases_unchanged=all(sha(a['path'])==a['sha256'] for a in case['aliases'] if a.get('sha256'));assert aliases_unchanged
            raw={'page':page,'document':doc,'source_sha256':state['source_sha256'],'render':render,'crop':crop,'analysis':analysis,'source_unchanged':True,'aliases_unchanged':True};(OUT/'raw'/(case['id']+'.json')).write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf-8')
            row.update(status='compatible',page=page,document=doc,source_unchanged=True,aliases_unchanged=True,pixels_unchanged=True,tokens=0,verified_reference_lines=0)
        except Exception:row.update(status='failed',error=traceback.format_exc())
        row['seconds']=round(time.perf_counter()-tick,3);report['cases'].append(row);save(report);print(case['id'],row['status'],flush=True)
    report.update(phase='finished',seconds=round(time.perf_counter()-started,3),all_sources_unchanged=all(c.get('source_unchanged') for c in report['cases']),all_aliases_unchanged=all(c.get('aliases_unchanged') for c in report['cases']));save(report);engine.db.close()

if __name__=='__main__':main()
