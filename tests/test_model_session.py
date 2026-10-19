import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from backend.archivereader.model_session import serve
from backend.archivereader.htr_compare import cached_model,clear_model_cache,model_cache_stats


class ModelSessionTests(unittest.TestCase):
    def setUp(self):
        output=Path(__file__).resolve().parents[1]/'test-output';output.mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=output);self.root=Path(self.tmp.name)
        clear_model_cache()
    def tearDown(self):clear_model_cache();self.tmp.cleanup()

    def test_jsonl_ids_errors_progress_isolation_and_bounded_requests(self):
        requests=[{'request_id':'first','command':'ok'},{'request_id':'second','command':'bad'},{'request_id':'third','command':'ok'}]
        def handler(request):
            print('third-party progress')
            if request['command']=='bad':raise ValueError('expected failure')
            return {'text':'Український текст'}
        output=io.StringIO()
        with patch.dict(os.environ),patch('sys.stderr',new=io.StringIO()) as stderr:
            serve(io.StringIO(''.join(json.dumps(r)+'\n' for r in requests)),output,handler,max_requests=2)
        replies=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([r['request_id'] for r in replies],['first','second'])
        self.assertTrue(replies[0]['ok']);self.assertEqual(replies[0]['result']['text'],'Український текст')
        self.assertFalse(replies[1]['ok']);self.assertEqual(replies[1]['error'],'expected failure')
        self.assertTrue(replies[1]['session']['restart_after_reply']);self.assertEqual(replies[0]['session']['pid'],replies[1]['session']['pid'])
        self.assertIn('third-party progress',stderr.getvalue());self.assertNotIn('third-party',output.getvalue())

    def test_cache_reuses_loaded_object_and_detects_same_size_same_timestamp_change(self):
        model=self.root/'test.mlmodel';model.write_bytes(b'first');calls=[]
        def load():calls.append(1);return object()
        with patch.dict(os.environ,{'ARCHIVEREADER_MODEL_SESSION':'1'}):
            first=cached_model('kraken',model,load);self.assertIs(first,cached_model('kraken',model,load));stamp=model.stat()
            model.write_bytes(b'other');os.utime(model,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            self.assertIsNot(first,cached_model('kraken',model,load))
        self.assertEqual(len(calls),2)

    def test_cache_is_bounded_and_only_one_trocr_kept(self):
        paths=[]
        for n in range(4):
            path=self.root/f'{n}.mlmodel';path.write_bytes(str(n).encode());paths.append(path)
        with patch.dict(os.environ,{'ARCHIVEREADER_MODEL_SESSION':'1'}):
            for path in paths:cached_model('kraken',path,object)
            self.assertEqual(model_cache_stats()['loaded'],2)
            cached_model('trocr',paths[0],object);cached_model('trocr',paths[1],object)
            self.assertEqual(sum(r['kind']=='trocr' for r in model_cache_stats()['entries']),1)
            self.assertLessEqual(model_cache_stats()['loaded'],2)

    def test_processor_or_added_shard_invalidates_folder_cache(self):
        folder=self.root/'model';folder.mkdir();(folder/'weights.bin').write_bytes(b'weights');(folder/'config.json').write_text('{}')
        with patch.dict(os.environ,{'ARCHIVEREADER_MODEL_SESSION':'1'}):
            first=cached_model('trocr',folder,object);(folder/'config.json').write_text('{"new":true}')
            second=cached_model('trocr',folder,object);self.assertIsNot(first,second)
            (folder/'additional.safetensors').write_bytes(b'shard');self.assertIsNot(second,cached_model('trocr',folder,object))

    def test_non_session_call_does_not_retain_models(self):
        model=self.root/'model';model.write_bytes(b'fake')
        with patch.dict(os.environ,{'ARCHIVEREADER_MODEL_SESSION':'0'}):
            first=cached_model('kraken',model,object);self.assertIsNot(first,cached_model('kraken',model,object))
        self.assertEqual(model_cache_stats()['loaded'],0)

    def test_real_worker_handles_multiple_requests_without_ml_or_text_corruption(self):
        script=Path(__file__).resolve().parents[1]/'backend/archivereader/model_session.py'
        requests=[{'request_id':'one','command':'settings','root':str(self.root/'library'),'values':{'uiLanguage':'uk'}},{'request_id':'two','command':'settings','root':str(self.root/'library')},{'request_id':'three','command':'session_status','root':str(self.root/'library')}]
        result=subprocess.run([sys.executable,'-X','utf8','-u',str(script)],input=''.join(json.dumps(r)+'\n' for r in requests),encoding='utf-8',capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr);rows=[json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(rows),3);self.assertTrue(all(r['ok'] for r in rows));self.assertEqual(rows[1]['result']['uiLanguage'],'uk');self.assertEqual(len({r['session']['pid'] for r in rows}),1);self.assertEqual(rows[2]['result']['cache']['loaded'],0)

if __name__=='__main__':unittest.main()
