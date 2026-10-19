"""Reproducible SQL/worker timings in a new synthetic test library only.

No model inference, user scans, live databases, or claimed OCR accuracy changes.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import html
import json
import math
from pathlib import Path
import platform
import random
import queue
import threading
import statistics
import subprocess
import sys
import time
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.books import BookTools
from backend.archivereader.genealogy import GenealogyTools
from backend.archivereader.operations import Operations

INDEXES={
 'idx_records_page':'CREATE INDEX idx_records_page ON records(page)',
 'idx_annotations_page':'CREATE INDEX idx_annotations_page ON annotations(page)',
 'idx_person_members_person':'CREATE INDEX idx_person_members_person ON person_members(person)',
 'idx_book_tasks_job_state':'CREATE INDEX idx_book_tasks_job_state ON book_tasks(job,state)',
 'idx_line_history_page_line':'CREATE INDEX idx_line_history_page_line ON line_history(page,line)',
 'idx_book_items_page':'CREATE INDEX idx_book_items_page ON book_items(page)'}


def summarize(values):
    ordered=sorted(values)
    return {'samples':len(values),'p50_ms':round(statistics.median(values),4),'p95_ms':round(ordered[min(len(ordered)-1,max(0,math.ceil(len(ordered)*.95)-1))],4),'min_ms':round(min(values),4),'max_ms':round(max(values),4)}


def populate(engine,count):
    image=engine.root/'tiny-shared.png';Image.new('RGB',(8,8),'white').save(image)
    db=engine.db
    with db:
        # NULL hashes and a shared tiny path mark synthetic metadata, not physical scans.
        db.executemany('INSERT INTO documents(id,name,path,sha) VALUES (?,?,?,NULL)',[(f'd{i:03}',f'Synthetic book {i}',str(image)) for i in range(100)])
        db.executemany('INSERT INTO pages(id,doc,num) VALUES (?,?,?)',[(f'p{i:06}',f'd{i%100:03}',i//100) for i in range(count)])
        db.executemany('INSERT INTO records VALUES (?,?,?)',[(f'r{i:07}',f'p{i//5:06}',json.dumps({'person':f'Synthetic Person {i}','place':'Synthetic village','house':str(i%200),'date':str(1800+i%120),'text':'SQL benchmark only; not an archival transcription.','verified':False})) for i in range(count*5)])
        db.executemany('INSERT INTO annotations VALUES (?,?,?)',[(f'a{i:07}',f'p{i//3:06}',json.dumps({'kind':'line','rect':[.1,.1,.5,.1],'text':'Synthetic','verified':False})) for i in range(count*3)])
        db.executemany('INSERT INTO persons VALUES (?,?)',[(f'i{i:06}',json.dumps({'name':f'Synthetic Person {i}'})) for i in range(count)])
        db.executemany('INSERT INTO person_members VALUES (?,?,?)',[(f'r{i:07}:person',f'i{i//2:06}',json.dumps({'note':'Synthetic membership; no historical assertion.'})) for i in range(count*2)])
        db.executemany('INSERT INTO book_jobs(id,data) VALUES (?,?)',[(f'j{i:02}','{}') for i in range(10)])
        db.executemany('INSERT INTO book_tasks(job,page,state) VALUES (?,?,?)',[(f'j{job:02}',f'p{i:06}','pending' if i%10==0 else 'done') for job in range(10) for i in range(count//2)])
        db.executemany('INSERT INTO line_history(page,line,before,after) VALUES (?,?,?,?)',[(f'p{i//10:06}',i%3,'before','after') for i in range(count*10)])
        db.executemany('INSERT INTO photo_books VALUES (?,?,?)',[(f'b{i:03}',f'Synthetic photo book {i}','{}') for i in range(100)])
        db.executemany('INSERT INTO book_items VALUES (?,?,?,?,?,?)',[(f'bi{i:06}',f'b{i%100:03}',i//100,f'p{i:06}',str(i),'Synthetic') for i in range(count)])
    return {'documents':100,'pages':count,'records':count*5,'annotations':count*3,'people':count,'memberships':count*2,'queue_tasks':count//2*10,'line_history':count*10,'book_items':count}


def queries(count,iterations):
    rng=random.Random(20261015);targets=[rng.randrange(count) for _ in range(iterations)]
    return {
      'records_page':('SELECT * FROM records WHERE page=?',[(f'p{i:06}',) for i in targets]),
      'annotations_page':('SELECT * FROM annotations WHERE page=? ORDER BY rowid',[(f'p{i:06}',) for i in targets]),
      'person_members':('SELECT * FROM person_members WHERE person=? ORDER BY rowid',[(f'i{i:06}',) for i in targets]),
      'tasks_queue':('SELECT * FROM book_tasks WHERE job=? AND state=?',[(f'j{i%10:02}','pending') for i in targets]),
      'line_history':('SELECT * FROM line_history WHERE page=? AND line=? ORDER BY id DESC LIMIT 20',[(f'p{i:06}',i%3) for i in targets]),
      'book_items_page':('SELECT * FROM book_items WHERE page=?',[(f'p{i:06}',) for i in targets]),
      'pages_document_existing_unique_index_control':('SELECT * FROM pages WHERE doc=? ORDER BY num',[(f'd{i%100:03}',) for i in targets])}


def measure(db,cases):
    result={}
    for name,(sql,parameters) in cases.items():
        for args in parameters[:2]:db.execute(sql,args).fetchall()
        values=[];checksum=hashlib.sha256();rows_count=[]
        for args in parameters:
            started=time.perf_counter_ns();rows=db.execute(sql,args).fetchall();values.append((time.perf_counter_ns()-started)/1e6)
            canonical=sorted([tuple(row) for row in rows],key=repr);checksum.update(json.dumps(canonical,ensure_ascii=False,sort_keys=True).encode());rows_count.append(len(rows))
        result[name]=summarize(values)|{'sql':sql,'first_parameters':parameters[0],'explain':[r['detail'] for r in db.execute('EXPLAIN QUERY PLAN '+sql,parameters[0])],'result_sha256':checksum.hexdigest(),'rows_per_query_min':min(rows_count),'rows_per_query_max':max(rows_count)}
    return result


def cold_worker(library,samples):
    values=[];checksums=set()
    for _ in range(samples):
        started=time.perf_counter_ns();run=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'backend/archivereader/engine.py')],input=json.dumps({'root':str(library),'command':'list_pages'}),encoding='utf-8',capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        response=json.loads(run.stdout);elapsed=(time.perf_counter_ns()-started)/1e6
        if run.returncode or not response.get('ok'):raise RuntimeError('Cold worker failed: '+str(response))
        values.append(elapsed);checksums.add(hashlib.sha256(json.dumps(response['result'],sort_keys=True).encode()).hexdigest())
    if len(checksums)!=1:raise RuntimeError('Cold worker results changed.')
    return summarize(values)|{'result_sha256':next(iter(checksums)),'method':'New Python process + Engine initialization + actual list_pages request (10k results serialized/decoded); not model startup.'}


def warm_worker(library,samples):
    worker=ROOT/'backend/archivereader/model_session.py'
    process=subprocess.Popen([sys.executable,'-X','utf8',str(worker)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    replies=queue.Queue();threading.Thread(target=lambda:[replies.put(line) for line in process.stdout],daemon=True).start();values=[];checksums=set()
    try:
        for index in range(samples+1):
            ident='benchmark-'+str(index);started=time.perf_counter_ns();process.stdin.write(json.dumps({'request_id':ident,'root':str(library),'command':'list_pages'})+'\n');process.stdin.flush();response=json.loads(replies.get(timeout=30));elapsed=(time.perf_counter_ns()-started)/1e6
            if response.get('request_id')!=ident or not response.get('ok'):raise RuntimeError('Warm worker failed: '+str(response))
            values.append(elapsed);checksums.add(hashlib.sha256(json.dumps(response['result'],sort_keys=True).encode()).hexdigest())
        if len(checksums)!=1:raise RuntimeError('Warm worker results changed.')
        process.stdin.close();process.wait(timeout=10)
        return summarize(values[1:])|{'first_request_ms':round(values[0],4),'result_sha256':next(iter(checksums)),'method':'One JSONL Python process; first request separately reported, then repeated list_pages with identical 10k-result serialization/decoding. No model loaded.'}
    finally:
        if process.poll() is None:process.kill();process.wait(timeout=10)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--pages',type=int,default=10000);parser.add_argument('--iterations',type=int,default=100);parser.add_argument('--cold-samples',type=int,default=0);parser.add_argument('--warm-session',action='store_true');args=parser.parse_args()
    if args.pages<100 or args.iterations<10:raise ValueError('Use at least 100 pages and 10 samples.')
    out=ROOT/'test-output'/('performance-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'));out.mkdir(parents=True,exist_ok=False);library=out/'library';engine=Engine(library);BookTools(engine);GenealogyTools(engine);Operations(engine)
    initial_indexes=[dict(r) for r in engine.db.execute("SELECT name,tbl_name,sql FROM sqlite_master WHERE type='index'")]
    # These names are fixed code constants, never supplied by a source file/user DB.
    with engine.db:
        for name in INDEXES:engine.db.execute('DROP INDEX IF EXISTS '+name)
    counts=populate(engine,args.pages);cases=queries(args.pages,args.iterations);before=measure(engine.db,cases)
    started=time.perf_counter()
    with engine.db:
        for sql in INDEXES.values():engine.db.execute(sql)
    build_seconds=time.perf_counter()-started;after=measure(engine.db,cases)
    for name in before:assert before[name]['result_sha256']==after[name]['result_sha256'],name+' changed query results'
    profile_times=[]
    for _ in range(10):
        started=time.perf_counter_ns();engine.profile({});profile_times.append((time.perf_counter_ns()-started)/1e6)
    engine.db.close()
    report={'created_utc':datetime.now(timezone.utc).isoformat(),'python':sys.version,'platform':platform.platform(),'sqlite_version':__import__('sqlite3').sqlite_version,'fixture':str(library),'counts':counts,'initial_indexes':initial_indexes,'candidate_indexes':INDEXES,'index_build_seconds':round(build_seconds,4),'before':before,'after':after,'result_checksums_match':True,'in_process_profile':summarize(profile_times),'limitations':['Synthetic SQL metadata: shared tiny image, no physical 10,000-page document was rendered.','Measures warm SQLite query+fetch latency after two warmups; OS caches are not flushed.','Queries are run sequentially on one machine; background load can affect timings.','Existing primary-key/unique indexes are kept; pages(doc,num) is an unchanged control.','No model inference, ML accuracy, complete application startup, or UI throughput is measured.']}
    if args.cold_samples:report['cold_worker_list_pages']=cold_worker(library,args.cold_samples)
    if args.warm_session:
        report['warm_worker_list_pages']=warm_worker(library,max(3,min(args.cold_samples or 10,20)))
        if args.cold_samples:assert report['warm_worker_list_pages']['result_sha256']==report['cold_worker_list_pages']['result_sha256']
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    esc=html.escape;page=['<!doctype html><meta charset="utf-8"><title>ArchiveReader performance</title><style>body{font:16px/1.5 system-ui;max-width:1100px;margin:40px auto;padding:0 20px}table{border-collapse:collapse;width:100%}td,th{padding:10px;border:1px solid #ddd}pre{white-space:pre-wrap}code{font-size:13px}</style><h1>ArchiveReader: SQL performance</h1><p>Isolated synthetic library: '+str(args.pages)+' pages, '+str(counts['records'])+' records. Result checksums match before/after.</p><table><tr><th>Query</th><th>Before p50 / p95 ms</th><th>After p50 / p95 ms</th><th>Query plan before → after</th></tr>']
    for name in before:
        a,b=before[name],after[name];page.append('<tr><td>'+esc(name)+'</td><td>'+str(a['p50_ms'])+' / '+str(a['p95_ms'])+'</td><td>'+str(b['p50_ms'])+' / '+str(b['p95_ms'])+'</td><td><code>'+esc('; '.join(a['explain']))+'<br>→ '+esc('; '.join(b['explain']))+'</code></td></tr>')
    page.append('</table>')
    if args.cold_samples:page.append('<h2>New worker process</h2><pre>'+esc(json.dumps(report['cold_worker_list_pages'],indent=2))+'</pre>')
    if args.warm_session:page.append('<h2>Persistent JSONL worker</h2><pre>'+esc(json.dumps(report['warm_worker_list_pages'],indent=2))+'</pre>')
    page.append('<h2>Limits</h2><ul>'+''.join('<li>'+esc(x)+'</li>' for x in report['limitations'])+'</ul><p><a href="report.json">Full report, checksums and environment</a></p>');(out/'report.html').write_text('\n'.join(page),encoding='utf-8');print(out)

if __name__=='__main__':main()
