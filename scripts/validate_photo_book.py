"""Exercise a small private photo-book copy; outputs stay under ignored test-output.

This validates import/ordering/recognition/export execution, not HTR accuracy.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import uuid
import pymupdf

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.books import BookTools


def main():
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path);parser.add_argument('--limit',type=int,default=3);parser.add_argument('--model',type=Path);parser.add_argument('--recognize-page',type=int,default=1)
    args=parser.parse_args()
    files=sorted([p for p in args.folder.iterdir() if p.suffix.lower() in {'.jpg','.jpeg','.png','.tif','.tiff'}],key=lambda p:[(1,int(t)) if t.isdigit() else (0,t.casefold()) for t in re.split(r'(\d+)',p.name)])[:max(1,min(args.limit,10))]
    if not files:raise ValueError('No supported source photographs')
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    output=ROOT/'test-output'/('photo-book-validation-'+uuid.uuid4().hex[:10]);output.mkdir(parents=True)
    engine=Engine(output/'library');tools=BookTools(engine);items=[]
    try:
        for path in files:
            doc=engine.import_file({'path':str(path)})['id']
            items.extend({'page':r['id'],'label':path.name} for r in engine.db.execute('SELECT id FROM pages WHERE doc=? ORDER BY num',(doc,)))
        book=tools.book_save({'name':args.folder.name+' — diagnostic subset','items':items})
        recognition=None
        if args.model:
            if not 1<=args.recognize_page<=len(items):raise ValueError('Recognition page outside selected subset')
            executable=Path(sys.executable).parent/('kraken.exe' if sys.platform=='win32' else 'kraken')
            recognition=engine.recognize({'id':items[args.recognize_page-1]['page'],'engine':'kraken','executable':str(executable),'model':str(args.model.resolve()),'useTextLayer':False})
        result=tools.book_pdf({'book':book['id'],'path':str(output/'book.pdf')})
        with pymupdf.open(result['path']) as pdf:
            text_pages=sum(bool(p.get_text().strip()) for p in pdf)
            pdf[0].get_pixmap(matrix=pymupdf.Matrix(1,1)).save(output/'first-page.png')
            if len(pdf)!=len(items):raise AssertionError('Page count mismatch')
        after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        if before!=after:raise AssertionError('Source bytes changed')
        report={'book':book['id'],'pdf':result['path'],'source_hashes_unchanged':True,'pages':len(items),'pages_with_text':text_pages,'recognition':recognition,'coverage':tools.book_index({'book':book['id']}),'limits':'Diagnostic subset only. No verified historical ground truth; no accuracy claim.'}
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({'output':str(output),'pages':len(items),'pages_with_text':text_pages,'source_hashes_unchanged':True},ensure_ascii=False))
    finally:engine.db.close()


if __name__=='__main__':main()
