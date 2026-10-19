"""Portable, checksummed research snapshots. Restore only into a new directory."""
from contextlib import closing
from datetime import datetime,timezone
import json
import os
from pathlib import Path,PurePosixPath
import shutil
import sqlite3
import stat
import tempfile
import uuid
import zipfile
from types import SimpleNamespace
try:
    from .backups import digest
    from .model_identity import fingerprint_path
except ImportError:
    from backups import digest
    from model_identity import fingerprint_path

WEIGHTS={'.mlmodel','.safetensors','.ckpt','.pt','.pth','.bin'}


def safe_name(value):
    if not isinstance(value,str) or not value or '\\' in value or ':' in value:raise ValueError('Небезпечний шлях у пакеті.')
    parts=PurePosixPath(value).parts
    if value.startswith('/') or any(p in ['..','.'] or p.endswith((' ','.')) for p in parts) or PurePosixPath(value).as_posix()!=value:raise ValueError('Небезпечний шлях у пакеті.')
    if any(p.split('.')[0].upper() in ['CON','PRN','AUX','NUL']+[f'{base}{n}' for base in ['COM','LPT'] for n in range(1,10)] for p in parts):raise ValueError('Небезпечний шлях у пакеті.')
    return value


def replace_paths(value,mapping):
    if isinstance(value,str):
        for old,new in sorted(mapping.items(),key=lambda p:-len(p[0])):
            variants=[(old,new),(old.replace('\\','/'),new.replace('\\','/'))]
            for before,after in variants:
                if value==before or value.startswith(before+'\\') or value.startswith(before+'/'):return after+value[len(before):]
        return value
    if isinstance(value,list):return [replace_paths(v,mapping) for v in value]
    if isinstance(value,dict):
        literal={'text','notes','note','value','name','label','reference','hypothesis','quote','citation','reason','evidence_text','partial_text'}
        return {k:v if k in literal else replace_paths(v,mapping) for k,v in value.items()}
    return value


class ResearchBundleTools:
    def __init__(self,engine):self.engine=engine

    def inventory(self,a):
        root=self.engine.root.resolve();include=bool(a.get('include_models'));files={};paths=set(a.get('model_paths',[]));missing=[]
        def discover(value,key=''):
            if isinstance(value,dict):
                for k,v in value.items():
                    if isinstance(v,str) and (k in ['model','model_path','base_model','segmentation','candidate','base'] or k=='path' and value.get('engine') in ['kraken','trocr']):
                        if v:paths.add(v)
                    discover(v,k)
            elif isinstance(value,list):
                for v in value:discover(v,key)
        for row in self.engine.db.execute('SELECT key,value FROM settings'):
            try:value=json.loads(row['value'])
            except ValueError:continue
            if row['key'] in ['model','segmentation'] and isinstance(value,str) and value:paths.add(value)
            discover(value)
        for table in [r[0] for r in self.engine.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]:
            columns=[r[1] for r in self.engine.db.execute('PRAGMA table_info("'+table.replace('"','""')+'")') if r[2].upper() in ['TEXT','JSON']]
            for column in columns:
                for row in self.engine.db.execute('SELECT "'+column.replace('"','""')+'" FROM "'+table.replace('"','""')+'"'):
                    if not isinstance(row[0],str) or not row[0].lstrip().startswith(('{','[')):continue
                    try:discover(json.loads(row[0]))
                    except ValueError:pass
        for area in ['results','cache','models']:
            folder=root/area
            if not folder.exists():continue
            for path in folder.rglob('*'):
                if not path.is_file():continue
                if any(Path(excluded)==path or Path(excluded) in path.parents for excluded in a.get('_exclude',[])):continue
                if path.is_symlink():raise ValueError('Пакет не підтримує символічні посилання.')
                if path.suffix.lower() in WEIGHTS:
                    paths.add(str(path))
                    if not include:continue
                files[path.relative_to(root).as_posix()]=path
                if path.suffix.lower()=='.json' and path.stat().st_size<20_000_000:
                    try:discover(json.loads(path.read_text(encoding='utf-8-sig')))
                    except (ValueError,UnicodeError):pass
        documents=[]
        for row in self.engine.db.execute('SELECT id,path,sha FROM documents'):
            source=Path(row['path'])
            if not source.is_file() or digest(source)!=row['sha']:raise ValueError('Оригінал відсутній або пошкоджений.')
            name='originals/'+row['sha']+source.suffix.lower();files[name]=source;documents.append({'id':row['id'],'name':name,'original_path':str(source),'sha256':row['sha']})
        models=[]
        for value in sorted(paths):
            path=Path(value).resolve()
            if not path.exists():missing.append(str(path));continue
            try:identity=fingerprint_path(path)
            except (OSError,ValueError) as exc:missing.append(str(path)+' · '+str(exc));continue
            included=None
            if include:
                try:included=path.relative_to(root).as_posix()
                except ValueError:
                    parent=next((m for m in models if m['included_path'] and Path(m['original_path']).is_dir() and Path(m['original_path']) in path.parents),None)
                    included=parent['included_path']+'/'+path.relative_to(Path(parent['original_path'])).as_posix() if parent else 'external-models/'+identity['sha256'][:20]+('/'+path.name if path.is_file() else '')
                entries=[path] if path.is_file() else [p for p in path.rglob('*') if p.is_file()]
                for item in entries:files[included if path.is_file() else included+'/'+item.relative_to(path).as_posix()]=item
            models.append({'original_path':str(path),'configured_path':value,'included_path':included,'identity':identity})
        return {'files':files,'documents':documents,'models':models,'missing_models':missing,'source_root':str(root),'include_models':include}

    def bundle_preview(self,a):
        inventory=self.inventory(a)
        return {'files':len(inventory['files'])+1,'documents':len(inventory['documents']),'bytes':sum(p.stat().st_size for p in inventory['files'].values())+(self.engine.root/'archive.sqlite').stat().st_size,'models':inventory['models'],'missing_models':inventory['missing_models'],'include_models':inventory['include_models'],'scope':'SQLite snapshot, originals, results, frozen test sets, training artifacts and caches. Optional model weights; no application/runtime or backup vault.'}

    def bundle_create(self,a):
        destination=Path(a['path']).resolve()
        if destination.exists():raise ValueError('Виберіть новий файл або папку пакета.')
        destination.parent.mkdir(parents=True,exist_ok=True)
        stage=destination.parent/('.bundle-'+uuid.uuid4().hex);stage.mkdir();temporary=destination.parent/('.bundle-'+uuid.uuid4().hex+'.zip')
        try:
            database=stage/'archive.sqlite'
            with closing(sqlite3.connect(database)) as target:self.engine.db.backup(target)
            with closing(sqlite3.connect(database)) as snapshot:
                snapshot.row_factory=sqlite3.Row
                inventory=ResearchBundleTools(SimpleNamespace(root=self.engine.root,db=snapshot)).inventory(a|{'_exclude':[str(stage)]})
            entries=[]
            for name,source in inventory.pop('files').items():
                safe_name(name);target=stage/name;target.parent.mkdir(parents=True,exist_ok=True);before=digest(source);shutil.copyfile(source,target)
                if digest(target)!=before or digest(source)!=before:raise ValueError('Файл змінився під час створення пакета.')
                entries.append({'name':name,'bytes':target.stat().st_size,'sha256':before})
            entries.append({'name':'archive.sqlite','bytes':database.stat().st_size,'sha256':digest(database)})
            manifest=inventory|{'version':1,'created':datetime.now(timezone.utc).isoformat(),'files':entries,'scope':'Research data only; Python/.NET/application not included. Missing or excluded weights require separate setup.'}
            (stage/'bundle.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
            if destination.suffix.lower()=='.zip':
                with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
                    for path in stage.rglob('*'):
                        if path.is_file():archive.write(path,path.relative_to(stage).as_posix())
                if destination.exists():raise ValueError('Пакет уже існує.')
                os.rename(temporary,destination)
            else:os.rename(stage,destination)
            return {'path':str(destination),'documents':len(manifest['documents']),'files':len(entries),'bytes':sum(f['bytes'] for f in entries),'models':manifest['models'],'missing_models':manifest['missing_models'],'excluded_models':[m['original_path'] for m in manifest['models'] if not m['included_path']]}
        finally:
            if stage.exists():shutil.rmtree(stage)
            temporary.unlink(missing_ok=True)

    def unpack(self,path,stage):
        if path.is_dir():
            for source in path.rglob('*'):
                if source.is_symlink():raise ValueError('Небезпечне посилання у пакеті.')
                if source.is_file():
                    name=safe_name(source.relative_to(path).as_posix());target=stage/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        else:
            with zipfile.ZipFile(path) as archive:
                seen=set()
                for item in archive.infolist():
                    if item.is_dir():safe_name(item.filename.rstrip('/'));continue
                    name=safe_name(item.filename)
                    if name.casefold() in seen or stat.S_ISLNK(item.external_attr>>16):raise ValueError('Небезпечні або повторні шляхи у пакеті.')
                    seen.add(name.casefold());target=stage/name;target.parent.mkdir(parents=True,exist_ok=True)
                    with archive.open(item) as source,target.open('wb') as output:shutil.copyfileobj(source,output,1024*1024)
        manifest=json.loads((stage/'bundle.json').read_text(encoding='utf8'))
        if manifest.get('version')!=1:raise ValueError('Невідома версія пакета.')
        expected=set()
        for item in manifest['files']:
            name=safe_name(item['name'])
            if name.casefold() in expected:raise ValueError('Повторний шлях у пакеті.')
            expected.add(name.casefold());file=stage/name
            if not file.is_file() or file.stat().st_size!=item['bytes'] or digest(file)!=item['sha256']:raise ValueError('Контрольна сума пакета не збігається.')
        actual={p.relative_to(stage).as_posix().casefold() for p in stage.rglob('*') if p.is_file() and p!=stage/'bundle.json'}
        if expected!=actual or 'archive.sqlite' not in expected:raise ValueError('Склад пакета неповний або змінений.')
        with closing(sqlite3.connect((stage/'archive.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('База пакета пошкоджена.')
            docs={r[0]:r[1] for r in db.execute('SELECT id,sha FROM documents')}
        if len(manifest['documents'])!=len(docs) or len({d['id'] for d in manifest['documents']})!=len(docs):raise ValueError('Список оригіналів неповний.')
        for doc in manifest['documents']:
            name=safe_name(doc['name'])
            if docs.get(doc['id'])!=doc['sha256'] or digest(stage/name)!=doc['sha256']:raise ValueError('Оригінал пакета пошкоджений.')
        return manifest

    def bundle_inspect(self,a):
        with tempfile.TemporaryDirectory(dir=self.engine.root/'cache') as temporary:
            manifest=self.unpack(Path(a['path']).resolve(),Path(temporary))
        return {'created':manifest['created'],'files':len(manifest['files']),'bytes':sum(f['bytes'] for f in manifest['files']),'documents':len(manifest['documents']),'models':manifest['models'],'missing_models':manifest['missing_models'],'scope':manifest['scope']}

    def bundle_restore(self,a):
        target=Path(a['destination']).resolve()
        if target.exists():raise ValueError('Відновлення можливе лише в нову папку.')
        target.parent.mkdir(parents=True,exist_ok=True);stage=target.parent/('.restore-bundle-'+uuid.uuid4().hex);stage.mkdir()
        try:
            manifest=self.unpack(Path(a['path']).resolve(),stage);mapping={manifest['source_root']:str(target)}
            for doc in manifest['documents']:mapping[doc['original_path']]=str(target/safe_name(doc['name']))
            for model in manifest['models']:
                if model['included_path']:
                    relocated=str(target/safe_name(model['included_path']));mapping[model['original_path']]=relocated
                    if model.get('configured_path'):mapping[model['configured_path']]=relocated
            rewritten=[]
            for path in stage.rglob('*.json'):
                area=path.relative_to(stage).parts[0]
                if path.name in ['bundle.json','manifest.json','freeze.json'] or area in ['models','external-models'] and path.name not in ['run.json','provenance.json']:continue
                try:
                    old=json.loads(path.read_text(encoding='utf-8-sig'));new=replace_paths(old,mapping)
                    if new!=old:path.write_text(json.dumps(new,ensure_ascii=False,indent=2),encoding='utf8');rewritten.append(path.relative_to(stage).as_posix())
                except (ValueError,UnicodeError):pass
            with closing(sqlite3.connect(stage/'archive.sqlite')) as db,db:
                tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'library_fts%'")]
                for table in tables:
                    escaped='"'+table.replace('"','""')+'"'
                    for column in [r[1] for r in db.execute('PRAGMA table_info('+escaped+')') if r[2].upper() in ['TEXT','JSON']]:
                        quoted='"'+column.replace('"','""')+'"'
                        for rowid,value in db.execute('SELECT rowid,'+quoted+' FROM '+escaped).fetchall():
                            if not isinstance(value,str):continue
                            try:old=json.loads(value);new=replace_paths(old,mapping);changed=json.dumps(new,ensure_ascii=False) if new!=old else value
                            except ValueError:changed=replace_paths(value,mapping)
                            if changed!=value:db.execute('UPDATE '+escaped+' SET '+quoted+'=? WHERE rowid=?',(changed,rowid))
                db.execute("DELETE FROM settings WHERE key='backupDirectory'")
                db.execute("UPDATE pages SET status='pending',error='' WHERE status='running'")
                if 'book_tasks' in tables:db.execute("UPDATE book_tasks SET state='queued',error='' WHERE state='running'")
                if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('База після перенесення пошкоджена.')
            (stage/'restore-report.json').write_text(json.dumps({'source_package':str(Path(a['path']).resolve()),'rewritten_json_files':rewritten,'mapping':mapping,'missing_models':manifest['missing_models'],'excluded_models':[m['original_path'] for m in manifest['models'] if not m['included_path']],'policy':'Model identities retained as provenance. Recreate old queued inference jobs after relocation; no automatic recognition or model promotion.'},ensure_ascii=False,indent=2),encoding='utf8')
            os.rename(stage,target)
            return {'destination':str(target),'documents':len(manifest['documents']),'files':len(manifest['files']),'bytes':sum(f['bytes'] for f in manifest['files']),'models':manifest['models'],'missing_models':manifest['missing_models'],'excluded_models':[m['original_path'] for m in manifest['models'] if not m['included_path']]}
        except BaseException:
            shutil.rmtree(stage,ignore_errors=True);raise
