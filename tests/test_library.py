import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from backend.archivereader.engine import Engine,KINDS
from backend.archivereader.library import LibraryTools


class LibraryTests(unittest.TestCase):
    def setUp(self):
        output=Path(__file__).resolve().parents[1]/'test-output'; output.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=output); self.root=Path(self.temp.name)
        source=self.root/'book.tif'
        Image.new('RGB',(100,200),'white').save(source,save_all=True,append_images=[Image.new('RGB',(100,200),'red')])
        self.engine=Engine(self.root/'library'); self.engine.import_file({'path':str(source)})
        self.pages=self.engine.list_pages({}); self.tools=LibraryTools(self.engine)

    def tearDown(self): self.engine.db.close(); self.temp.cleanup()

    def region(self,kind='line',text='Joannes',verified=True):
        return self.tools.save_annotation({'page':self.pages[0]['id'],'data':{'kind':kind,'text':text,'verified':verified,'rect':[.1,.3,.8,.1]}})['id']

    def test_search_indexes_all_sources_and_updates_only_dirty_pages(self):
        page=self.pages[0]['id']
        with self.engine.db: self.engine.db.execute("UPDATE pages SET text=?,lines=? WHERE id=?",('Joannes natus',json.dumps([{'text':'Paulus','box':[10,30,80,10]}]),page))
        record=self.engine.save_record({'page':page,'kind':KINDS[0],'person':'Joannes Šimek'})['id']
        self.engine.save_line({'id':page,'line':0,'text':'Joannes filius','verified':True}); self.region()
        result=self.tools.library_search({'query':'joann'})['rows']
        self.assertEqual({r['source'] for r in result},{'record','ocr','correction','region'})
        self.assertTrue(all('⟦' in r['snippet'] for r in result))
        self.assertEqual(self.tools.library_search({'query':'simek'})['rows'][0]['entity'],record)
        self.engine.save_record({'page':page,'id':record,'kind':KINDS[0],'person':'Anna'})
        self.assertFalse(self.tools.library_search({'query':'simek'})['rows'])
        self.assertEqual(self.engine.db.execute('SELECT COUNT(*) FROM search_dirty').fetchone()[0],0)
        self.assertFalse(self.tools.library_search({'query':'" OR * - :'})['rows'])
        self.assertEqual(self.tools.library_search({'query':'absent'})['coverage']['pending'],2)

    def test_review_latest_results_context_and_resolution_reappears_on_change(self):
        ident=self.region(); page=self.pages[0]
        folder=self.root/'report'; folder.mkdir()
        row={'id':ident,'rect':[.1,.3,.8,.1],'disagreement':True,'results':{'A':{'text':'Joannes'},'B':{'text':'Ioannes'}}}
        (folder/'report.json').write_text(json.dumps({'rows':[row]}),encoding='utf8')
        with self.engine.db: self.engine.db.execute('INSERT INTO comparison_runs(id,doc,path,manifest_sha) VALUES (?,?,?,?)',('run',page['doc'],str(folder),'sha'))
        item=self.tools.review_queue({})[0]
        context=self.tools.review_context({'id':page['id'],'region':ident})
        self.assertTrue(Path(context['path']).exists()); self.assertAlmostEqual(context['focus'][1],.4)
        self.tools.review_resolve(item); self.assertFalse(self.tools.review_queue({}))
        self.tools.save_annotation({'page':page['id'],'annotation':ident,'data':{'kind':'line','rect':row['rect'],'text':'Corrected','verified':True}})
        self.assertEqual(len(self.tools.review_queue({})),1)
        with self.assertRaises(ValueError): self.tools.review_resolve(item)
        # A newer agreeing run supersedes the previous disagreement.
        row['disagreement']=False; (folder/'report.json').write_text(json.dumps({'rows':[row]}),encoding='utf8')
        self.assertFalse(self.tools.review_queue({}))

    def test_history_restores_records_lines_and_deleted_regions_with_conflict_detection(self):
        page=self.pages[0]['id']; record=self.engine.save_record({'page':page,'kind':KINDS[0],'person':'Anna'})['id']
        self.engine.save_record({'page':page,'id':record,'kind':KINDS[0],'person':'Maria'})
        old=next(r for r in self.tools.history_list({'id':page}) if r['kind']=='record' and r['snapshot']['person']=='Anna')
        self.tools.history_restore(old|{'id':page})
        self.assertEqual(self.engine.details({'id':page})['records'][0]['person'],'Anna')
        with self.assertRaises(ValueError): self.tools.history_restore(old|{'id':page})
        ident=self.region(); self.tools.delete_annotation({'page':page,'annotation':ident})
        region=next(r for r in self.tools.history_list({'id':page}) if r['kind']=='region')
        self.tools.history_restore(region|{'id':page}); self.assertEqual(len(self.tools.annotations({'id':page})),1)
        with self.engine.db: self.engine.db.execute('UPDATE pages SET lines=? WHERE id=?',(json.dumps([{'text':'John','box':[10,30,80,10]}]),page))
        self.engine.save_line({'id':page,'line':0,'text':'Joannes','verified':True})
        line=next(r for r in self.tools.history_list({'id':page}) if r['kind']=='line' and r['version']=='before')
        self.tools.history_restore(line|{'id':page})
        self.assertEqual(self.engine.details({'id':page})['lines'][0]['corrected'],'John')
        self.assertFalse(self.engine.details({'id':page})['lines'][0]['verified'])

    def test_templates_skip_existing_columns_and_never_copy_transcriptions(self):
        self.region('column',text='Do not propagate'); template=self.tools.template_save({'id':self.pages[0]['id'],'name':'Test'})['id']
        result=self.tools.template_apply({'id':self.pages[0]['id'],'template':template,'pages':[p['id'] for p in self.pages]})
        self.assertEqual(result,{'added':1,'skipped':1})
        copied=self.tools.annotations({'id':self.pages[1]['id']})[0]
        self.assertEqual(copied['text'],''); self.assertFalse(copied['verified'])
        self.assertEqual(self.tools.template_apply({'id':self.pages[0]['id'],'template':template,'pages':[self.pages[1]['id']]})['skipped'],1)

    def test_benchmark_snapshot_is_frozen_and_excludes_missing_text(self):
        self.region(); self.tools.book_profile({'id':self.pages[0]['id'],'values':{'split':'test','languages':'la'}})
        result=self.tools.benchmark_freeze({}); folder=Path(result['path']); original=(folder/'manifest.json').read_bytes()
        self.region(text='Changed')
        self.assertEqual((folder/'manifest.json').read_bytes(),original)
        self.assertEqual(result['test'],1); self.assertTrue((folder/'freeze.json').exists())
        expected={'rows':[],'models':[]}
        with patch('backend.archivereader.library.compare',return_value=expected) as comparison:
            self.tools.benchmark_compare({'path':str(folder),'models':[]})
        passed=json.loads(comparison.call_args.args[0].read_text(encoding='utf8'))
        self.assertEqual([r['reference'] for r in passed],['Joannes'])
        (folder/'manifest.json').write_text('[]',encoding='utf8')
        with self.assertRaises(ValueError): self.tools.benchmark_compare({'path':str(folder),'models':[]})
        self.region('missing')
        with self.assertRaises(ValueError): self.tools.benchmark_freeze({})

if __name__=='__main__': unittest.main()
