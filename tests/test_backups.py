import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from PIL import Image
from backend.archivereader.engine import Engine
from backend.archivereader.backups import BackupTools


class BackupTests(unittest.TestCase):
    def setUp(self):
        output=Path(__file__).resolve().parents[1]/'test-output';output.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=output);self.root=Path(self.temp.name)
        source=self.root/'source.png';Image.new('RGB',(150,200),'white').save(source)
        self.engine=Engine(self.root/'library');self.engine.import_file({'path':str(source)})
        self.page=self.engine.list_pages({})[0]['id'];self.tools=BackupTools(self.engine)
        self.record=self.engine.save_record({'page':self.page,'kind':'Інші записи та примітки','person':'Jan','text':'Saved reading'})['id']

    def tearDown(self):self.engine.db.close();self.temp.cleanup()

    def test_wal_snapshot_restores_records_sources_links_and_originals_to_new_library(self):
        from backend.archivereader.sources import SourceTools
        SourceTools(self.engine).source_card({'id':self.page,'book':{'archive':'Archive A'},'page_values':{'folio':'12r'}})
        snapshot=self.tools.backup_create({});target=self.root/'restored'
        self.engine.save_record({'id':self.record,'page':self.page,'kind':'Інші записи та примітки','person':'Changed'})
        self.tools.backup_restore({'path':snapshot['path'],'destination':str(target)})
        restored=Engine(target)
        try:
            self.assertEqual(restored.details({'id':self.page})['records'][0]['person'],'Jan')
            self.assertEqual(SourceTools(restored).source_card({'id':self.page})['book']['archive'],'Archive A')
            original=Path(restored.page(self.page)['path']);self.assertTrue(original.is_file());self.assertEqual(original.parent,target/'originals')
            self.assertTrue(Path(restored.render({'id':self.page})['path']).is_file())
        finally:restored.db.close()
        self.assertEqual(self.engine.details({'id':self.page})['records'][0]['person'],'Changed')
        with self.assertRaises(ValueError):self.tools.backup_restore({'path':snapshot['path'],'destination':str(target)})

    def test_automatic_interval_disable_retention_and_shared_originals(self):
        self.tools.backup_create({'automatic':True});self.assertTrue(self.tools.backup_create({'automatic':True})['skipped'])
        self.engine.settings({'values':{'autoBackup':False}});self.assertTrue(self.tools.backup_create({'automatic':True})['skipped'])
        for _ in range(8):self.tools.backup_create({})
        self.assertEqual(len(self.tools.backup_list({})['snapshots']),7)
        self.assertEqual(len(list((self.tools.vault()/'objects').iterdir())),1)
        partial=self.tools.vault()/'snapshots'/'.partial-crashed';partial.mkdir();(partial/'manifest.json').write_text('{}')
        self.assertEqual(len(self.tools.backup_list({})['snapshots']),7)

    def test_corrupt_database_original_or_manifest_never_creates_restore_target(self):
        snapshot=self.tools.backup_create({});manifest=Path(snapshot['path']);data=json.loads(manifest.read_text())
        object_path=self.tools.vault()/'objects'/data['documents'][0]['sha'];original=object_path.read_bytes();object_path.write_bytes(b'broken')
        target=self.root/'restored'
        with self.assertRaises(ValueError):self.tools.backup_restore({'path':str(manifest),'destination':str(target)})
        self.assertFalse(target.exists());object_path.write_bytes(original)
        database=manifest.parent/'archive.sqlite';database.write_bytes(b'broken')
        with self.assertRaises(ValueError):self.tools.backup_restore({'path':str(manifest),'destination':str(target)})
        self.assertFalse(target.exists())

    def test_failed_backup_does_not_publish_snapshot_and_external_vault_restores(self):
        self.engine.settings({'values':{'backupDirectory':str(self.root/'other-disk')}})
        original=Path(self.engine.page(self.page)['path']);content=original.read_bytes();original.write_bytes(b'changed')
        with self.assertRaises(ValueError):self.tools.backup_create({})
        self.assertEqual(self.tools.backup_list({})['snapshots'],[]);original.write_bytes(content)
        snapshot=self.tools.backup_create({});target=self.root/'restored'
        self.tools.backup_restore({'path':snapshot['path'],'destination':str(target)})
        restored=Engine(target)
        try:self.assertNotIn('backupDirectory',restored.settings({}))
        finally:restored.db.close()

    def test_worker_can_restore_even_if_working_database_is_corrupted(self):
        snapshot=self.tools.backup_create({});self.engine.db.close()
        (self.engine.root/'archive.sqlite').write_bytes(b'not a database')
        worker=Path(__file__).resolve().parents[1]/'backend/archivereader/engine.py'
        target=self.root/'recovery'
        for command,values in [('backup_list',{}),('backup_restore',{'path':snapshot['path'],'destination':str(target)})]:
            result=subprocess.run([sys.executable,'-X','utf8',str(worker)],input=json.dumps({'command':command,'root':str(self.engine.root)}|values),text=True,encoding='utf8',capture_output=True,check=True)
            self.assertTrue(json.loads(result.stdout)['ok'],result.stdout)
        restored=Engine(target)
        try:self.assertEqual(restored.details({'id':self.page})['records'][0]['person'],'Jan')
        finally:restored.db.close()
