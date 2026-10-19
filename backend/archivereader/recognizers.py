"""Local recognizer contracts and shared segmentation for whole-page TrOCR."""
import hashlib
import json
from pathlib import Path
import tempfile

try:from .htr_compare import cached_model
except ImportError:from htr_compare import cached_model


def segmentation_model(path=None):
    from importlib import resources
    from kraken.lib.vgsl import TorchVGSLModel
    path=path or str(resources.files('kraken').joinpath('blla.mlmodel'))
    return cached_model('segmentation',path,lambda:TorchVGSLModel.load_model(path))


def kraken_page(image_path,model_path,segmentation=None,alto_path=None):
    """CPU in-process counterpart of segment -bl + OCR, retaining ALTO geometry."""
    if Path(model_path).suffix=='.safetensors':
        if alto_path:return kraken_region(image_path,model_path,alto_path,segmentation)
        with tempfile.TemporaryDirectory() as folder:return kraken_region(image_path,model_path,Path(folder)/'result.xml',segmentation)
    from PIL import Image
    from dataclasses import replace
    from kraken import blla,rpred,serialization
    from kraken.lib.models import load_any
    try:from .engine import parse_alto
    except ImportError:from engine import parse_alto
    with Image.open(image_path) as source:image=source.convert('RGB')
    bounds=blla.segment(image,model=segmentation_model(segmentation),device='cpu')
    model=cached_model('kraken',model_path,lambda:load_any(str(model_path),device='cpu'))
    records=list(rpred.rpred(model,image,bounds))
    xml=serialization.serialize(replace(bounds,lines=records),image_size=image.size,template='alto')
    if alto_path:
        Path(alto_path).write_text(xml,encoding='utf-8');return parse_alto(alto_path)
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'result.xml';path.write_text(xml,encoding='utf-8');return parse_alto(path)


def model_metadata(path):
    path=Path(path).resolve()
    if path.is_dir():
        config=json.loads((path/'config.json').read_text(encoding='utf8'))
        if config.get('model_type')!='vision-encoder-decoder':raise ValueError('Непідтримувана модель розпізнавання.')
        processor_path=path/'processor_config.json';processor=json.loads(processor_path.read_text(encoding='utf8')) if processor_path.exists() else {}
        return {'engine':'trocr','path':str(path),'alphabet':None,'input_size':processor.get('image_processor',{}).get('size'),'segmentation':'separate line segmentation required','limits':'Generative recognizer; outputs require source review.'}
    if path.suffix=='.safetensors':
        from kraken.tasks import RecognitionTaskModel
        model=cached_model('kraken-task',path,lambda:RecognitionTaskModel.load_model(str(path)))
        alphabet=''.join(model.net.codec.c2l);size=model.net.input;segmentation=model.net.seg_type
    else:
        from kraken.lib.models import load_any
        model=cached_model('kraken',path,lambda:load_any(str(path),device='cpu'))
        alphabet=''.join(model.nn.user_metadata.get('codec',{}));size=model.nn.input;segmentation=model.seg_type
    import unicodedata
    def supports(c):return c in alphabet or all(part in alphabet for part in unicodedata.normalize('NFD',c))
    return {'engine':'kraken','path':str(path),'alphabet':alphabet,'input':list(size),'segmentation':segmentation,
            'missing_polish_characters':''.join(c for c in 'ąćęłńóśźżĄĆĘŁŃÓŚŹŻ' if not supports(c)),
            'missing_czech_characters':''.join(c for c in 'čďěňřšťůžČĎĚŇŘŠŤŮŽ' if not supports(c)),
            'limits':'A codec cannot output missing characters. Character support does not establish accuracy.'}


class RecognizerTools:
    def __init__(self,engine):self.engine=engine

    def model_inspect(self,a):
        path=Path(a['model']).resolve()
        files=[path] if path.is_file() else sorted(p for p in path.rglob('*') if p.is_file() and p.suffix in {'.json','.safetensors','.bin','.model','.txt'})
        if not files:raise ValueError('Виберіть локальну модель.')
        stamp=[(str(p),p.stat().st_size,p.stat().st_mtime_ns) for p in files]
        key=hashlib.sha256(json.dumps({'version':2,'files':stamp}).encode()).hexdigest();cache=self.engine.root/'cache'/('model-info-'+key+'.json')
        if cache.is_file():return json.loads(cache.read_text(encoding='utf8'))
        info=dict(model_metadata(path))
        hashes={}
        for file in files:
            with file.open('rb') as source:hashes[file.relative_to(path).as_posix() if path.is_dir() else file.name]=hashlib.file_digest(source,'sha256').hexdigest()
        info['sha256']=hashes;info['identity']=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
        cache.write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf8');return info


def trocr_page(image_path,model_path,segmentation=None):
    from PIL import Image,ImageDraw
    from kraken import blla
    try:
        from .htr_compare import trocr_lines
    except ImportError:from htr_compare import trocr_lines
    with Image.open(image_path) as source:image=source.convert('RGB')
    bounds=blla.segment(image,model=segmentation_model(segmentation),device='cpu')
    lines=[];paths=[]
    with tempfile.TemporaryDirectory() as folder:
        for n,line in enumerate(bounds.lines):
            polygon=line.boundary
            if not polygon:continue
            x=max(0,int(min(p[0] for p in polygon)));y=max(0,int(min(p[1] for p in polygon)))
            right=min(image.width,int(max(p[0] for p in polygon))+1);bottom=min(image.height,int(max(p[1] for p in polygon))+1)
            if right<=x or bottom<=y:continue
            cropped=image.crop((x,y,right,bottom));mask=Image.new('L',cropped.size,0);ImageDraw.Draw(mask).polygon([(p[0]-x,p[1]-y) for p in polygon],fill=255)
            white=Image.new('RGB',cropped.size,'white');white.paste(cropped,(0,0),mask)
            path=Path(folder)/(str(n)+'.png');white.save(path);paths.append(path);lines.append({'box':[x,y,right-x,bottom-y],'polygon':polygon,'confidence':None})
        if not lines:raise ValueError('Рядків не знайдено. Позначте рядок або колонку вручну.')
        for line,result in zip(lines,trocr_lines(model_path,paths),strict=True):
            if 'error' in result:raise RuntimeError(result['error'])
            line['text']=result['text']
    return lines


def kraken_region(image_path, model_path, alto_path, segmentation=None, single_line=False, threads=2, layout_xml=None):
    """Persistent region adapter; line geometry is the crop, never a word box."""
    import torch
    torch.set_num_threads(max(1,min(4,threads)))
    from dataclasses import replace
    from kraken.tasks import RecognitionTaskModel,SegmentationTaskModel
    from kraken.configs import RecognitionInferenceConfig,SegmentationInferenceConfig
    from kraken.containers import BBoxLine,Segmentation
    from kraken.lib.util import open_image
    from kraken import serialization
    try:from .engine import parse_alto
    except ImportError:from engine import parse_alto
    image=open_image(str(image_path))
    model=cached_model('kraken-task',model_path,lambda:RecognitionTaskModel.load_model(str(model_path)))
    if layout_xml:
        from kraken.lib.xml import XMLPage
        parsed=XMLPage(layout_xml,filetype='alto',linetype='baselines')
        if parsed.image_size!=image.size:raise ValueError('Saved layout image size differs.')
        bounds=replace(parsed.to_container(),imagename=str(image_path))
    elif single_line:
        bounds=Segmentation(type='bbox',text_direction='horizontal-tb',imagename=str(image_path),script_detection=False,lines=[BBoxLine(id='region-line',bbox=(0,0,image.width,image.height))])
    else:
        from importlib import resources
        segmentation=segmentation or str(resources.files('kraken').joinpath('blla.mlmodel'))
        segmenter=cached_model('segmentation-task',segmentation,lambda:SegmentationTaskModel.load_model(str(segmentation)))
        bounds=segmenter.predict(image,SegmentationInferenceConfig(accelerator='cpu',device=1,num_threads=threads))
    records=list(model.predict(im=image,segmentation=bounds,config=RecognitionInferenceConfig(accelerator='cpu',device=1,num_threads=threads,num_line_workers=0)))
    xml=serialization.serialize(replace(bounds,lines=records),image_size=image.size,template='alto')
    Path(alto_path).write_text(xml,encoding='utf-8')
    return parse_alto(alto_path)
