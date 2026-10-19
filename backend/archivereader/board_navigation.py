"""Navigate a preserved board to explicit library evidence, never infer proof from colors."""
import json
try:
    from .board_import import BoardTools
except ImportError:
    from board_import import BoardTools


class BoardNavigation(BoardTools):
    def board_evidence(self,a):
        board=self.board_get({'id':a['id']});nodes={n['id']:n for n in board['snapshot']['nodes']}
        if a['node'] not in nodes:raise ValueError('Вузол дошки не знайдено.')
        node=nodes[a['node']];ids={a['node']};edge=node.get('type')=='CONNECTOR'
        if edge:ids.update(node.get(k,{}).get('endpointNodeId') for k in ['start','end'])
        people={board['persons'][i] for i in ids if i in board['persons']}
        state=board.get('semantics',{}).get('connectors',{}).get(a['node'],{}).get('status')
        relation_records={r['record'] for r in self.family_list({}) if edge and len(people)==2 and {r['left'],r['right']}==people and r['status']=='confirmed' and not r['stale'] and state!='incorrect'}
        evidence={}
        for person in people:
            for member in self.person_card({'id':person})['members']:
                current=member.get('current')
                if not current:continue
                mention=current
                item=evidence.setdefault(mention['record'],{'page':mention['page'],'record':mention['record'],'person':person,'stale':member['stale']})
                item['stale']|=member['stale']
        for record in relation_records:
            r=self.db.execute('SELECT page FROM records WHERE id=?',(record,)).fetchone()
            evidence.setdefault(record,{'page':r['page'],'record':record,'person':'','stale':False})
        # Exact imported-image identity is an independent way to reach the source page.
        for asset in board['assets']:
            if asset['node'] not in ids:continue
            for page in self.db.execute('SELECT p.id FROM pages p JOIN documents d ON p.doc=d.id WHERE d.sha=?',(asset['sha'],)):
                records=list(self.db.execute('SELECT id FROM records WHERE page=?',(page['id'],)))
                for row in records:evidence.setdefault(row['id'],{'page':page['id'],'record':row['id'],'person':'','stale':False})
        result=[]
        for ident,item in evidence.items():
            r=self.db.execute('SELECT data FROM records WHERE id=?',(ident,)).fetchone();data=json.loads(r['data']);card=self.source_card({'id':item['page']})
            regions=[v for v in self.annotations({'id':item['page']}) if v.get('record')==ident]
            preview=self.engine.render({'id':item['page']})['path']
            result.append(item|{'text':data.get('text',''),'title':data.get('person',''),'citation':card['citation'],'url':card['page_values']['page_url'] or card['book']['url'],'rect':regions[0].get('rect') if regions else None,'preview':preview,'relationship_proof':ident in relation_records and not item['stale'],'scope':'relationship' if ident in relation_records else 'person_context','board_status':state or 'unspecified','verified':bool(data.get('verified'))})
        return result
