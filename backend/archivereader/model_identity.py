"""Content identities for local recognition and segmentation models.

Every regular file in a selected model folder is pinned, including tokenizer,
configuration and sharded weights. Hashes are streamed; timestamps are not identity.
"""
import hashlib
import json
from pathlib import Path


def fingerprint_path(value):
    root=Path(value).resolve()
    if not root.exists() or not (root.is_file() or root.is_dir()):raise ValueError('Файл або папку моделі не знайдено.')
    def members():return sorted(p for p in root.rglob('*') if p.is_file()) if root.is_dir() else [root]
    paths=members()
    if not paths:raise ValueError('Папка моделі порожня.')
    files={}
    for path in paths:
        before=path.stat()
        with path.open('rb') as stream:content=hashlib.file_digest(stream,'sha256').hexdigest()
        after=path.stat()
        if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):raise ValueError('Модель змінюється. Дочекайтеся завершення запису файлів.')
        files[path.relative_to(root).as_posix() if root.is_dir() else path.name]={'bytes':after.st_size,'sha256':content}
    if paths!=members():raise ValueError('Склад папки моделі змінився. Створіть нову чергу.')
    manifest={'path':str(root),'kind':'folder' if root.is_dir() else 'file','files':files}
    manifest['sha256']=hashlib.sha256(json.dumps(manifest,sort_keys=True,ensure_ascii=False).encode('utf8')).hexdigest()
    return manifest


def fingerprint_models(options):
    result={'version':1,'engine':options.get('engine','kraken'),
            'recognition':fingerprint_path(options['model']) if options.get('model') else None,
            'segmentation':fingerprint_path(options['segmentation']) if options.get('segmentation') else None}
    if options.get('engine')=='paddle' and options.get('model'):
        try:from .paddle_local import package
        except ImportError:from paddle_local import package
        config,root=package(options['model'])
        result['paddle_weights']={key:fingerprint_path(root/config[key]) for key in ['detector_path','recognizer_path','runtime']}
    return result


def validate_models(options,expected):
    if not expected:
        if options.get('model') or options.get('segmentation') or options.get('engine')=='trocr' or not options.get('useTextLayer',True):
            raise ValueError('Стара черга не має контрольних сум моделей. Створіть нову чергу.')
        return fingerprint_models(options)
    try:actual=fingerprint_models(options)
    except (OSError,ValueError) as exc:raise ValueError('Модель або її склад змінилися. Створіть нову чергу.') from exc
    if actual!=expected:raise ValueError('Модель або її склад змінилися. Створіть нову чергу.')
    return actual
