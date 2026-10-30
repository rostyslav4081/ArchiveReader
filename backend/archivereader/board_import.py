"""Lossless, explicitly mapped FigJam snapshots. Canvas links are never kinship facts."""
import hashlib
import json
from pathlib import Path
import uuid
try:
    from .genealogy import GenealogyTools
except ImportError:
    from genealogy import GenealogyTools


class BoardTools(GenealogyTools):
    def __init__(self, engine):
        super().__init__(engine)
        self.db.executescript('''CREATE TABLE IF NOT EXISTS board_imports(id TEXT PRIMARY KEY, board_key TEXT UNIQUE, sha TEXT, raw BLOB, mapping TEXT, data TEXT);
        CREATE TABLE IF NOT EXISTS board_assets(id TEXT PRIMARY KEY, board TEXT REFERENCES board_imports(id), node TEXT, kind TEXT, sha TEXT, raw BLOB);
        CREATE TABLE IF NOT EXISTS board_semantics(board TEXT PRIMARY KEY REFERENCES board_imports(id),revision INTEGER,data TEXT);
        CREATE TABLE IF NOT EXISTS board_semantics_history(id INTEGER PRIMARY KEY,board TEXT REFERENCES board_imports(id),before TEXT,after TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);''')

    def board_set_semantics(self,a):
        board=self.board_get({'id':a['id']})
        if a.get('expected_sha')!=board['sha']:raise ValueError('Board snapshot changed. Preview again.')
        previous=self.db.execute('SELECT * FROM board_semantics WHERE board=?',(a['id'],)).fetchone()
        revision=previous['revision'] if previous else 0
        if 'expected_revision' in a and a['expected_revision']!=revision:raise ValueError('Board semantics changed. Reload before editing.')
        if a.get('path'):
            source=json.loads(Path(a['path']).read_text(encoding='utf-8-sig'))
            snapshot=board['snapshot']
            if source.get('fileKey')!=snapshot['fileKey'] or source.get('pageId')!=snapshot['pageId']:raise ValueError('Semantics belong to a different board.')
            if source.get('legend')!={'red':'incorrect','yellow':'unresolved','other':'logically_consistent'}:raise ValueError('Explicit board color legend required.')
            connector_ids={n['id'] for n in snapshot['nodes'] if n.get('type')=='CONNECTOR'}
            items=source.get('connectors',[])
            if len(items)!=len(connector_ids) or {n['id'] for n in items}!=connector_ids:raise ValueError('Semantics must preserve every connector exactly once.')
            values={'source':source,'policy':'User-provided board legend; logically consistent is not archival verification.','connectors':{}}
            for item in items:
                paint=next((p for p in item.get('strokes',[]) if p.get('type')=='SOLID' and p.get('visible',True)),{})
                color=paint.get('color',{});r,g,b=(float(color.get(k,0)) for k in ['r','g','b'])
                status='incorrect' if r>.8 and g<.5 else 'unresolved' if r>.8 and g>.6 and b<.4 else 'logically_consistent'
                values['connectors'][item['id']]={'status':status,'color':color,'reason':'User-provided color legend','origin':'board_color','archive_verified':False}
        elif previous:values=json.loads(previous['data'])
        else:raise ValueError('Load the board color legend first.')
        for override in a.get('overrides',[]):
            if override.get('connector') not in values['connectors'] or override.get('status') not in ['incorrect','unresolved','logically_consistent'] or not override.get('reason','').strip():raise ValueError('Manual connector override requires a valid connector, status and reason.')
            values['connectors'][override['connector']].update({'status':override['status'],'reason':override['reason'].strip(),'origin':'manual_override','archive_verified':False})
        encoded=json.dumps(values,ensure_ascii=False,sort_keys=True)
        if previous and previous['data']==encoded:return self.board_get({'id':a['id']})
        with self.db:
            self.db.execute('INSERT INTO board_semantics_history(board,before,after) VALUES (?,?,?)',(a['id'],previous['data'] if previous else None,encoded))
            self.db.execute('INSERT INTO board_semantics VALUES (?,?,?) ON CONFLICT(board) DO UPDATE SET revision=excluded.revision,data=excluded.data',(a['id'],revision+1,encoded))
        return self.board_get({'id':a['id']})

    def board_preview(self, a):
        raw=Path(a['path']).read_bytes()
        if len(raw)>25_000_000: raise ValueError('Board snapshot exceeds 25 MB.')
        data=json.loads(raw.decode('utf-8-sig'));nodes=data.get('nodes',[])
        if not data.get('fileKey') or not data.get('pageId') or not isinstance(nodes,list): raise ValueError('Invalid board snapshot.')
        ids=[n['id'] for n in nodes]
        if len(ids)!=len(set(ids)): raise ValueError('Duplicate board node IDs.')
        return {'sha':hashlib.sha256(raw).hexdigest(),'board_key':data['fileKey']+':'+data['pageId'],'nodes':nodes,'raw':data,
                'counts':{'nodes':len(nodes),'connectors':sum(n.get('type')=='CONNECTOR' for n in nodes),'image_nodes':sum(bool(n.get('images')) for n in nodes)},
                'policy':'Canvas connectors remain unverified; select person nodes explicitly. Notes and original spellings are preserved.'}

    def board_import(self,a):
        preview=self.board_preview(a)
        if preview['sha']!=a.get('sha'): raise ValueError('Preview changed. Preview again.')
        selected=sorted(set(a.get('people',[])));nodes={n['id']:n for n in preview['nodes']}
        if any(i not in nodes or nodes[i].get('type') not in ['SHAPE_WITH_TEXT','TEXT'] or not nodes[i].get('text','').strip() for i in selected): raise ValueError('Invalid person-node mapping.')
        mapping=json.dumps(selected);old=self.db.execute('SELECT * FROM board_imports WHERE board_key=?',(preview['board_key'],)).fetchone()
        assets=[]
        if a.get('assets'):
            for asset in json.loads(Path(a['assets']).read_text(encoding='utf-8')):
                if asset['node'] not in nodes: raise ValueError('Asset node missing from snapshot.')
                raw=Path(asset['path']).read_bytes();sha=hashlib.sha256(raw).hexdigest()
                if not raw or len(raw)>100_000_000: raise ValueError('Asset is empty or exceeds 100 MB.')
                from PIL import Image
                import io
                try:
                    with Image.open(io.BytesIO(raw)) as image: image.verify()
                except Exception as error: raise ValueError('Asset is not a readable image.') from error
                if sha!=asset['sha256']: raise ValueError('Asset checksum mismatch.')
                assets.append((asset,raw,sha))
        asset_signature=sorted((asset['node'],asset.get('kind','source'),sha) for asset,raw,sha in assets)
        if old:
            if old['sha']!=preview['sha'] or old['mapping']!=mapping or json.loads(old['data']).get('asset_signature')!=[list(x) for x in asset_signature]: raise ValueError('Board already imported with different content, mapping or assets. Existing import was preserved.')
            return self.board_get({'id':old['id']})|{'already_imported':True}
        ident=uuid.uuid4().hex;persons={i:uuid.uuid4().hex for i in selected}
        data={'persons':persons,'counts':preview['counts'],'asset_signature':asset_signature,'asset_count':len(assets),'source_url':'https://www.figma.com/board/'+preview['raw']['fileKey']+'?node-id='+preview['raw']['pageId'].replace(':','-'),'status':'user_source_unverified'}
        with self.db:
            self.db.execute('INSERT INTO board_imports VALUES (?,?,?,?,?,?)',(ident,preview['board_key'],preview['sha'],Path(a['path']).read_bytes(),mapping,json.dumps(data,ensure_ascii=False)))
            for node,person in persons.items():
                text=nodes[node]['text'];name=text.splitlines()[0].strip()
                values={'name':name,'notes':text,'unverified_import':True,'board_import':ident,'source_node':node,'source_url':data['source_url'],'events':[]}
                self.db.execute('INSERT INTO persons VALUES (?,?)',(person,json.dumps(values,ensure_ascii=False)))
            for asset,raw,sha in assets:
                self.db.execute('INSERT INTO board_assets VALUES (?,?,?,?,?,?)',(uuid.uuid4().hex,ident,asset['node'],asset.get('kind','source'),sha,raw))
        return self.board_get({'id':ident})

    def board_list(self,a):
        return [dict(id=r['id'],**json.loads(r['data'])) for r in self.db.execute('SELECT id,data FROM board_imports ORDER BY rowid')]

    def board_get(self,a):
        row=self.db.execute('SELECT * FROM board_imports WHERE id=?',(a['id'],)).fetchone()
        if not row: raise ValueError('Board import not found.')
        data=json.loads(row['data']);snapshot=json.loads(row['raw'])
        data['person_styles']={}
        for node,person in data.get('persons',{}).items():
            stored=self.db.execute('SELECT data FROM persons WHERE id=?',(person,)).fetchone()
            if stored and json.loads(stored['data']).get('board_style'):data['person_styles'][node]=json.loads(stored['data'])['board_style']
        semantics=self.db.execute('SELECT * FROM board_semantics WHERE board=?',(a['id'],)).fetchone()
        if semantics:data['semantics']=json.loads(semantics['data'])|{'revision':semantics['revision']}
        assets=[dict(r) for r in self.db.execute('SELECT id,node,kind,sha FROM board_assets WHERE board=?',(a['id'],))]
        if a.get('export'):
            target=Path(a['export']);target.mkdir(parents=True,exist_ok=True)
            (target/'board.json').write_bytes(row['raw'])
            if semantics:(target/'connector-semantics.json').write_text(json.dumps(data['semantics'],ensure_ascii=False,indent=2),encoding='utf-8')
            for asset in assets:
                raw=self.db.execute('SELECT raw FROM board_assets WHERE id=?',(asset['id'],)).fetchone()['raw']
                from PIL import Image
                import io
                ext=Image.open(io.BytesIO(raw)).format.lower()
                path=target/(asset['id']+'.'+ext);path.write_bytes(raw);asset['path']=str(path.resolve())
            (target/'manifest.json').write_text(json.dumps(data|{'assets':assets},ensure_ascii=False,indent=2),encoding='utf-8')
        return data|{'id':row['id'],'sha':row['sha'],'snapshot':snapshot,'assets':assets}
