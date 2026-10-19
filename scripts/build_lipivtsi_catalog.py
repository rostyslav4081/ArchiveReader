"""Build a source-backed catalog from saved official metadata and public viewer lists.

Reads only local source snapshots. Does not download/OCR all historical pages.
"""
import hashlib
import html
import json
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'test-output/philip-source-research';BASE='https://archium.tsdial.archives.gov.ua'
IDS=[140241,140242,140243,143541,144034,146498,146499,230496]


def clean(text):return re.sub(r'\s+',' ',html.unescape(re.sub('<.*?>','',text))).strip()


def main():
    books=[]
    for ident in IDS:
        path=OUT/(str(ident)+'.html');raw=path.read_bytes();source=raw.decode('utf-8')
        rows={clean(k):clean(v) for k,v in re.findall(r'<div class="left(?: bold)?">(.*?)</div>\s*<div class="right">(.*?)</div>',source,re.S)}
        title=rows['Заголовок'];viewer=(OUT/('viewer-'+str(ident)+'.html')).read_text(encoding='utf-8')
        scans=[]
        for index,m in enumerate(re.finditer(r'<img\s+data-target-link="#file-(\d+)"\s+data-observe-src="([^"]+)"[^>]*\balt="([^"]*)"',viewer),1):
            scans.append({'scan_position':index,'file_id':m[1],'archive_image_label':html.unescape(m[3]),'image_url':BASE+html.unescape(m[2]),'viewer_url':BASE+'/file-viewer/'+str(ident)+'#file-'+m[1]})
        fonds_name=re.search(r'<a href="/fonds/\d+/">(.*?)</a>&nbsp;/&nbsp;',source,re.S)
        types=[]
        if 'народження' in title:types.append('birth')
        if 'одруження' in title:types.append('marriage')
        if 'смерт' in title:types.append('death')
        if not types:types=['mixed_or_unspecified_in_catalog_title']
        books.append({'archive':'Центральний державний історичний архів України, м. Львів','archive_file_id':ident,'fonds':rows['Фонд'],'inventory':rows['Опис'],'case':rows['Справа'],'fonds_title':clean(fonds_name[1]) if fonds_name else None,'title':title,'catalog_dates':rows.get('Дати'),'catalog_folios':int(rows['Кількість аркушів']),'record_types':types,'metadata_url':BASE+'/files/'+str(ident)+'/','viewer_url':scans[0]['viewer_url'] if scans else None,'public_scan_count':len(scans) if scans else None,'access_status':'public_digitized_viewer' if scans else 'catalog_entry_only_order_button_no_public_viewer_observed','scans':scans,'source_snapshot':str(path),'source_snapshot_sha256':hashlib.sha256(raw).hexdigest(),'verified_at':'2026-10-15','limitations':['Catalog date interval may differ from years enumerated in the title.','Catalog folio count is not a scan count.','Viewer labels are not asserted to be handwritten folio numbers.','Metadata and scan links inventoried; pages have not all been read or OCRed.']})
    search=json.loads((OUT/'search-all-acts.json').read_text(encoding='utf-8'))['View'];all_results=[]
    for m in re.finditer(r'<p class="doc-title">(.*?)</p>.*?<p class="date">(.*?)</p>.*?<a href="/files/(\d+)/"',search,re.S):all_results.append({'id':int(m[3]),'title':clean(m[1]),'dates_and_folios':clean(m[2]),'url':BASE+'/files/'+m[3]+'/','included_metric_book':int(m[3]) in IDS})
    local=[];secondary=Path('C:/Users/inst/Desktop/родовід/wikisource_201_4a.raw')
    if secondary.exists():
        text=secondary.read_text(encoding='utf-8')
        for book in books:
            if book['fonds']=='201':
                row=next((line for line in text.splitlines() if '/'+book['case']+'/' in line),None)
                if row:local.append({'path':str(secondary),'case':book['case'],'raw_row':row,'status':'local_secondary_inventory_cross_reference_not_primary_metadata'})
    for case in ['8448','8449']:
        path=Path('C:/Users/inst/Desktop/родовід')/('FamilySearch_201-4a-'+case)/('manifest_'+case+'.json')
        if path.exists():
            manifest=json.loads(path.read_text(encoding='utf-8'));local.append({'path':str(path),'fonds':'201','inventory':'4а','case':case,'downloaded_count':manifest.get('count'),'image_group':manifest.get('imageGroupNumber'),'status':'nearby_context_Maidan_Holohirskyi_Stinka_not_automatically_equated_to_Lipivtsi','metadata_title_snapshot':str(Path('C:/Users/inst/Desktop/родовід')/('archium_files_'+('145721' if case=='8448' else '145722')+'_'+case+'.html'))})
    report={'place':'Липівці, колишній повіт Перемишляни','verified_at':'2026-10-15','scope':'Official catalog exact place search Липівці plus the seven supplied links; eight metric-book entries, including a Roman Catholic multi-parish volume. This is not a guarantee about uncataloged holdings or differently titled parish volumes.','search_url':BASE+'/search/act?q=%D0%9B%D0%B8%D0%BF%D1%96%D0%B2%D1%86%D1%96&search_type=all&fond_number=0','search_results':all_results,'metric_books':books,'public_scan_links':sum(len(b['scans']) for b in books),'local_cross_references':local,'record_identification_policy':'A precise person/date/folio is attached only after reading the image; archive image labels and nearby years alone do not identify a person.'}
    assert len(all_results)==14 and len(books)==8 and report['public_scan_links']==990
    (OUT/'lipivtsi-catalog.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Каталог метричних книг Липівців','', 'Перевірено 15.10.2026 за офіційним каталогом ЦДІАЛ. Пошук «Липівці» повернув 14 справ, із них 8 метричних. До семи посилань із дошки додано римо-католицьку справу 618/2/3181. Це перелік знайдених описів і доступних сканів, а не прочитання всіх сторінок.','', '| Фонд / опис / справа | Дати каталогу | Зміст | Аркуші за описом | Сканів у переглядачі | Офіційне джерело |','|---|---|---|---:|---:|---|']
    for b in books:lines.append('| '+b['fonds']+' / '+b['inventory']+' / '+b['case']+' | '+b['catalog_dates']+' | '+b['title']+' | '+str(b['catalog_folios'])+' | '+(str(b['public_scan_count']) if b['public_scan_count'] else 'публічного перегляду не виявлено')+' | [опис]('+b['metadata_url']+')'+(' · [скани]('+b['viewer_url']+')' if b['viewer_url'] else '')+' |')
    lines+=['','У шести публічних переглядачах перевірено перелік із **990 прямих посилань на скани**. Повний упорядкований перелік збережено в JSON. Книги 9225 і 9226 мають картки опису з кнопкою замовлення; доступного публічного переглядача під час перевірки не було. Це не означає відсутність інших копій на інших ресурсах.','','Важливі розрізнення: кількість аркушів ≠ кількість сканів; підпис зображення у переглядачі ≠ номер аркуша, прочитаний на документі. Для 2984, 2985 і 6268 роки, перелічені в заголовку, відрізняються від загального діапазону дат картки; обидва значення збережені без виправлення.','','Місцевий файл wikisource_201_4a.raw використано лише для перехресної перевірки. У ньому деякі заголовки скорочені як «Те саме», тому простий пошук назви села пропускає сусідні справи. Місцеві завантаження FamilySearch 8448/8449 стосуються Майдану Гологірського і Стінки; їх не прирівняно автоматично до Липівців або Майдану Липовецького.','','## Інші знайдені справи','']
    for item in all_results:
        if not item['included_metric_book']:lines.append('- ['+str(item['id'])+']('+item['url']+') — '+item['title']+' ('+item['dates_and_folios']+').')
    lines+=['','Конкретний запис людини, дата й рукописний номер аркуша потребують окремого прочитання зображення. Каталог сам по собі не підтверджує родинний зв’язок.']
    (OUT/'lipivtsi-catalog.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    esc=html.escape
    page=['<!doctype html><html lang="uk"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Липівці — каталог архівних книг</title><style>body{font:16px/1.5 system-ui,sans-serif;max-width:1150px;margin:40px auto;padding:0 20px;background:#f8f7f2;color:#242923}h1,h2{line-height:1.2}a{color:#175a71}table{border-collapse:collapse;width:100%;background:white}td,th{padding:12px;text-align:left;border-bottom:1px solid #ddd;vertical-align:top}.note{padding:16px;background:#fff4d9;border-radius:8px}details{background:white;margin:12px 0;padding:16px;border-radius:8px}summary{cursor:pointer;font-weight:bold}.scans{display:grid;grid-template-columns:repeat(auto-fill,minmax(245px,1fr));gap:8px;margin-top:18px}.scan{border:1px solid #deded7;padding:8px;border-radius:4px}small{color:#59645d}</style><h1>Липівці: метричні книги</h1><p>Перевірено 15.10.2026. 8 метричних справ, 6 публічних переглядачів, 990 посилань на скани.</p><p class="note">Прочитано описи й перевірено переліки сканів. Усі сторінки цих книг ще не прочитані та не розпізнані. Підпис зображення і номер рукописного аркуша можуть відрізнятися.</p><table><thead><tr><th>Шифр</th><th>Назва й роки</th><th>Доступ</th></tr></thead><tbody>']
    for book in books:
        code=book['fonds']+'/'+book['inventory']+'/'+book['case'];ident=str(book['archive_file_id'])
        page.append('<tr><td><a href="#book-'+ident+'">'+esc(code)+'</a></td><td>'+esc(book['title'])+'<br><small>Дати картки: '+esc(book['catalog_dates'])+'; '+str(book['catalog_folios'])+' аркушів за описом</small></td><td><a href="'+esc(book['metadata_url'],quote=True)+'">Офіційний опис</a><br>'+('Сканів: '+str(book['public_scan_count']) if book['public_scan_count'] else 'Картка з кнопкою замовлення; публічного перегляду не виявлено')+'</td></tr>')
    page.append('</tbody></table><h2>Перехід до конкретного скану</h2><p>Розгорни книгу. «Скан» відкриває точне місце в офіційному переглядачі; «зображення» — файл скану. Порядок відповідає переліку архівного сайту.</p>')
    for book in books:
        code=book['fonds']+'/'+book['inventory']+'/'+book['case'];ident=str(book['archive_file_id']);page.append('<details id="book-'+ident+'"><summary>'+esc(code)+' · '+esc(book['catalog_dates'])+' · '+str(book['public_scan_count'] or 0)+' публічних сканів</summary><p>'+esc(book['title'])+'</p>')
        if book['scans']:
            page.append('<div class="scans">')
            for scan in book['scans']:page.append('<div class="scan" id="scan-'+scan['file_id']+'"><a href="'+esc(scan['viewer_url'],quote=True)+'">Скан '+str(scan['scan_position'])+'</a> · <a href="'+esc(scan['image_url'],quote=True)+'">зображення</a><br><small>Підпис архіву: '+esc(scan['archive_image_label'])+'; ID '+scan['file_id']+'</small></div>')
            page.append('</div>')
        else:page.append('<p>Публічних зображень у цьому переглядачі під час перевірки не виявлено. <a href="'+esc(book['metadata_url'],quote=True)+'">Опис і замовлення</a>.</p>')
        page.append('</details>')
    page.append('<p>Джерело: офіційний каталог ЦДІАЛ. <a href="lipivtsi-catalog.json">Повний JSON з джерелами й контрольними сумами</a> · <a href="lipivtsi-catalog.md">Текстовий звіт</a> · <a href="polish-sources.html">Польські джерела AGAD</a></p></html>')
    (OUT/'lipivtsi-catalog.html').write_text('\n'.join(page),encoding='utf-8')
    print(json.dumps({'metric_books':len(books),'catalog_results':len(all_results),'public_scan_links':report['public_scan_links']}))

if __name__=='__main__':main()
