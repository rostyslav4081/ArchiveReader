import json
from contextlib import closing
from pathlib import Path
import tempfile
import unittest
import sqlite3
from unittest.mock import patch
import zipfile
from PIL import Image,ImageDraw
from backend.archivereader.engine import Engine,handle_request
from backend.archivereader.research_bundle import ResearchBundleTools
from backend.archivereader.review_corpus import CorpusTools
from backend.archivereader.backups import digest


class ResearchBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'test-output');self.root=Path(self.temp.name);self.engine=Engine(self.root/'library');self.tools=ResearchBundleTools(self.engine)
        source=self.root/'source.png';image=Image.new('RGB',(200,150),'ivory');ImageDraw.Draw(image).text((20,30),'Alpha beta',fill='black');image.save(source);self.original=source.read_bytes();self.engine.import_file({'path':str(source)});self.page=self.engine.list_pages({})[0]['id']
        (self.engine.root/'results/report.html').write_text('<h1>Research result</h1>',encoding='utf8')
        self.models=self.root/'external-model';self.models.mkdir();(self.models/'model.safetensors').write_bytes(b'weights');(self.models/'config.json').write_text('{}');self.engine.settings({'values':{'model':str(self.models)}})
    def tearDown(self):self.engine.db.close();self.temp.cleanup()
    def create(self,**options):return self.tools.bundle_create({'path':str(self.root/'package.zip')}|options)
    def test_original_results_database_json_rebase_and_optional_weights(self):
        training=self.engine.root/'models/training-one';training.mkdir(parents=True);(training/'training.log').write_text('Training completed');checkpoint=training/'best.safetensors';checkpoint.write_bytes(b'new weights')
        (training/'run.json').write_text(json.dumps({'base_model':str(self.models),'dataset':str(training/'dataset')}))
        self.engine.db.execute('CREATE TABLE candidate_test(id TEXT PRIMARY KEY,data TEXT)')
        with self.engine.db:self.engine.db.execute('INSERT INTO candidate_test VALUES (?,?)',('one',json.dumps({'candidate':str(checkpoint),'report':str(self.engine.root/'results/report.html')})))
        package=self.create(include_models=True);target=self.root/'restored';self.tools.bundle_restore({'path':package['path'],'destination':str(target)});restored=Engine(target)
        try:
            page=restored.page(self.page);self.assertEqual(Path(page['path']).read_bytes(),self.original);self.assertEqual((target/'results/report.html').read_text(),'<h1>Research result</h1>');self.assertEqual((target/'models/training-one/training.log').read_text(),'Training completed')
            candidate=json.loads(restored.db.execute('SELECT data FROM candidate_test').fetchone()['data']);self.assertTrue(Path(candidate['candidate']).is_file());self.assertEqual(candidate['candidate'],str(target/'models/training-one/best.safetensors'))
            run=json.loads((target/'models/training-one/run.json').read_text());self.assertEqual(run['dataset'],str(target/'models/training-one/dataset'))
            model=Path(restored.settings({})['model']);self.assertTrue((model/'model.safetensors').is_file());self.assertTrue(str(model).startswith(str(target)))
        finally:restored.db.close()
        with self.assertRaises(ValueError):self.tools.bundle_restore({'path':package['path'],'destination':str(target)})
    def test_missing_and_excluded_models_are_explicit_and_manifested(self):
        missing=self.root/'missing.mlmodel';preview=self.tools.bundle_preview({'model_paths':[str(missing)]});self.assertIn(str(missing),preview['missing_models']);self.assertTrue(preview['models'][0]['identity']['sha256'])
        package=self.create();self.assertIn(str(self.models),package['excluded_models'])
        with zipfile.ZipFile(package['path']) as archive:self.assertFalse(any('model.safetensors' in p for p in archive.namelist()))
    def test_corrupt_and_path_escape_fail_without_destination(self):
        package=self.create();bad=self.root/'corrupt.zip'
        with zipfile.ZipFile(package['path']) as source,zipfile.ZipFile(bad,'w') as target:
            for item in source.infolist():target.writestr(item, b'corrupted' if item.filename.endswith('report.html') else source.read(item))
        destination=self.root/'failed'
        with self.assertRaises(ValueError):self.tools.bundle_restore({'path':str(bad),'destination':str(destination)})
        self.assertFalse(destination.exists());evil=self.root/'escape.zip'
        with zipfile.ZipFile(evil,'w') as archive:archive.writestr('../escaped.txt','bad')
        with self.assertRaises(ValueError):self.tools.bundle_restore({'path':str(evil),'destination':str(destination)})
        self.assertFalse((self.root/'escaped.txt').exists());self.assertFalse(destination.exists())
    def test_frozen_corpus_bytes_and_bindings_survive_restoration(self):
        corpus=CorpusTools(self.engine);region=corpus.save_annotation({'page':self.page,'data':{'kind':'entry','rect':[.1,.1,.8,.6],'text':'Alpha beta','verified':False}})['id'];corpus.corpus_import({'id':self.page});row=corpus.corpus_list({})[0];corpus.corpus_save({'reference':row['id'],'revision':row['revision'],'text':'Alpha beta','human_verified':True,'single_block':True});frozen=corpus.corpus_freeze({});folder=Path(frozen['path']);original=(folder/'manifest.json').read_bytes();freeze=(folder/'freeze.json').read_bytes()
        with self.engine.db:self.engine.db.execute('INSERT INTO comparison_runs VALUES (?,?,?, ?,CURRENT_TIMESTAMP)',('test-run',self.engine.page(self.page)['doc'],str(folder/'comparison.html'),frozen['manifest_sha256']))
        package=self.create(include_models=True);target=self.root/'restored';self.tools.bundle_restore({'path':package['path'],'destination':str(target)});relative=folder.relative_to(self.engine.root);self.assertEqual((target/relative/'manifest.json').read_bytes(),original);self.assertEqual((target/relative/'freeze.json').read_bytes(),freeze)
        engine=Engine(target);tools=CorpusTools(engine)
        try:
            self.assertTrue(tools.corpus_list({})[0]['eligible']);self.assertEqual(engine.db.execute('SELECT path FROM comparison_runs WHERE id=?',('test-run',)).fetchone()['path'],str(target/relative/'comparison.html'))
            a=self.root/'a.mlmodel';a.write_bytes(b'A');b=self.root/'b.mlmodel';b.write_bytes(b'B');models=[{'name':'A','engine':'kraken','path':str(a)},{'name':'B','engine':'kraken','path':str(b)}]
            def fake(manifest,models,out):return {'models':[],'rows':[r|{'results':{'A':{'text':'Alpha beta'},'B':{'text':'Alpha beta'}}} for r in json.loads(Path(manifest).read_text())]}
            with patch('backend.archivereader.review_corpus.segment_entry',return_value=[[0,0,1,1]]),patch('backend.archivereader.review_corpus.compare',side_effect=fake):self.assertEqual(tools.corpus_compare({'path':str(target/relative),'models':models})['common_entries'],1)
        finally:engine.db.close()
    def test_inventory_uses_database_snapshot_even_if_live_import_changes(self):
        original=ResearchBundleTools.inventory;live=self.engine;new=self.root/'later.png';Image.new('RGB',(50,50),'red').save(new)
        def during_snapshot(tools,args):
            if tools.engine.db is not live.db and len(live.list_pages({}))==1:live.import_file({'path':str(new)})
            return original(tools,args)
        with patch.object(ResearchBundleTools,'inventory',during_snapshot):package=self.create()
        self.assertEqual(len(live.list_pages({})),2);self.assertEqual(self.tools.bundle_inspect({'path':package['path']})['documents'],1)
    def test_restore_and_inspect_work_when_current_database_is_corrupt(self):
        package=self.create();broken=self.root/'broken';broken.mkdir();database=broken/'archive.sqlite';database.write_bytes(b'not a SQLite database');target=self.root/'recovered'
        inspected=handle_request({'command':'bundle_inspect','root':str(broken),'path':package['path']})
        self.assertEqual(1,inspected['documents'])
        result=handle_request({'command':'bundle_restore','root':str(broken),'path':package['path'],'destination':str(target)})
        self.assertEqual(1,result['documents']);self.assertEqual(database.read_bytes(),b'not a SQLite database')
        restored=Engine(target)
        try:self.assertEqual(Path(restored.page(self.page)['path']).read_bytes(),self.original)
        finally:restored.db.close()

    def test_folder_bundle_and_foreign_key_integrity_guard(self):
        package=Path(self.tools.bundle_create({'path':str(self.root/'folder-package')})['path']);self.assertEqual(self.tools.bundle_inspect({'path':str(package)})['documents'],1)
        with closing(sqlite3.connect(package/'archive.sqlite')) as db,db:db.execute('UPDATE pages SET doc=?',('nonexistent-document',))
        manifest=json.loads((package/'bundle.json').read_text());entry=next(f for f in manifest['files'] if f['name']=='archive.sqlite');entry['sha256']=digest(package/'archive.sqlite');entry['bytes']=(package/'archive.sqlite').stat().st_size;(package/'bundle.json').write_text(json.dumps(manifest))
        target=self.root/'invalid-database'
        with self.assertRaises(ValueError):self.tools.bundle_restore({'path':str(package),'destination':str(target)})
        self.assertFalse(target.exists())
