"""Offline, paired recognition of identical line crops. Never changes saved OCR."""
import gc
import hashlib
import html
import json
from pathlib import Path
import random
import time
import unicodedata
import os
from collections import OrderedDict

try:
    from .engine import error_rate
except ImportError:
    from engine import error_rate


def normalize(text):
    return ' '.join(unicodedata.normalize('NFC', text).split())


def score(reference, hypothesis):
    reference, hypothesis = normalize(reference), normalize(hypothesis)
    chars, words = len(reference), len(reference.split())
    cer, wer = error_rate(list(reference), list(hypothesis)), error_rate(reference.split(), hypothesis.split())
    return {'characters': chars, 'words': words, 'cer': cer, 'wer': wer,
            'character_errors': round(cer * chars) if cer is not None else None,
            'word_errors': round(wer * words) if wer is not None else None,
            'exact': reference == hypothesis}


def file_sha256(path):
    with Path(path).open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()


_MODEL_CACHE=OrderedDict()
_CACHE_COUNTS={'hits':0,'loads':0,'invalidations':0,'evictions':0}


def clear_model_cache():
    _MODEL_CACHE.clear();gc.collect()


def model_cache_stats():
    return dict(_CACHE_COUNTS,capacity=2,loaded=len(_MODEL_CACHE),entries=[{'kind':key[0],'path':key[1],'identity':value[0]} for key,value in _MODEL_CACHE.items()])


def cached_model(kind,path,loader):
    """Bounded process-local cache, enabled only by the persistent worker.

    Every lookup checks streamed content hashes (including tokenizer/config and
    shards), so replacing weights with identical timestamps cannot reuse them.
    """
    if os.environ.get('ARCHIVEREADER_MODEL_SESSION')!='1':return loader()
    try:from .model_identity import fingerprint_path
    except ImportError:from model_identity import fingerprint_path
    key=(kind,str(Path(path).resolve()));identity=fingerprint_path(path)['sha256']
    previous=_MODEL_CACHE.get(key)
    if previous and previous[0]==identity:
        _MODEL_CACHE.move_to_end(key);_CACHE_COUNTS['hits']+=1;return previous[1]
    if previous:
        del _MODEL_CACHE[key];del previous;_CACHE_COUNTS['invalidations']+=1;gc.collect()
    if kind=='trocr':
        # Keep at most one large encoder-decoder in memory, even if several
        # TrOCR candidates are compared sequentially in the same process.
        for old_key in list(_MODEL_CACHE):
            if old_key[0]=='trocr':
                del _MODEL_CACHE[old_key];_CACHE_COUNTS['evictions']+=1;gc.collect()
    # Evict before loading the next network, avoiding a transient third model.
    while len(_MODEL_CACHE)>=2:
        _MODEL_CACHE.popitem(last=False);_CACHE_COUNTS['evictions']+=1;gc.collect()
    loaded=loader();_MODEL_CACHE[key]=(identity,loaded);_CACHE_COUNTS['loads']+=1
    return loaded


def kraken_lines(model_path, images):
    if Path(model_path).suffix=='.safetensors':
        import tempfile
        try:from .recognizers import kraken_region
        except ImportError:from recognizers import kraken_region
        with tempfile.TemporaryDirectory() as folder:
            for n,path in enumerate(images):
                try:
                    lines=kraken_region(path,model_path,Path(folder)/f'{n}.xml',single_line=True)
                    yield {'text':'\n'.join(line['text'] for line in lines)}
                except Exception as exc:yield {'error':str(exc)}
        return
    from PIL import Image
    from kraken.lib.models import load_any
    from kraken.lib.dataset import ImageInputTransforms
    model = cached_model('kraken',model_path,lambda:load_any(str(model_path), device='cpu'))
    batch, channels, height, width = model.nn.input
    # Baseline crops are already rectified by the common extraction step.
    # Bbox normalization would distort them and invalidate the comparison.
    transforms = ImageInputTransforms(batch, height, width, channels, (16, 0), model.seg_type == 'bbox')
    for path in images:
        try:
            with Image.open(path) as source:
                image = source.convert('RGB')
            yield {'text': model.predict_string(transforms(image).unsqueeze(0))[0]}
        except Exception as exc:
            yield {'error': str(exc)}


def trocr_lines(model_path, images):
    from PIL import Image
    import torch
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel,ViTImageProcessor,PreTrainedTokenizerFast
    torch.set_num_threads(max(1,min(4,torch.get_num_threads())))
    def load():
        folder=Path(model_path)
        # Preserve the processor contract rather than silently using legacy size.
        modern=folder/'processor_config.json';custom=False
        if modern.is_file() and 'image_processor' in (configuration:=json.loads(modern.read_text(encoding='utf8'))):
            image_settings=configuration['image_processor'];tokenizer_settings=json.loads((folder/'tokenizer_config.json').read_text(encoding='utf8'))
            tokenizer=PreTrainedTokenizerFast(tokenizer_file=str(folder/'tokenizer.json'),**{k:tokenizer_settings[k] for k in ['bos_token','eos_token','pad_token','unk_token','mask_token','sep_token','cls_token'] if k in tokenizer_settings})
            processor=TrOCRProcessor(image_processor=ViTImageProcessor(**image_settings),tokenizer=tokenizer);custom=True
        else:processor=TrOCRProcessor.from_pretrained(str(model_path),local_files_only=True,use_fast=False)
        model=VisionEncoderDecoderModel.from_pretrained(str(model_path),local_files_only=True).eval()
        return processor,model,custom
    processor,model,custom=cached_model('trocr',model_path,load)
    limit=96 if custom else 256
    for path in images:
        try:
            with Image.open(path) as source:
                pixels = processor(images=source.convert('RGB'), return_tensors='pt').pixel_values
            with torch.inference_mode():
                tokens = model.generate(pixels, max_new_tokens=limit,num_beams=1,**({'interpolate_pos_encoding':True} if custom else {}))
            # A length-limited output is not a successful complete transcription.
            text = processor.batch_decode(tokens, skip_special_tokens=True)[0]
            eos=model.generation_config.eos_token_id
            eos={eos} if isinstance(eos,int) else set(eos or [])
            if tokens.shape[-1] >= limit+1 and tokens[0, -1].item() not in eos:
                yield {'error': 'Generation reached token limit', 'partial_text': text}
            else:
                yield {'text': text}
        except Exception as exc:
            yield {'error': str(exc)}


def paired_interval(rows, left, right):
    """Page-cluster bootstrap for paired CER difference (left minus right)."""
    pages = {}
    for row in rows:
        a, b = row['results'].get(left, {}), row['results'].get(right, {})
        if 'score' not in a or 'score' not in b or not a['score']['characters']:
            continue
        group = pages.setdefault(row.get('source', row['id']), [0, 0])
        group[0] += a['score']['character_errors'] - b['score']['character_errors']
        group[1] += a['score']['characters']
    groups = list(pages.values())
    if len(groups) < 2:
        return None
    rng = random.Random(20261012)
    estimates = []
    for _ in range(1000):
        sample = rng.choices(groups, k=len(groups))
        estimates.append(sum(g[0] for g in sample) / sum(g[1] for g in sample))
    estimates.sort()
    return {'difference': sum(g[0] for g in groups) / sum(g[1] for g in groups),
            'lower_95': estimates[25], 'upper_95': estimates[974], 'pages': len(groups),
            'meaning': 'CER(left)-CER(right), paired successful lines only; page bootstrap, not a population guarantee'}


def ensemble_vote(results,configurations):
    """Show independent alternatives, never synthesize a genealogical fact."""
    groups={};failures=[]
    for config in configurations:
        result=results.get(config['name'],{})
        if 'text' not in result:failures.append(config['name']);continue
        value=normalize(result['text']);group=groups.setdefault(value,{'text':value,'models':[],'engines':[]})
        group['models'].append(config['name'])
        if config['engine'] not in group['engines']:group['engines'].append(config['engine'])
    agreed=len(groups)==1 and not failures and len(configurations)>=2 and bool(next(iter(groups),'').strip())
    return {'status':'agreed_unverified' if agreed else 'review_required' if groups else 'failed',
            'options':list(groups.values()),'failures':failures,'verified':False,
            'consensus_text':next(iter(groups)) if agreed else None,
            'policy':'Agreement is not proof. Preserve names, diacritics and source-linked raw alternatives.'}


def book_scores(rows,names):
    """Comparable CER denominator: only rows scored successfully by every model."""
    grouped={}
    for row in rows:grouped.setdefault(row.get('book',row.get('document',row.get('source','unknown'))),[]).append(row)
    output=[]
    for ident,cases in grouped.items():
        common=[r for r in cases if all(r['results'].get(n,{}).get('score',{}).get('characters',0)>0 for n in names)]
        models=[]
        for name in names:
            scores=[r['results'][name]['score'] for r in common];chars=sum(s['characters'] for s in scores);words=sum(s['words'] for s in scores)
            models.append({'name':name,'common_cer':sum(s['character_errors'] for s in scores)/chars if chars else None,
                           'common_wer':sum(s['word_errors'] for s in scores)/words if words else None,
                           'failed_lines':sum('text' not in r['results'].get(name,{}) for r in cases)})
        output.append({'book':ident,'name':cases[0].get('book_name',ident),'lines':len(cases),'common_scored_lines':len(common),'models':models})
    return output


def compare(manifest, configurations, output):
    manifest, output = Path(manifest).resolve(), Path(output).resolve()
    cases = json.loads(manifest.read_text(encoding='utf-8'))
    if not configurations or len({c['name'] for c in configurations}) != len(configurations):
        raise ValueError('Provide uniquely named models')
    if any(c['engine'] not in {'kraken', 'trocr'} for c in configurations):
        raise ValueError('Supported comparison engines: kraken, trocr')
    if not cases or len({c['id'] for c in cases}) != len(cases):
        raise ValueError('Manifest must have nonempty, unique case IDs')
    images = [(manifest.parent / c['image']).resolve() for c in cases]
    for case, image in zip(cases, images):
        if hashlib.sha256(image.read_bytes()).hexdigest() != case['image_sha256']:
            raise ValueError('Changed line image: ' + case['id'])
    output.mkdir(parents=True, exist_ok=True)
    rows = [dict(c, image=str(image), results={}) for c, image in zip(cases, images)]
    report = {'normalization': 'NFC and collapsed whitespace; case/diacritics/punctuation retained',
              'mode': 'same reference line crops; segmentation not evaluated', 'models': [], 'rows': rows,
              'limitations': ['Small diagnostic corpus, not proof for genealogical registers.',
                              'Reference transcriptions can contain mistakes.',
                              'Upstream test split is page-based; writer independence is not guaranteed.',
                              'Training overlap of external/pretrained models is unknown unless documented.',
                              'Model disagreement is a review flag, never a corrected transcription.']}
    for config in configurations:
        name, engine, model = config['name'], config['engine'], Path(config['path']).resolve()
        files = [model] if model.is_file() else sorted(p for p in model.iterdir() if p.is_file())
        metadata = dict(config, path=str(model), sha256={p.name: file_sha256(p) for p in files})
        provenance_path = (model.parent if model.is_file() else model) / 'provenance.json'
        if provenance_path.exists():
            metadata['provenance'] = json.loads(provenance_path.read_text(encoding='utf-8'))
        report['models'].append(metadata)
        start = time.monotonic()
        print('Comparing ' + name, flush=True)
        try:
            predictions = kraken_lines(model, images) if engine == 'kraken' else trocr_lines(model, images)
            for row, prediction in zip(rows, predictions, strict=True):
                if 'text' in prediction and 'reference' in row:
                    prediction['score'] = score(row['reference'], prediction['text'])
                row['results'][name] = prediction
        except Exception as exc:
            metadata['error'] = str(exc)
            for row in rows:
                row['results'].setdefault(name, {'error': str(exc)})
        metadata['seconds_including_model_load'] = round(time.monotonic() - start, 3)
        metadata['seconds_per_attempt_including_load'] = metadata['seconds_including_model_load']/len(rows) if rows else None
        gc.collect()
        valid = [row['results'][name]['score'] for row in rows if 'score' in row['results'].get(name, {}) and row['results'][name]['score']['characters']]
        metadata['scored_lines'] = len(valid)
        metadata['failed_lines'] = sum('text' not in row['results'].get(name, {}) for row in rows)
        metadata['micro_cer'] = sum(v['character_errors'] for v in valid) / sum(v['characters'] for v in valid) if valid else None
        metadata['micro_wer'] = sum(v['word_errors'] for v in valid) / sum(v['words'] for v in valid) if valid else None
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    names = [c['name'] for c in configurations]
    for row in rows:
        texts = [normalize(value['text']) for value in row['results'].values() if 'text' in value]
        row['disagreement'] = len(set(texts)) > 1
        row['ensemble']=ensemble_vote(row['results'],configurations)
        if len(names)>=2 and all('text' in row['results'].get(name,{}) for name in names[:2]):
            from difflib import SequenceMatcher
            left,right=(row['results'][name]['text'] for name in names[:2])
            # WPF substring coordinates are UTF-16 code units, not Python code points.
            index=lambda text,n:len(text[:n].encode('utf-16-le'))//2
            row['differences']=[{'operation':op,'a_start':index(left,a0),'a_end':index(left,a1),'b_start':index(right,b0),'b_end':index(right,b1)} for op,a0,a1,b0,b1 in SequenceMatcher(None,left,right,autojunk=False).get_opcodes() if op!='equal']
    if len(names) >= 2:
        report['paired_comparison_first_two'] = paired_interval(rows, names[0], names[1])
    report['by_book'] = book_scores(rows,names)
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    body = ['<!doctype html><html lang="uk"><meta charset="utf-8"><title>HTR comparison</title>',
            '<style>body{font:16px system-ui;margin:2rem;max-width:1200px}article{border-top:2px solid #ccc;padding:1rem}img{max-width:100%;max-height:180px}pre{white-space:pre-wrap}.flag{color:#a43d00}td,th{padding:.5rem;text-align:left}</style>',
            '<h1>Порівняння HTR на однакових рядках</h1><p>Розбіжність — сигнал для перевірки. Автоматично обраного переможця чи виправлення немає.</p>',
            '<p>Малий тест; виділення рядків не оцінюється. Зберігається пунктуація, регістр і діакритика. CER/WER — частки помилок, менше краще.</p>',
            '<table><tr><th>Модель</th><th>CER</th><th>WER</th><th>Перевірено / помилок запуску</th><th>Секунди разом із завантаженням</th></tr>']
    for model in report['models']:
        body.append('<tr>' + ''.join('<td>' + html.escape(str(v)) + '</td>' for v in [model['name'], model['micro_cer'], model['micro_wer'], f"{model['scored_lines']} / {model['failed_lines']}",model['seconds_including_model_load']]) + '</tr>')
    body.append('</table>')
    body.append('<h2>Книги: CER на спільних успішно прочитаних рядках</h2><p>Невдалі спроби показано окремо. Вони не зникають із загальної кількості рядків.</p>')
    for book in report['by_book']:
        body.append('<h3>'+html.escape(book['name'])+'</h3><pre>'+html.escape(json.dumps(book,ensure_ascii=False,indent=2))+'</pre>')
    import base64
    for row in rows:
        encoded = base64.b64encode(Path(row['image']).read_bytes()).decode('ascii')
        body.append(f'<article><h2>{html.escape(row["id"])}</h2><img alt="Рукописний рядок" src="data:image/png;base64,{encoded}">')
        if row['disagreement']:
            body.append('<p class="flag">Моделі розходяться — перевірте оригінал.</p>')
        body.append('<p>Еталон:</p><pre>' + html.escape(row.get('reference', 'Еталона немає')) + '</pre>')
        for name, result in row['results'].items():
            body.append('<p>' + html.escape(name) + '</p><pre>' + html.escape(result.get('text', result.get('error', 'Немає результату'))) + '</pre>')
        body.append('</article>')
    body.append('</html>')
    (output / 'comparison.html').write_text('\n'.join(body), encoding='utf-8')
    return report
