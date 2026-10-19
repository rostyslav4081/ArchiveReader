"""Bounded metadata windows; source frame numbers remain immutable."""
import hashlib
import json
try:
    from .books import BookTools
except ImportError:
    from books import BookTools


class PagingTools(BookTools):
    def __init__(self,engine):
        super().__init__(engine)
        # A scalar revision detects updates without reading/hashing every book
        # item on each window request. Triggers also cover other connections and
        # in-place changes that preserve row counts and reuse SQLite rowids.
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS paging_revision(id INTEGER PRIMARY KEY CHECK(id=1),version INTEGER NOT NULL);
        INSERT OR IGNORE INTO paging_revision VALUES (1,0);
        """)
        updates={'pages':'id,doc,num,status,text','documents':'id,name,path',
                 'records':'id,page,data','book_items':'book,page,position,label',
                 'photo_books':'id,name'}
        for table,columns in updates.items():
            for event in ['insert','update','delete']:
                clause=' OF '+columns if event=='update' else ''
                self.db.execute(f"""CREATE TRIGGER IF NOT EXISTS paging_{table}_{event}_v1
                    AFTER {event}{clause} ON {table} BEGIN
                    UPDATE paging_revision SET version=version+1 WHERE id=1;
                    END""")
        self.db.commit()

    def _page_query(self,query):
        sql='''WITH anchor_docs AS (
          SELECT i.book,MIN(d.rowid) AS anchor_doc FROM book_items i
          JOIN pages p ON p.id=i.page JOIN documents d ON d.id=p.doc GROUP BY i.book
        ), anchors AS (
          SELECT i.book,a.anchor_doc,MIN(p.num) AS anchor_num FROM book_items i
          JOIN pages p ON p.id=i.page JOIN documents d ON d.id=p.doc
          JOIN anchor_docs a ON a.book=i.book AND a.anchor_doc=d.rowid GROUP BY i.book
        ), matched AS (
          SELECT p.id,p.doc,p.num,p.status,d.name,d.path,i.book,i.position AS book_index,
            i.label AS book_label,b.name AS book_name,d.rowid AS doc_order,p.rowid AS page_order,
            COALESCE(a.anchor_doc,d.rowid) AS group_doc,COALESCE(a.anchor_num,p.num) AS group_num,
            CASE WHEN i.book IS NULL THEN 0 ELSE i.position END AS group_position
          FROM pages p JOIN documents d ON d.id=p.doc
          LEFT JOIN book_items i ON i.page=p.id AND i.rowid=(SELECT MIN(first.rowid) FROM book_items first WHERE first.page=p.id)
          LEFT JOIN photo_books b ON b.id=i.book LEFT JOIN anchors a ON a.book=i.book
        '''
        params=[]
        if query:
            sql+='''WHERE d.name LIKE ? OR b.name LIKE ? OR p.text LIKE ?
              OR EXISTS (SELECT 1 FROM records r WHERE r.page=p.id AND r.data LIKE ?)'''
            params=['%'+query+'%']*4
        sql+='''), ordered AS (
          SELECT matched.*,ROW_NUMBER() OVER (
            ORDER BY group_doc,group_num,group_position,doc_order,num,page_order,id
          )-1 AS window_position FROM matched
        ) '''
        return sql,params

    def pages_window(self,a):
        if self.db.in_transaction:return self._pages_window(a)
        with self.db:
            self.db.execute("BEGIN")
            return self._pages_window(a)

    def _pages_window(self,a):
        limit=max(1,min(200,int(a.get('limit',200))));offset=max(0,int(a.get('offset',0)));query=str(a.get('query',a.get('search',''))).strip()
        sql,params=self._page_query(query)
        total=self.db.execute(sql+'SELECT COUNT(*) FROM matched',params).fetchone()[0] if query else self.db.execute('SELECT COUNT(*) FROM pages').fetchone()[0]
        locate=a.get('locate');located=None
        offset=min(offset,((total-1)//limit)*limit) if total else 0
        rows_sql=sql+'SELECT * FROM matched ORDER BY group_doc,group_num,group_position,doc_order,num,page_order,id LIMIT ? OFFSET ?'
        fetched=list(self.db.execute(rows_sql,params+[limit,offset]))
        if locate:
            local=next((i for i,row in enumerate(fetched) if row['id']==locate),None)
            if local is not None:located=offset+local
            else:
                row=self.db.execute(sql+'SELECT window_position FROM ordered WHERE id=?',params+[locate]).fetchone()
                if row:
                    located=row['window_position'];offset=located//limit*limit
                    fetched=list(self.db.execute(rows_sql,params+[limit,offset]))
        rows=[]
        for row in fetched:
            values={key:row[key] for key in ['id','doc','num','status','name','path']}
            values['label']=f"{row['name']} · {row['num']+1} · {row['status']}"
            if row['book']:
                values.update(book=row['book'],book_position=row['book_index']+1,book_name=row['book_name'],display_name=f"{row['book_name']} · {row['book_index']+1} · {row['book_label'] or row['name']}")
            rows.append(values)
        state=[query,total,self.db.execute('SELECT version FROM paging_revision WHERE id=1').fetchone()[0]]
        snapshot=hashlib.sha256(json.dumps(state,ensure_ascii=False).encode()).hexdigest()
        return {'rows':rows,'total':total,'offset':offset,'limit':limit,'has_more':offset+len(rows)<total,'snapshot':snapshot,'snapshot_changed':bool(a.get('snapshot') and a['snapshot']!=snapshot),'located':located,'locate_missing':bool(locate and located is None)}

    def book_page_ids(self,a):
        page=self.engine.page(a['page']);member=self.db.execute('SELECT book FROM book_items WHERE page=? ORDER BY rowid LIMIT 1',(page['id'],)).fetchone()
        pending=a.get('pending_only',True)
        if member:
            return [r['id'] for r in self.db.execute('SELECT p.id,p.status FROM book_items i JOIN pages p ON p.id=i.page WHERE i.book=? ORDER BY i.position,i.rowid',(member['book'],)) if not pending or r['status']!='done']
        return [r['id'] for r in self.db.execute('SELECT id,status FROM pages WHERE doc=? ORDER BY num,rowid',(page['doc'],)) if not pending or r['status']!='done']
