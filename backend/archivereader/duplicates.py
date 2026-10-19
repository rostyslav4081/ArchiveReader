"""Incremental perceptual candidates; only explicit full-page decisions permit queue skipping."""
import json
from PIL import Image,ImageOps,ImageStat
try:
    from .research import ResearchTools
except ImportError:
    from research import ResearchTools


def fingerprint(image):
    gray=ImageOps.grayscale(image)
    if ImageStat.Stat(gray).stddev[0]<8:return []
    rectangles=[[0,0,1,1],[.15,.15,.7,.7]]+[[x,y,.5,.5] for x,y in [(0,0),(.5,0),(0,.5),(.5,.5)]]
    rectangles += [[x/3,y/3,1/3,1/3] for y in range(3) for x in range(3)]
    result=[]
    for rect in rectangles:
        x,y,w,h=rect;crop=gray.crop((round(x*gray.width),round(y*gray.height),round((x+w)*gray.width),round((y+h)*gray.height)))
        if ImageStat.Stat(crop).stddev[0]<8:continue
        pixels=list(ImageOps.autocontrast(crop).resize((9,8)).get_flattened_data());bits=0
        for y in range(8):
            for x in range(8):bits=(bits<<1)|int(pixels[y*9+x]>pixels[y*9+x+1])
        result.append({'hash':f'{bits:016x}','rect':rect})
    return result


class DuplicateTools(ResearchTools):
    def __init__(self,engine):
        super().__init__(engine)
        self.db.executescript('CREATE TABLE IF NOT EXISTS page_fingerprints(page TEXT PRIMARY KEY,sha TEXT,data TEXT);CREATE TABLE IF NOT EXISTS duplicate_decisions(pair TEXT PRIMARY KEY,data TEXT);')

    def index_page(self,page):
        rendering=self.engine.render({'id':page['id']})
        with Image.open(rendering['path']) as image:data=fingerprint(image)
        with self.db:self.db.execute('INSERT INTO page_fingerprints VALUES (?,?,?) ON CONFLICT(page) DO UPDATE SET sha=excluded.sha,data=excluded.data',(page['id'],page['sha'],json.dumps(data)))
        return data

    def duplicate_index(self,a):
        remaining=list(self.db.execute('SELECT p.id,d.sha FROM pages p JOIN documents d ON d.id=p.doc LEFT JOIN page_fingerprints f ON f.page=p.id WHERE f.page IS NULL OR f.sha<>d.sha ORDER BY p.rowid'))
        limit=max(1,min(100,int(a.get('limit',30))))
        for page in remaining[:limit]:self.index_page(dict(page))
        return {'indexed':min(limit,len(remaining)),'remaining':max(0,len(remaining)-limit)}

    def duplicate_find(self,a):
        page=self.engine.page(a['page']);sha=self.db.execute('SELECT sha FROM documents WHERE id=?',(page['doc'],)).fetchone()[0]
        row=self.db.execute('SELECT data FROM page_fingerprints WHERE page=? AND sha=?',(page['id'],sha)).fetchone()
        selected=json.loads(row['data']) if row else self.index_page({'id':page['id'],'sha':sha});results=[]
        if not selected:return results
        for row in self.db.execute('SELECT f.*,p.num,p.status,d.name FROM page_fingerprints f JOIN pages p ON p.id=f.page JOIN documents d ON d.id=p.doc WHERE f.page<>?',(page['id'],)):
            other=json.loads(row['data']);best=None;full=0
            for left in selected:
                for right in other:
                    score=1-(int(left['hash'],16)^int(right['hash'],16)).bit_count()/64
                    if left['rect']==[0,0,1,1] and right['rect']==[0,0,1,1]:full=score
                    if best is None or score>best['similarity']:best={'similarity':round(score,3),'left_rect':left['rect'],'right_rect':right['rect']}
            if best and best['similarity']>=.94:
                pair=json.dumps(sorted([page['id'],row['page']]))
                decision=self.db.execute('SELECT data FROM duplicate_decisions WHERE pair=?',(pair,)).fetchone()
                results.append(best|{'left':page['id'],'right':row['page'],'name':row['name'],'number':row['num']+1,'left_state':page['status'],'right_state':row['status'],'full_similarity':round(full,3),'decision':json.loads(decision['data']) if decision else None})
        return sorted(results,key=lambda r:(-r['full_similarity'],-r['similarity']))[:100]

    def duplicate_decide(self,a):
        left,right=a['left'],a['right'];self.engine.page(left);self.engine.page(right)
        if left==right or a.get('status') not in ['confirmed_full','related_fragment','rejected'] or not a.get('note','').strip():raise ValueError('Вкажіть рішення й пояснення для двох сторінок.')
        # Preserve the user-selected direction; the source page must actually be done to skip.
        values={k:a[k] for k in ['left','right','status','note']};pair=json.dumps(sorted([left,right]))
        with self.db:self.db.execute('INSERT INTO duplicate_decisions VALUES (?,?) ON CONFLICT(pair) DO UPDATE SET data=excluded.data',(pair,json.dumps(values,ensure_ascii=False)))
        return values
