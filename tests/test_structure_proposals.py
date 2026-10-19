from tests.support import workspace_tempdir
import tempfile,unittest
from pathlib import Path
from PIL import Image,ImageDraw
from backend.archivereader.structure_proposals import suggest_structure


class StructureProposalsTests(unittest.TestCase):
 def setUp(self):self.temp=workspace_tempdir();self.root=Path(self.temp.name)
 def tearDown(self):self.temp.cleanup()
 def test_ruled_grid_remains_an_unverified_proposal(self):
  image=Image.new('RGB',(600,800),'white');draw=ImageDraw.Draw(image)
  for x in [70,190,330,520]:draw.line((x,90,x,700),fill='black',width=2)
  for y in range(90,701,90):draw.line((70,y,520,y),fill='black',width=2)
  path=self.root/'grid.png';image.save(path);before=path.read_bytes();result=suggest_structure(path)
  self.assertTrue(result['candidates']);row=result['candidates'][0];self.assertFalse(row['verified']);self.assertIsNone(row['confidence']);self.assertGreaterEqual(row['evidence']['intersections'],6);self.assertEqual(before,path.read_bytes())
 def test_frame_spine_and_plain_text_are_not_a_table(self):
  image=Image.new('RGB',(600,800),'white');draw=ImageDraw.Draw(image);draw.rectangle((10,10,590,790),outline='black',width=2);draw.line((300,10,300,790),fill='black',width=2)
  for y in range(110,650,45):draw.text((60,y),'A handwritten page needs actual reading',fill='black')
  path=self.root/'page.png';image.save(path);self.assertEqual([],suggest_structure(path)['candidates'])


 def test_cache_reuses_only_identical_input_and_recovers_corruption(self):
  from unittest.mock import patch
  from backend.archivereader.structure_proposals import cached_structure
  path=self.root/'cached.png';Image.new('RGB',(70,80),'white').save(path);cache=self.root/'cache';before=path.read_bytes()
  first=cached_structure(path,cache);self.assertFalse(first['cache']['hit'])
  with patch('backend.archivereader.structure_proposals.suggest_structure',side_effect=AssertionError('must reuse')):
   second=cached_structure(path,cache);self.assertTrue(second['cache']['hit']);self.assertEqual(first['candidates'],second['candidates'])
  self.assertEqual(before,path.read_bytes());next(cache.glob('structure-*.json')).write_text('{broken','utf-8');self.assertFalse(cached_structure(path,cache)['cache']['hit'])
  Image.new('RGB',(70,80),'black').save(path);changed=cached_structure(path,cache);self.assertFalse(changed['cache']['hit']);self.assertNotEqual(first['cache']['identity'],changed['cache']['identity']);self.assertFalse(cached_structure(path,cache,force=True)['cache']['hit'])


if __name__=='__main__':unittest.main()
