"""Archival source cards, page locators and generated citations."""
import hashlib
import json
from urllib.parse import urlsplit

try:
    from .workbench import Workbench
except ImportError:
    from workbench import Workbench

BOOK_FIELDS=['archive','country','collection','fonds','inventory','file','title','place','url','accessed','rights','notes']
PAGE_FIELDS=['folio','page_url','page_notes','original_page','image_number','scan_label','entry_number']
EXPORT_FIELDS=[('source_'+key,label) for key,label in [
    ('archive','Архів'),('country','Країна джерела'),('collection','Колекція'),('fonds','Фонд'),
    ('inventory','Опис'),('file','Справа'),('title','Назва джерела'),('place','Місце джерела'),
    ('folio','Аркуш (оригінальна нумерація)'),('url','Посилання на джерело'),('accessed','Дата доступу'),
    ('rights','Права доступу / використання'),('notes','Примітки джерела'),('page_notes','Примітки аркуша'),('citation','Посилання для цитування'),('original_page','Написаний номер сторінки'),('image_number','Номер скану в архіві'),('scan_label','Позначення зображення'),('entry_number','Номер запису в джерелі')]]


def signature(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def validate_url(value):
    if not value: return
    parsed=urlsplit(value)
    if parsed.scheme not in ['https','http'] or not parsed.hostname or any(ord(c)<32 for c in value):
        raise ValueError('Вкажіть повне посилання HTTP або HTTPS.')


class SourceTools(Workbench):
    def __init__(self,engine):
        super().__init__(engine)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS book_sources(doc TEXT PRIMARY KEY REFERENCES documents(id),data TEXT);
        CREATE TABLE IF NOT EXISTS page_sources(page TEXT PRIMARY KEY REFERENCES pages(id),data TEXT);
        CREATE TABLE IF NOT EXISTS source_history(id INTEGER PRIMARY KEY,doc TEXT,page TEXT,before TEXT,after TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')

    def source_card(self,a):
        page=self.engine.page(a['id'])
        current=self.read_card(page)
        if 'book' in a or 'page_values' in a:
            if a.get('expected') and a['expected']!=current['signature']:
                raise ValueError('Результат змінився. Оновіть список.')
            book={k:str(a.get('book',current['book']).get(k,'')).strip() for k in BOOK_FIELDS}
            values={k:str(a.get('page_values',current['page_values']).get(k,'')).strip() for k in PAGE_FIELDS}
            for url in [book['url'],values['page_url']]: validate_url(url)
            with self.db:
                before={'book':current['book'],'page_values':current['page_values']}
                after={'book':book,'page_values':values}
                if before!=after:
                    self.db.execute('INSERT INTO source_history(doc,page,before,after) VALUES (?,?,?,?)',
                        (page['doc'],page['id'],json.dumps(before,ensure_ascii=False),json.dumps(after,ensure_ascii=False)))
                self.db.execute('INSERT INTO book_sources VALUES (?,?) ON CONFLICT(doc) DO UPDATE SET data=excluded.data',(page['doc'],json.dumps(book,ensure_ascii=False)))
                group=self.photo_book(page['doc'])
                if group:
                    group_data=json.loads(group['data']);group_data['source']=book
                    self.db.execute('UPDATE photo_books SET data=? WHERE id=?',(json.dumps(group_data,ensure_ascii=False),group['id']))
                self.db.execute('INSERT INTO page_sources VALUES (?,?) ON CONFLICT(page) DO UPDATE SET data=excluded.data',(page['id'],json.dumps(values,ensure_ascii=False)))
            current=self.read_card(page)
        return current

    def read_card(self,page):
        chain=[]; cursor=page; seen=set()
        while cursor['id'] not in seen:
            seen.add(cursor['id']); chain.append(cursor)
            parent=self.db.execute('SELECT parent_page FROM derivatives WHERE doc=?',(cursor['doc'],)).fetchone()
            if not parent: break
            cursor=self.engine.page(parent['parent_page'])
        book=values=None; inherited=False
        group=self.photo_book(page['doc'])
        if group:
            book=json.loads(group['data']).get('source')
        for item in chain:
            if book is None:
                row=self.db.execute('SELECT data FROM book_sources WHERE doc=?',(item['doc'],)).fetchone()
                if row: book=json.loads(row['data']); inherited|=item['id']!=page['id']
            if values is None:
                row=self.db.execute('SELECT data FROM page_sources WHERE page=?',(item['id'],)).fetchone()
                if row: values=json.loads(row['data']); inherited|=item['id']!=page['id']
        book={k:(book or {}).get(k,'') for k in BOOK_FIELDS}; values={k:(values or {}).get(k,'') for k in PAGE_FIELDS}
        origin=chain[-1]
        parts=[book[k] for k in ['archive','collection','title'] if book[k]]
        if not parts: parts=[origin['name']]
        if group and not any(book[k] for k in ['archive','collection','title']):parts=[group['name']]
        for key,prefix in [('fonds','ф.'),('inventory','оп.'),('file','спр.')]:
            if book[key]: parts.append(prefix+' '+book[key])
        if values['folio']: parts.append('арк. '+values['folio'])
        if values['original_page']: parts.append('стор. '+values['original_page'])
        parts.append('скан '+(values['image_number'] or str(origin['num']+1)))
        if values['scan_label']: parts.append('зображення '+values['scan_label'])
        if values['entry_number']: parts.append('запис '+values['entry_number'])
        if group:
            item=self.db.execute('SELECT position,label FROM book_items WHERE book=? AND page=?',(group['id'],page['id'])).fetchone()
            if item:parts.append('сторінка збірки '+str(item['position']+1)+(('; '+item['label']) if item['label'] else ''))
        url=values['page_url'] or book['url']
        if url: parts.append(url)
        if book['accessed']: parts.append('дата доступу: '+book['accessed'])
        payload={'book':book,'page_values':values,'origin_page':origin['id'],'scan_page':origin['num']+1,
                 'inherited':inherited,'citation':'; '.join(parts)}
        payload['signature']=signature(payload)
        return payload

    def export_values(self,card):
        values=card['book']|card['page_values']|{'url':card['page_values']['page_url'] or card['book']['url'],'citation':card['citation']}
        return {key:values.get(key.removeprefix('source_'),'') for key,_ in EXPORT_FIELDS}
