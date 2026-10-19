import json,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from tests import test_layout as fixtures
from backend.archivereader.layout import fingerprint

class LayoutWorkflowTests(unittest.TestCase):
 def setUp(self):
  self.f=fixtures.LayoutTests();self.f.setUp();self.l=self.f.layout;self.page=self.f.page['id'];self.model=self.f.root/'model.mlmodel';self.model.write_bytes(b'fixture')
 def tearDown(self):self.f.tearDown()
 def ann(self,kind,rect,**kw):return self.l.save_annotation({'page':self.page,'data':{'kind':kind,'rect':rect,**kw}})['id']
 def test_manual_lines_skip_segmentation_keep_order_and_invalidate_on_edit(self):
  entry=self.ann('entry',[0,0,1,1]);bottom=self.ann('line',[.1,.6,.8,.1],parent=entry,reading_order=1,text='B');top=self.ann('line',[.1,.1,.8,.1],parent=entry,reading_order=2,text='A');args={'id':self.page,'annotation':entry,'model':str(self.model),'mode':'columns'}
  def run(cmd,timeout):
   self.assertNotIn('segment',cmd);self.assertIn('--no-segmentation',cmd)
   # Different raw readings prove parent order does not get re-sorted geometrically.
   count=run.count;run.count+=1;Path(cmd[5]).write_text('<alto><TextLine HPOS="0" VPOS="0" WIDTH="160" HEIGHT="30"><String CONTENT="'+str(count)+'"/></TextLine></alto>')
  run.count=0;before=self.l.annotations({'id':self.page})
  with patch('backend.archivereader.layout.run_process',side_effect=run) as recognize:
   result=self.l.recognize_region(args);self.assertEqual(result['text'],'0\n1');self.assertEqual(recognize.call_count,2);self.assertEqual(result['saved_lines'][0]['id'],bottom)
   cached=self.l.recognize_region(args);self.assertTrue(cached['reused']);self.assertEqual(recognize.call_count,2)
   applied=self.l.region_recognition_apply({'id':self.page,'run':result['id']});self.assertEqual(applied['added'],0);self.assertEqual(len(applied['conflicts']),2);self.assertEqual(self.l.annotations({'id':self.page}),before)
   row=next(r for r in before if r['id']==top);self.l.save_annotation({'page':self.page,'annotation':top,'data':row|{'rect':[.1,.12,.8,.1]}})
   with self.assertRaises(ValueError):self.l.region_recognition_apply({'id':self.page,'run':result['id']})
   changed=self.l.recognize_region(args);self.assertNotEqual(changed['id'],result['id']);self.assertEqual(recognize.call_count,3)
 def test_variants_have_separate_hashes_coordinates_and_apply_original_binding(self):
  line=self.ann('line',[.1,.2,.5,.1]);sizes=[]
  def run(cmd,timeout):
   with Image.open(cmd[4]) as im:w,h=im.size;sizes.append(im.size)
   Path(cmd[5]).write_text(f'<alto><TextLine HPOS="0" VPOS="0" WIDTH="{w}" HEIGHT="{h}"><String CONTENT="Anna"/></TextLine></alto>')
  args={'id':self.page,'annotation':line,'model':str(self.model)}
  with patch('backend.archivereader.layout.run_process',side_effect=run):
   a=self.l.recognize_region(args);b=self.l.recognize_region(args|{'variant':'upscale2'});c=self.l.recognize_region(args|{'variant':'contrast'})
  self.assertEqual(sizes,[(100,30),(200,60),(100,30)]);self.assertEqual(a['lines'][0]['rect'],b['lines'][0]['rect']);self.assertNotEqual(a['cache_key'],b['cache_key']);self.assertNotEqual(a['cache_key'],c['cache_key']);self.l.region_recognition_apply({'id':self.page,'run':b['id']})
 def test_edit_atomic_protection_history_and_quality(self):
  entry=self.ann('entry',[0,0,1,1]);a=self.ann('line',[.1,.1,.8,.1],parent=entry,text='A');b=self.ann('line',[.1,.15,.8,.1],parent=entry,text='B');q=self.l.layout_quality({'id':self.page});self.assertTrue(any(r['kind']=='overlap' for r in q['issues']))
  with self.assertRaises(ValueError):self.l.layout_edit_lines({'id':self.page,'regions':[a,b],'expected':'old','operation':'merge'})
  merged=self.l.layout_edit_lines({'id':self.page,'regions':[a,b],'expected':q['snapshot'],'operation':'merge'});row=next(r for r in self.l.annotations({'id':self.page}) if r['id']==merged['ids'][0]);self.assertEqual(row['text'],'A\nB');self.assertFalse(row['verified']);self.assertTrue(self.f.engine.db.execute('select count(*) from annotation_history where annotation=? and after IS NULL',(a,)).fetchone()[0])
  split=self.l.layout_edit_lines({'id':self.page,'regions':merged['ids'],'expected':self.l.layout_quality({'id':self.page})['snapshot'],'operation':'split'});rows=[r for r in self.l.annotations({'id':self.page}) if r['id'] in split['ids']];self.assertTrue(all(r['text']=='' and 'A\nB' in r['note'] for r in rows))
  r=rows[0];self.l.save_annotation({'page':self.page,'annotation':r['id'],'data':r|{'text':'checked','verified':True}})
  with self.assertRaises(ValueError):self.l.layout_edit_lines({'id':self.page,'regions':[r['id']],'expected':self.l.layout_quality({'id':self.page})['snapshot'],'operation':'split'})
 def test_map_never_claims_full_page_and_compare_does_not_apply(self):
  self.ann('line',[.1,.1,.8,.1],text='Anna',verified=True);mapped=self.l.book_quality_map({'id':self.page});self.assertEqual(mapped['pages'][0]['state'],'saved_lines_verified');self.assertFalse(mapped['pages'][0]['coverage_complete'])
  model2=self.f.root/'seg.mlmodel';model2.write_bytes(b'other');before=self.l.annotations({'id':self.page})
  def run(cmd,timeout):Path(cmd[5]).write_text(json.dumps({'lines':[{'bbox':[20,30,180,60]}]}))
  with patch('backend.archivereader.layout.run_process',side_effect=run):r=self.l.layout_compare({'id':self.page,'mode':'text','models':[{'name':'A','path':''},{'name':'B','path':str(model2)}]})
  self.assertEqual(len(r['models']),2);self.assertEqual(before,self.l.annotations({'id':self.page}));self.assertFalse(r['automatic_selection']);self.assertIn('source_sha256',r['models'][0]['proposal'])

 def test_photo_book_order_missing_leaf_and_status_map_bounds(self):
  from backend.archivereader.books import BookTools
  other=self.f.root/'second.png';Image.new('RGB',(200,300),'black').save(other);self.f.engine.import_file({'path':str(other)});p2=self.f.engine.db.execute('select id from pages where id<>?',(self.page,)).fetchone()[0]
  BookTools(self.f.engine).book_save({'name':'Ordered test','items':[{'page':p2},{'label':'Missing leaf'},{'page':self.page}]})
  mapped=self.l.book_quality_map({'id':self.page});self.assertEqual([r['page'] for r in mapped['pages']],[p2,None,self.page]);self.assertEqual(mapped['pages'][1]['state'],'missing_page');self.assertEqual([r['number'] for r in mapped['pages']],[1,2,3])

if __name__=='__main__':unittest.main()
