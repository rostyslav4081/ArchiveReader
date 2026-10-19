import hashlib,json,tempfile,unittest
from pathlib import Path
from PIL import Image
from backend.archivereader.engine import Engine
from backend.archivereader.board_navigation import BoardNavigation

class BoardNavigationTests(unittest.TestCase):
    def test_relationship_proof_requires_explicit_current_link_and_respects_red(self):
        root=Path(__file__).resolve().parents[1]/'test-output'
        with tempfile.TemporaryDirectory(dir=root) as tmp:
            p=Path(tmp);image=p/'scan.png';Image.new('RGB',(300,400),'white').save(image);e=Engine(p/'library');t=BoardNavigation(e)
            try:
                e.import_file({'path':str(image)});page=e.list_pages({})[0]['id']
                raw={'fileKey':'test','pageId':'0:1','nodes':[{'id':i,'type':'TEXT','text':i} for i in ['a','b']]+[{'id':'edge','type':'CONNECTOR','start':{'endpointNodeId':'a'},'end':{'endpointNodeId':'b'}}]}
                path=p/'board.json';path.write_text(json.dumps(raw));preview=t.board_preview({'path':str(path)});board=t.board_import({'path':str(path),'sha':preview['sha'],'people':['a','b']})
                rec=e.save_record({'page':page,'kind':'Народження','person':'Child','related1':'Parent','text':'Synthetic child of parent'})['id'];mentions=t.mentions()
                for node,field in [('a','person'),('b','related1')]:
                    m=next(v for v in mentions if v['field']==field);t.person_attach({'person':board['persons'][node],'mention':m,'signature':m['signature'],'note':'Synthetic reviewed membership'})
                args={'id':board['id'],'node':'edge'};self.assertTrue(all(not r['relationship_proof'] for r in t.board_evidence(args)))
                signature=hashlib.sha256(e.db.execute('select data from records where id=?',(rec,)).fetchone()['data'].encode()).hexdigest();t.family_save({'left':board['persons']['b'],'right':board['persons']['a'],'kind':'parent','record':rec,'signature':signature,'note':'Synthetic explicit parent assertion'})
                self.assertTrue(t.board_evidence(args)[0]['relationship_proof'])
                semantics={'fileKey':'test','pageId':'0:1','legend':{'red':'incorrect','yellow':'unresolved','other':'logically_consistent'},'connectors':[{'id':'edge','strokes':[{'type':'SOLID','color':{'r':1,'g':0,'b':0}}]}]};sp=p/'semantics.json';sp.write_text(json.dumps(semantics));t.board_set_semantics({'id':board['id'],'path':str(sp),'expected_sha':board['sha']})
                self.assertFalse(t.board_evidence(args)[0]['relationship_proof'])
                e.save_record({'id':rec,'page':page,'kind':'Народження','person':'Other','related1':'Parent'})
                self.assertTrue(t.board_evidence(args)[0]['stale'])
                self.assertEqual(2,len(t.person_list({})))
            finally:e.db.close()

if __name__=='__main__':unittest.main()
