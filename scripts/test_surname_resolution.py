"""Native-resolution/crop experiment; no restoration, references or model updates."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
from PIL import Image,ImageDraw
import pymupdf

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'test-output/gologory-surname-review'
JPG=ROOT/'test-output/gologory-source-research/PL_1_301_334_0003.jpg'
PDF=Path('C:/Users/inst/Desktop/родовід/Гологори_римо-католицькі_смерті_1755-1795_AGAD_301_334.pdf')
for key in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS']:os.environ[key]='2'

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--recognize-lines',action='store_true');args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'inputs').mkdir(exist_ok=True);source_sha=sha(JPG);pdf_sha=sha(PDF)
    with pymupdf.open(PDF) as pdf:
        embedded=[hashlib.sha256(pdf.extract_image(im[0])['image']).hexdigest() for im in pdf[4].get_images(full=True)]
    assert source_sha in embedded,'Official JPEG differs from PDF embedded image'
    with Image.open(JPG) as image:source=image.convert('RGB');assert source.size==(2500,1515)
    definitions=[('full-native',(0,0,2500,1515)),('left-native',(0,0,1280,1515)),('entry-native',(175,151,1250,341))]
    lines=[('entry-line1',(185,164,1235,209)),('entry-line2',(405,205,1235,246)),('entry-line3',(405,242,940,282))]
    cases=[];line_cases=[];sheet=Image.new('RGB',(1000,1100),'white');draw=ImageDraw.Draw(sheet)
    for index,(ident,rect) in enumerate(definitions+lines):
        crop=source.crop(rect);path=OUT/'inputs'/(ident+'.png');crop.save(path)
        alias={'path':str(path),'label':ident,'origin':'Exact native JPEG crop from PDF scan5','source_document':str(PDF),'source_page':5,'source_sha256':pdf_sha,'native_image':str(JPG),'native_image_sha256':source_sha,'sha256':sha(path),'original_size':[2500,1515],'source_region':{'rect_pixels':list(rect),'rect_normalized':[rect[0]/2500,rect[1]/1515,(rect[2]-rect[0])/2500,(rect[3]-rect[1])/1515]},'transform_to_source':{'scale_x':1,'scale_y':1,'offset_x':rect[0],'offset_y':rect[1]}}
        item={'id':ident,'image':str(path),'image_sha256':sha(path),'pixel_sha256':hashlib.sha256(crop.tobytes()).hexdigest(),'size':list(crop.size),'aliases':[alias],'source_region':alias['source_region'],'transform_to_source':alias['transform_to_source']}
        (cases if index<3 else line_cases).append(item)
        thumb=crop.copy();thumb.thumbnail((970,190 if index<2 else 100));y=[0,220,440,570,700,830][index];sheet.paste(thumb,(10,y+24));draw.text((10,y+4),ident,fill='black')
    sheet.save(OUT/'contact-sheet.png')
    manifest={'scope':'Three native-resolution/crop inputs from same exact JPEG; previous1800px full-spread baseline remains separate. No ground-truth text.','preparation':'RGB PNG conversion/cropping only; no restoration, generative pixels or upscaling. Exact native2500x1515JPEG matches embeddedPDFbytes.','source_pdf':str(PDF),'source_pdf_sha256':pdf_sha,'native_jpeg':str(JPG),'native_jpeg_sha256':source_sha,'cases':cases}
    (OUT/'resolution-cases.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'manual-lines.json').write_text(json.dumps({'policy':'Manually bounded unverified text lines, not full entry as one line; no training/reference truth.','lines':line_cases},ensure_ascii=False,indent=2),encoding='utf-8')
    if args.recognize_lines:
        import torch,numpy as np
        from kraken.lib.models import load_any
        from kraken.lib.dataset import ImageInputTransforms
        torch.set_num_threads(2);results=[]
        for name in ['german-handwriting','bohemica']:
            path=ROOT/'models'/name/'model.mlmodel';started=time.perf_counter();model=load_any(str(path),device='cpu');batch,channels,height,width=model.nn.input
            transform=ImageInputTransforms(batch,height,width,channels,(16,0),model.seg_type=='bbox');model_sha=sha(path)
            for case in line_cases:
                started_line=time.perf_counter()
                with Image.open(case['image']) as crop:tensor=transform(crop.convert('RGB')).unsqueeze(0)
                with torch.inference_mode():decoded=model.predict(tensor)[0]
                raw=[{'text':text,'codepoints':['U+%04X'%ord(c) for c in text],'start_timestep':int(start),'end_timestep':int(end),'decoder_confidence':float(confidence)} for text,start,end,confidence in decoded]
                codepoints=[{'character':character,'codepoint':'U+%04X'%ord(character),'start_timestep':int(start),'end_timestep':int(end),'decoder_confidence':float(confidence),'shared_decoded_span':len(text)>1} for text,start,end,confidence in decoded for character in text]
                np.savez_compressed(OUT/(name+'-'+case['id']+'-ctc.npz'),probabilities=model.outputs)
                results.append({'model':name,'model_sha256':model_sha,'line':case['id'],'source_image_sha256':case['image_sha256'],'text':''.join(x[0] for x in decoded),'decoded':raw,'input_tensor_shape':list(tensor.shape),'output_shape':list(model.outputs.shape),'decoder':getattr(model.decoder,'__name__',str(type(model.decoder))),'temperature':float(model.temperature),'seconds':time.perf_counter()-started_line})
                results[-1]['decoded_codepoints']=codepoints;results[-1]['raw_ctc_file']=name+'-'+case['id']+'-ctc.npz'
            del model
        report={'policy':'Raw CTC decoder alignment/confidences, not exact glyph segmentation, calibrated probabilities of truth or verified transcription. No language-model autofill and no CER/WER.','results':results,'sources_unchanged':sha(JPG)==source_sha and sha(PDF)==pdf_sha}
        (OUT/'line-model-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    assert sha(JPG)==source_sha and sha(PDF)==pdf_sha
    print(OUT/'resolution-cases.json',flush=True)

if __name__=='__main__':main()
