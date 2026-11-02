"""Bounded GEDZIP reading; only referenced documents are staged for import."""
import hashlib
import io
from pathlib import Path, PurePosixPath
import stat
from urllib.parse import unquote
import zipfile

MAX_GED=20*1024**2
MAX_FILE=256*1024**2
MAX_TOTAL=2*1024**3

def safe_name(name):
    name=unquote(name).replace('\\','/')
    if not name or name.startswith('/') or ':' in name or '\x00' in name or any(p in ['..','.'] for p in name.split('/')):
        raise ValueError('Небезпечний шлях документа в GEDZIP.')
    return PurePosixPath(name).as_posix()

def package_index(archive):
    infos=archive.infolist()
    if len(infos)>25000 or sum(i.file_size for i in infos)>MAX_TOTAL:
        raise ValueError('GEDZIP перевищує ліміт розпакованих даних 2 ГБ.')
    result={};seen=set()
    for info in infos:
        name=safe_name(info.filename.rstrip('/'))
        if name.casefold() in seen:raise ValueError('Повторний шлях у GEDZIP.')
        seen.add(name.casefold())
        if info.flag_bits&1 or stat.S_ISLNK(info.external_attr>>16):raise ValueError('Зашифровані файли та посилання GEDZIP не підтримуються.')
        if info.is_dir():continue
        if info.file_size>MAX_FILE:raise ValueError('Документ GEDZIP перевищує ліміт 256 МБ.')
        result[name]=info
    if 'gedcom.ged' not in result:raise ValueError('GEDZIP має містити gedcom.ged у корені.')
    if result['gedcom.ged'].file_size>MAX_GED:raise ValueError('GEDCOM перевищує ліміт імпорту 20 МБ.')
    return result

def input_bytes(path):
    path=Path(path)
    if path.suffix.lower()!='.gdz':
        if path.stat().st_size>MAX_GED:raise ValueError('GEDCOM перевищує ліміт імпорту 20 МБ.')
        raw=path.read_bytes();return raw,hashlib.sha256(raw).hexdigest(),None
    if path.stat().st_size>MAX_TOTAL:raise ValueError('GEDZIP перевищує ліміт 2 ГБ.')
    try:
        with zipfile.ZipFile(path) as archive:
            index=package_index(archive);raw=archive.read(index['gedcom.ged'])
            files={name:info.file_size for name,info in index.items()}
        with path.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
        return raw,sha,files
    except (zipfile.BadZipFile,RuntimeError) as ex:raise ValueError('Пошкоджений пакет GEDZIP.') from ex

def stage_media(path,media,folder):
    """Validate every referenced file before any library database writes."""
    from PIL import Image
    staged=[]
    with zipfile.ZipFile(path) as archive:
        index=package_index(archive)
        for item in media:
            name=item['path'];raw=archive.read(index[name]);suffix=Path(name).suffix.lower()
            if suffix=='.pdf':
                import pymupdf
                with pymupdf.open(stream=raw,filetype='pdf') as pdf:
                    if pdf.needs_pass:raise ValueError('PDF у GEDZIP захищений паролем.')
                    count=len(pdf)
            elif suffix in ['.jpg','.jpeg','.png','.tif','.tiff','.webp','.bmp','.gif']:
                with Image.open(io.BytesIO(raw)) as image:
                    count=getattr(image,'n_frames',1);image.verify()
            else:raise ValueError('Непідтримуваний формат документа GEDZIP: '+suffix)
            if not count:raise ValueError('Порожній документ GEDZIP.')
            sha=hashlib.sha256(raw).hexdigest();target=Path(folder)/(sha+suffix)
            target.write_bytes(raw)
            staged.append(item|{'staged':str(target),'sha':sha,'suffix':suffix,'count':count})
    return staged
