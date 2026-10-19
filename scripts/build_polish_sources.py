"""Verify supplied AGAD reference and keep parish/denomination distinctions explicit."""
import hashlib
import html
import json
from pathlib import Path
import re
from urllib.parse import quote,urljoin
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'test-output/philip-source-research'

def clean(s):return re.sub(r'\s+',' ',html.unescape(re.sub('<[^>]+>',' ',s))).strip()

def main():
    board=json.loads((ROOT/'test-output/figma-family-tree/raw-board.json').read_text(encoding='utf-8'));board_links={}
    for node in board['nodes']:
        for url in re.findall(r'https?://[^\s<>]+',node.get('text','')):
            if 'agad' in url or '.pl/' in url:board_links.setdefault(url,[]).append(node['id'])
    books=[]
    for fonds,case in [('298','338'),('301','331'),('301','335'),('301','336')]:
        source=OUT/('agad-'+fonds+'-official.xml');text=source.read_text(encoding='utf-8');match=re.search(r'<b>Sygn\.:\s*</b></td>\s*<td><b>'+case+r'</b>',text)
        if not match:raise ValueError('Official inventory unit missing.')
        end=text.find('<hr color="red">',match.end());block=text[match.start():end];fields={clean(k).rstrip(':').strip():clean(v) for k,v in re.findall(r'<b>(.*?)</b></td>\s*<td[^>]*>(.*?)</td>',block,re.S)}
        base=('http://agadd2.home.net.pl/metrykalia/298/sygn.%20338/' if fonds=='298' else 'http://agadd.home.net.pl/metrykalia/301/sygn.%20'+case+'/');paths=[]
        snapshots=[OUT/'agad-338-indeks.htm'] if fonds=='298' else sorted(OUT.glob('agad-301-'+case+'-indeks*.htm'))
        for path in snapshots:
            for link in re.findall(r'href="(pages/[^"#]+\.htm)"',path.read_text(encoding='windows-1250'),re.I):
                if link not in paths:paths.append(link)
        paths.sort(key=lambda p:p.casefold())
        scans=[{'gallery_position':i,'page_url':urljoin(base,quote(link,safe='/._-')),'image_url':urljoin(base,quote(link.replace('pages/','images/').removesuffix('.htm')+'.jpg',safe='/._-')),'filename':link.split('/')[-1].removesuffix('.htm')} for i,link in enumerate(paths,1)]
        books.append({'archive':'Archiwum Główne Akt Dawnych, Warszawa','fonds':fonds,'case':case,'archival_reference':'PL 1/'+fonds+'/'+case,'parish':'Przemyślany' if fonds=='298' else 'Gołogóry','denomination':'Greek Catholic' if fonds=='298' else 'Roman Catholic','title':fields.get('Tytuł'),'dates':fields.get('Daty'),'description':fields.get('Opis'),'language':fields.get('Język'),'old_reference':fields.get('Dawna Sygn.'),'metadata_url':'https://agad.gov.pl/inwentarze/ksGrec298.xml' if fonds=='298' else 'https://www.agad.gov.pl/inwentarze/KLwo301new.xml','gallery_url':base+'indeks.htm','scan_count':len(scans),'scans':scans,'source_snapshot_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'relation_to_board':'explicit URL on board node 4:1928' if fonds=='298' else 'additional official Lipowce-related Roman Catholic inventory entry; no automatic person/Greek-Catholic matching'})
    local=Path('C:/Users/inst/Desktop/родовід/1_298_0_0_338_0013.jpg');download=OUT/'agad-338-0013.jpg';local_sha=hashlib.sha256(local.read_bytes()).hexdigest();remote_sha=hashlib.sha256(download.read_bytes()).hexdigest();assert local_sha==remote_sha
    evidence={'archival_reference':'AGAD PL 1/298/338','board_node':'4:1928','page_url':next(iter(board_links)),'image_url':'http://agadd2.home.net.pl/metrykalia/298/sygn.%20338/images/1_298_0_0_338_0013.jpg','scan_filename':'1_298_0_0_338_0013','scan_number_in_filename':13,'handwritten_page_numbers':['16','17'],'record_type_visible':'birth/baptism register, headings Natus/Baptisatus, Parentes and Patrini','visible_years':['1832','1833'],'visual_locator':'Cosma is on the left page, third principal row, house 150. Barbara is visible in the parent column. Full diplomatic reading and identity proof remain separate work.','local_path':str(local),'downloaded_copy':str(download),'sha256':local_sha,'exact_bytes_match':True,'limitations':['Not a death register image.','Do not equate scan 13 with handwritten page 13.','Current official unit 338 is explicitly births only; older local inventory wording is broader.','Source citation and image identity are verified; surname normalization and kinship require independent row reading.']}
    report={'verified_at':'2026-10-15','polish_urls_in_board':board_links,'polish_url_count':len(board_links),'books':books,'provided_scan':evidence,'policy':'Only one Polish archival URL was found in preserved board text. Additional Roman Catholic Lipowce volumes are catalog leads, not proof that their people match the Greek Catholic Przemyślany family.'}
    assert len(board_links)==1 and len(books[0]['scans'])==56
    (OUT/'polish-sources.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    esc=html.escape;page=['<!doctype html><html lang="uk"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Польські архівні джерела</title><style>body{font:16px/1.5 system-ui,sans-serif;max-width:1100px;margin:40px auto;padding:0 20px;background:#f8f7f2;color:#242923}a{color:#175a71}table{width:100%;border-collapse:collapse;background:white}td,th{padding:12px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}.note{background:#fff0cd;padding:16px;border-radius:8px}details{background:white;margin:12px 0;padding:16px}.scans{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px}</style><h1>Польські джерела з дошки родоводу</h1><p>Перевірено 15.10.2026. У тексті збереженої дошки знайдено одне польське архівне посилання: AGAD, фонд 298, справа 338, скан 0013.</p><p class="note">Це греко-католицька книга народжень парафії Перемишляни за 1829–1848 роки. Надане зображення — розворот народжень/хрещень 1832–1833 років, а не книга смертей. Скан 0013 показує рукописні сторінки 16–17.</p><p><a href="'+esc(evidence['page_url'],quote=True)+'">Відкрити саме наданий скан</a> · <a href="'+esc(evidence['image_url'],quote=True)+'">Оригінальне зображення</a> · <a href="agad-338-0013.jpg">Перевірена місцева копія</a></p><p>Завантажений з архівного сервера JPG побайтово збігається з твоїм файлом <code>1_298_0_0_338_0013.jpg</code>. SHA-256: <code>'+local_sha+'</code>.</p><p>На лівій сторінці в третьому основному рядку видно Cosma, будинок 150; у колонці батьків видно Barbara. Повне прочитання рядка й підтвердження особи виконуються окремо.</p><h2>Перевірені книги та додаткові вказівки</h2><table><tr><th>Шифр</th><th>Парафія / обряд</th><th>Зміст і роки</th><th>Скани</th></tr>']
    for book in books:page.append('<tr><td>'+esc(book['archival_reference'])+'</td><td>'+esc(book['parish'])+'<br>'+('греко-католицька' if book['fonds']=='298' else 'римо-католицька')+'</td><td>'+esc(book['title'] or '')+'<br>'+esc(book['dates'] or '')+'<br><a href="'+esc(book['metadata_url'],quote=True)+'">Офіційний опис</a></td><td><a href="'+esc(book['gallery_url'],quote=True)+'">Галерея</a><br>'+str(book['scan_count'])+'</td></tr>')
    page.append('</table><p class="note">Римо-католицькі книги Гологір, що згадують Lipowce, збережені як додаткові джерела. Вони не доводять тотожність людей із греко-католицькою родиною в Перемишлянах.</p>')
    for book in books:
        page.append('<details><summary>'+esc(book['archival_reference'])+' — перелік сканів</summary><div class="scans">')
        for scan in book['scans']:page.append('<div><a href="'+esc(scan['page_url'],quote=True)+'">'+esc(scan['filename'])+'</a> · <a href="'+esc(scan['image_url'],quote=True)+'">JPG</a></div>')
        page.append('</div></details>')
    page.append('<p><a href="polish-sources.json">Повний JSON</a> · <a href="lipivtsi-catalog.html">Український каталог Липівців</a></p></html>');(OUT/'polish-sources.html').write_text('\n'.join(page),encoding='utf-8');print(json.dumps({'board_polish_urls':len(board_links),'books':len(books),'counts':{b['archival_reference']:b['scan_count'] for b in books},'local_original_matches':True}))

if __name__=='__main__':main()
