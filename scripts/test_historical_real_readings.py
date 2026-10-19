"""Sample one real Paddle reading per case through the historical layer.

Seven saved reports,469 case rows: duplicates remain explicit. No inference,
reference transcription, accuracy claim or automatic correction is introduced.
"""
import hashlib,html,json,math,sys,time,traceback
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.historical_reading import HistoricalTools
OUT=ROOT/'test-output/historical-real-readings'
REPORTS=['paddle','gologory-paddle','gologory-deaths-paddle','gologory-331-paddle','gologory-333-paddle','gologory-335-paddle','gologory-336-paddle']

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def candidates(raw,width,height):
    options=[];rejected=0;nonempty=0
    for payload_index,data in enumerate(raw if isinstance(raw,list) else [raw]):
        texts=data.get('rec_texts',[]);polys=data.get('rec_polys',[])
        if len(texts)!=len(polys):rejected+=len(texts);nonempty+=sum(isinstance(t,str) and bool(t.strip()) for t in texts);continue
        for index,(text,poly) in enumerate(zip(texts,polys)):
            if not isinstance(text,str) or not text.strip():continue
            nonempty+=1
            valid=isinstance(poly,list) and len(poly)>=3 and all(isinstance(p,list) and len(p)==2 and all(type(v) in [int,float] and math.isfinite(v) for v in p) for p in poly)
            if not valid:rejected+=1;continue
            xs=[p[0] for p in poly];ys=[p[1] for p in poly];left,right=min(xs),max(xs);top,bottom=min(ys),max(ys)
            area=abs(sum(poly[i][0]*poly[(i+1)%len(poly)][1]-poly[(i+1)%len(poly)][0]*poly[i][1] for i in range(len(poly))))/2
            if not(0<=left<right<=width and 0<=top<bottom<=height and area>0):rejected+=1;continue
            options.append({'payload_index':payload_index,'line_index':index,'text':text,'polygon':poly,'rect':[left/width,top/height,(right-left)/width,(bottom-top)/height],'score':data.get('rec_scores',[None]*len(texts))[index]})
    return sorted(options,key=lambda c:(-sum(ch.isalpha() for ch in c['text']),-len(c['text']),c['payload_index'],c['line_index'])),rejected,nonempty

def save(report):
    report['summary']={status:sum(c['status']==status for c in report['cases']) for status in ['analyzed_unverified','skip_empty','skip_invalid_geometry','failed']};report['processed']=len(report['cases'])
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    esc=html.escape;parts=['<!doctype html><meta charset=utf-8><title>Historical real-reading compatibility</title><style>body{font:16px system-ui;max-width:1300px;margin:30px auto}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:9px;vertical-align:top}pre{white-space:pre-wrap;max-width:650px}img{max-width:550px;max-height:100px}</style><h1>Історичний шар: справжні збережені прочитання</h1><p>Вибрано один фактично розпізнаний рядок на вхід: найбільше літер серед рядків із придатним багатокутником. Це може бути заголовок або водяний знак. Текст моделей збережено дослівно, він неперевірений. Порожні входи й непридатна геометрія пропускаються явно. Це не повне прочитання книг і не оцінка точності.</p><p>'+esc(str(report['summary']))+'</p><table><tr><th>Звіт / вхід</th><th>Стан</th><th>Дослівний текст моделі та фрагмент</th></tr>']
    for case in report['cases']:
        detail='<pre>'+esc(case.get('literal',case.get('error','')))+'</pre>'
        if case.get('crop'):detail+='<img loading="lazy" src="'+esc(Path(case['crop']).relative_to(OUT).as_posix(),quote=True)+'">'
        if case.get('raw_output'):detail+='<p><a href="'+esc(case['raw_output'],quote=True)+'">Походження, багатокутник і аналіз</a></p>'
        parts.append('<tr><td>'+esc(case['report']+' / '+case['id'])+'</td><td>'+esc(case['status'])+'</td><td>'+detail+'</td></tr>')
    parts.append('</table><a href=report.json>Повний звіт</a>');(OUT/'report.html').write_text('\n'.join(parts),encoding='utf-8')

def main():
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'raw').mkdir(exist_ok=True);engine=Engine(OUT/'library');tools=HistoricalTools(engine);started=time.perf_counter()
    report={'scope':'Primary109 Paddle cases plus six additional AGAD reports totalling360 case rows;469 rows, overlap retained explicitly.','policy':'One real saved recognized line per nonempty geometrically valid case, unverified. Compatibility/literal preservation only; no new ML, GT or accuracy metric.','selection':'Max alphabetic-character count, then text length; valid same-image rec_polys only. May select headings/watermarks, not necessarily manuscript body.','reports':[],'cases':[],'phase':'running'}
    hashes={}
    for name in REPORTS:
        path=ROOT/'test-output/integrations'/name/'report.json';data=json.loads(path.read_text(encoding='utf-8'));report['reports'].append({'name':name,'path':str(path),'sha256':sha(path),'case_rows':len(data['cases'])})
        assert data['configuration']['doc_orientation'] is False and data['configuration']['doc_unwarping'] is False
        for case in data['cases']:
            row={'report':name,'id':case['id'],'image':case['image'],'image_sha256':case['image_sha256'],'aliases':case.get('aliases',[])};tick=time.perf_counter()
            try:
                actual=sha(case['image']);assert actual==case['image_sha256'];hashes.setdefault(actual,[]).append(name+'/'+case['id'])
                with Image.open(case['image']) as image:width,height=image.size
                imported=engine.import_file({'path':case['image']})['id'];imported_page=engine.db.execute('SELECT id FROM pages WHERE doc=? ORDER BY num LIMIT 1',(imported,)).fetchone()['id'];row.update(document=imported,page=imported_page)
                if not case.get('raw_path'):row.update(status='skip_empty',reason='No saved recognition output')
                else:
                    raw_path=Path(case['raw_path']);raw_sha=sha(raw_path);raw=json.loads(raw_path.read_text(encoding='utf-8'))
                    for payload in raw if isinstance(raw,list) else [raw]:assert Path(payload['input_path']).resolve()==Path(case['image']).resolve(),'Recognition geometry belongs to another image'
                    options,rejected,nonempty=candidates(raw,width,height);row.update(nonempty_model_lines=nonempty,rejected_geometry_lines=rejected)
                    if not options:row.update(status='skip_invalid_geometry' if nonempty else 'skip_empty',reason='No nonempty saved reading with a valid aligned polygon')
                    else:
                        selected=options[0];doc=engine.import_file({'path':case['image']})['id'];page=engine.db.execute('SELECT id FROM pages WHERE doc=? ORDER BY num LIMIT 1',(doc,)).fetchone()['id'];annotation='real-reading-'+name+'-'+case['id']
                        tools.save_annotation({'page':page,'annotation':annotation,'data':{'kind':'line','rect':selected['rect'],'text':selected['text'],'verified':False,'note':'Actual saved Paddle output, unverified. Axis-aligned bounds of detector polygon; no manual reading or ground truth.'}})
                        state=tools.historical_get({'page':page});analysis=tools.historical_analyze({'page':page,'annotation':annotation});assert analysis['original']['text']==selected['text'];assert not analysis['gt_eligible'];assert not analysis['original'].get('verified')
                        crop=tools.region_crop({'id':page,'annotation':annotation});
                        with Image.open(crop['path']) as image:image.verify()
                        ident=name+'--'+case['id'];raw_output=OUT/'raw'/(ident+'.json');provenance={'source_report':str(path),'source_report_sha256':report['reports'][-1]['sha256'],'raw_paddle':str(raw_path),'raw_paddle_sha256':raw_sha,'case':case,'selected_line':selected,'image_size':[width,height],'crop':crop,'analysis':analysis,'page':page,'annotation':annotation,'literal_preserved':True,'ground_truth':False};raw_output.write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf-8')
                        row.update(status='analyzed_unverified',literal=selected['text'],payload_index=selected['payload_index'],line_index=selected['line_index'],polygon=selected['polygon'],rect=selected['rect'],page=page,annotation=annotation,crop=crop['path'],raw_output=raw_output.relative_to(OUT).as_posix(),literal_preserved=True,gt_eligible=False)
                assert sha(case['image'])==actual;row['source_unchanged']=True;row['aliases_unchanged']=all(sha(a['path'])==a['sha256'] for a in case.get('aliases',[]) if a.get('sha256'));assert row['aliases_unchanged']
            except Exception:row.update(status='failed',error=traceback.format_exc())
            row['seconds']=round(time.perf_counter()-tick,3);report['cases'].append(row);save(report);print(name,case['id'],row['status'],flush=True)
    assert len(report['cases'])==469
    report.update(phase='finished',seconds=round(time.perf_counter()-started,3),distinct_image_sha256=len(hashes),duplicate_image_groups=[{'image_sha256':h,'cases':cases} for h,cases in hashes.items() if len(cases)>1],all_sources_unchanged=all(c.get('source_unchanged') for c in report['cases']),all_aliases_unchanged=all(c.get('aliases_unchanged') for c in report['cases']))
    report['deduplication_note']='Counts refer to encoded normalized test inputs, not unique physical archival pages. Different resolutions or encodings may depict overlapping source content.'
    report['all_saved_model_reports_unchanged']=all(sha(r['path'])==r['sha256'] for r in report['reports']);assert report['all_saved_model_reports_unchanged']
    report['reopened_library_counts']={table:engine.db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ['documents','pages','annotations']}
    save(report);engine.db.close()

if __name__=='__main__':main()
