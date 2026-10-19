"""Consistent SQLite snapshots and verified immutable originals in a shared backup vault."""
from datetime import datetime, timezone
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import uuid


def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''): value.update(block)
    return value.hexdigest()


class BackupTools:
    def __init__(self,engine): self.engine=engine

    def vault(self):
        setting=self.engine.settings({}).get('backupDirectory','')
        return Path(setting).resolve() if setting else self.engine.root/'backups'

    def backup_list(self,a):
        vault=self.vault(); result=[]
        for path in sorted((vault/'snapshots').glob('*/manifest.json'),reverse=True):
            if path.parent.name.startswith('.'): continue
            try:
                data=json.loads(path.read_text(encoding='utf8'))
                result.append({'path':str(path),'created':data['created'],'documents':len(data['documents']),'bytes':data['bytes']})
            except (OSError,ValueError,KeyError,TypeError): continue
        result.sort(key=lambda item:item['created'],reverse=True)
        return {'vault':str(vault),'snapshots':result,'enabled':self.engine.settings({}).get('autoBackup',True)}

    def backup_create(self,a):
        listing=self.backup_list({})
        if a.get('automatic'):
            if not listing['enabled']: return {'skipped':True}
            if listing['snapshots']:
                latest=datetime.fromisoformat(listing['snapshots'][0]['created'])
                if (datetime.now(timezone.utc)-latest).total_seconds()<7200: return {'skipped':True}
            if not self.engine.db.execute('SELECT 1 FROM documents').fetchone(): return {'skipped':True}
        vault=self.vault(); objects=vault/'objects'; snapshots=vault/'snapshots'
        objects.mkdir(parents=True,exist_ok=True); snapshots.mkdir(exist_ok=True)
        created=datetime.now(timezone.utc).isoformat(); ident=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
        temporary=snapshots/('.partial-'+ident); final=snapshots/ident; temporary.mkdir()
        try:
            db_path=temporary/'archive.sqlite'
            with closing(sqlite3.connect(db_path)) as target: self.engine.db.backup(target)
            with closing(sqlite3.connect(db_path)) as snapshot:
                if snapshot.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('Резервна база пошкоджена.')
                documents=snapshot.execute('SELECT id,path,sha FROM documents').fetchall()
            files=[]; total=db_path.stat().st_size
            for record,path,expected in documents:
                if len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected): raise ValueError('Оригінал не відповідає контрольній сумі.')
                source=Path(path); dest=objects/expected
                if not dest.is_file() or digest(dest)!=expected:
                    copying=objects/(expected+'.'+uuid.uuid4().hex+'.partial')
                    try:
                        shutil.copyfile(source,copying)
                        if digest(copying)!=expected: raise ValueError('Оригінал не відповідає контрольній сумі.')
                        os.replace(copying,dest)
                    finally: copying.unlink(missing_ok=True)
                size=dest.stat().st_size; total+=size
                files.append({'id':record,'sha':expected,'suffix':source.suffix,'size':size})
            manifest={'version':1,'created':created,'database_sha':digest(db_path),'documents':files,'bytes':total,
                      'scope':'SQLite database and imported originals; excludes caches, OCR report files, training checkpoints and external models.'}
            (temporary/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
            os.replace(temporary,final)
            # Keep seven database snapshots. Shared originals are retained for recovery.
            for item in self.backup_list({})['snapshots'][7:]:
                old=Path(item['path'])
                if old.parent.parent==snapshots and not old.parent.name.startswith('.partial-'): shutil.rmtree(old.parent)
            return {'path':str(final/'manifest.json'),'documents':len(files),'bytes':total,'created':created}
        except BaseException:
            shutil.rmtree(temporary,ignore_errors=True)
            raise

    def backup_restore(self,a):
        manifest_path=Path(a['path']).resolve(); target=Path(a['destination']).resolve()
        if target.exists(): raise ValueError('Виберіть нову папку для відновлення.')
        data=json.loads(manifest_path.read_text(encoding='utf8'))
        if data.get('version')!=1: raise ValueError('Невідома версія резервної копії.')
        vault=manifest_path.parent.parent.parent; database=manifest_path.parent/'archive.sqlite'
        if manifest_path.name!='manifest.json' or manifest_path.parent.parent.name!='snapshots': raise ValueError('Виберіть manifest.json із папки snapshots.')
        if digest(database)!=data['database_sha']: raise ValueError('Резервна база пошкоджена.')
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as connection:
            if connection.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or connection.execute('PRAGMA foreign_key_check').fetchone(): raise ValueError('Резервна база пошкоджена.')
            records={row[0]:row[1] for row in connection.execute('SELECT id,sha FROM documents')}
        documents=data['documents']
        if len(documents)!=len(records) or len({item['id'] for item in documents})!=len(records): raise ValueError('Список оригіналів неповний.')
        for item in documents:
            sha=item['sha']; suffix=item['suffix']
            if len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha) or records.get(item['id'])!=sha: raise ValueError('Список оригіналів неповний.')
            if suffix and (not suffix.startswith('.') or any(c not in '.abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789' for c in suffix)): raise ValueError('Неправильна назва оригіналу.')
            original=vault/'objects'/sha
            if not original.is_file() or original.stat().st_size!=item['size'] or digest(original)!=sha: raise ValueError('Оригінал у резервній копії відсутній або пошкоджений.')
        target.parent.mkdir(parents=True,exist_ok=True); temporary=target.parent/(target.name+'.restoring-'+uuid.uuid4().hex); temporary.mkdir()
        try:
            (temporary/'originals').mkdir(); shutil.copyfile(database,temporary/'archive.sqlite')
            with closing(sqlite3.connect(temporary/'archive.sqlite')) as connection, connection:
                for item in documents:
                    filename=item['sha']+item['suffix']; shutil.copyfile(vault/'objects'/item['sha'],temporary/'originals'/filename)
                    if digest(temporary/'originals'/filename)!=item['sha']: raise ValueError('Оригінал у резервній копії відсутній або пошкоджений.')
                    connection.execute('UPDATE documents SET path=? WHERE id=?',(str(target/'originals'/filename),item['id']))
                connection.execute("DELETE FROM settings WHERE key='backupDirectory'")
                connection.execute("UPDATE pages SET status='pending',error='' WHERE status='running'")
            os.rename(temporary,target)
            return {'destination':str(target),'documents':len(documents)}
        except BaseException:
            shutil.rmtree(temporary,ignore_errors=True); raise


class RecoveryLibrary:
    """Read backup configuration without initializing a possibly damaged database."""
    def __init__(self,root): self.root=Path(root).resolve()
    def settings(self,a):
        database=self.root/'archive.sqlite'
        if not database.is_file(): return {}
        try:
            with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as connection:
                return {key:json.loads(value) for key,value in connection.execute('SELECT key,value FROM settings')}
        except (sqlite3.Error,ValueError): return {}
