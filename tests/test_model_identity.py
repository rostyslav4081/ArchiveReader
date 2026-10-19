import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from backend.archivereader.engine import Engine
from backend.archivereader.operations import Operations
from backend.archivereader.model_identity import fingerprint_path,fingerprint_models,validate_models


class ModelIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'test-output');self.root=Path(self.temp.name);self.engine=Engine(self.root/'library');self.tools=Operations(self.engine)
        source=self.root/'page.png';Image.new('RGB',(100,100),'white').save(source);self.doc=self.engine.import_file({'path':str(source)})['id']
        self.model=self.root/'model.mlmodel';self.model.write_bytes(b'original');self.seg=self.root/'segment.mlmodel';self.seg.write_bytes(b'segmentation')
    def tearDown(self):self.engine.db.close();self.temp.cleanup()
    def job(self,**options):return self.tools.batch_create({'documents':[self.doc],'options':options})['id']
    def test_same_size_and_mtime_content_change_blocks_before_claim(self):
        job=self.job(model=str(self.model));stamp=self.model.stat();self.model.write_bytes(b'changed!');os.utime(self.model,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        with patch.object(self.engine,'recognize') as recognize:
            with self.assertRaises(ValueError):self.tools.batch_step({'job':job})
            recognize.assert_not_called()
        self.assertEqual(self.tools.batch_status({'job':job})['counts']['queued'],1)
    def test_folder_pins_configs_tokenizer_shards_and_membership(self):
        folder=self.root/'trocr';folder.mkdir()
        for name in ['config.json','tokenizer.json','processor_config.json','model.safetensors.index.json','model-00001-of-00002.safetensors','model-00002-of-00002.safetensors']:(folder/name).write_text(name)
        options={'engine':'trocr','model':str(folder),'segmentation':str(self.seg)};expected=fingerprint_models(options)
        self.assertEqual(len(expected['recognition']['files']),6);self.assertEqual(validate_models(options,expected),expected)
        check=self.tools.runtime_check({'model':str(folder)});self.assertTrue(check['model_exists']);self.assertEqual(check['model_bytes'],sum(p.stat().st_size for p in folder.iterdir()))
        original=folder/'tokenizer.json';renamed=folder/'renamed.json';original.rename(renamed)
        with self.assertRaises(ValueError):validate_models(options,expected)
        renamed.rename(original);extra=folder/'added-shard.bin';extra.write_bytes(b'new')
        with self.assertRaises(ValueError):validate_models(options,expected)
        extra.unlink();original.unlink()
        with self.assertRaises(ValueError):validate_models(options,expected)
    def test_segmentation_content_change_and_legacy_queue_rejection(self):
        job=self.job(model=str(self.model),segmentation=str(self.seg));self.seg.write_bytes(b'new segmentation')
        with self.assertRaises(ValueError):self.tools.batch_step({'job':job})
        legacy=self.job(model=str(self.model));config=json.loads(self.engine.db.execute('SELECT data FROM book_jobs WHERE id=?',(legacy,)).fetchone()['data']);config.pop('model_identity');config['model_stamp']={'size':self.model.stat().st_size,'mtime':self.model.stat().st_mtime_ns}
        with self.engine.db:self.engine.db.execute('UPDATE book_jobs SET data=? WHERE id=?',(json.dumps(config),legacy))
        with self.assertRaisesRegex(ValueError,'Стара черга'):self.tools.batch_step({'job':legacy})
        with self.assertRaises(ValueError):self.tools.batch_recover({'job':legacy})
        textjob=self.job(useTextLayer=True)
        with self.engine.db:self.engine.db.execute('UPDATE book_jobs SET data=? WHERE id=?',(json.dumps({'options':{'useTextLayer':True}}),textjob))
        with patch.object(self.engine,'recognize') as recognize:self.assertEqual(self.tools.batch_step({'job':textjob})['counts']['done'],1);recognize.assert_called_once()
    def test_stream_manifest_changes_when_file_renamed(self):
        original=fingerprint_path(self.model);renamed=self.model.with_name('other.mlmodel');self.model.rename(renamed);self.assertNotEqual(fingerprint_path(renamed),original)
