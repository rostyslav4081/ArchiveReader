"""Serial JSON-lines inference worker. Stdout is exclusively request-ID replies."""
import contextlib
import json
import os
import sys
import time

MAX_LINE_BYTES=16*1024*1024


def serve(stream_in,stream_out,handler=None,max_requests=24):
    if handler is None:
        try:from .engine import handle_request
        except ImportError:from engine import handle_request
        handler=handle_request
    os.environ['ARCHIVEREADER_MODEL_SESSION']='1'
    for count in range(max_requests):
        raw=stream_in.readline(MAX_LINE_BYTES+1)
        if not raw:return
        ident=None;started=time.monotonic()
        try:
            if len(raw.encode('utf-8'))>MAX_LINE_BYTES:raise ValueError('Session request is too large')
            request=json.loads(raw)
            ident=request.get('request_id')
            if not isinstance(ident,str) or not ident or len(ident)>100:raise ValueError('Missing request_id')
            # Neural libraries can print progress to stdout; never mix it with IPC.
            with contextlib.redirect_stdout(sys.stderr):
                if request.get('command') in ['train_model','tutor_train','candidate_train_check']:
                    try:from .htr_compare import clear_model_cache
                    except ImportError:from htr_compare import clear_model_cache
                    clear_model_cache()
                if request.get('command')=='session_status':
                    try:from .htr_compare import model_cache_stats
                    except ImportError:from htr_compare import model_cache_stats
                    result={'pid':os.getpid(),'requests':count+1,'cache':model_cache_stats()}
                else:result=handler(request)
            response={'request_id':ident,'ok':True,'result':result}
        except Exception as exc:
            response={'request_id':ident,'ok':False,'error':str(exc)}
        response['session']={'pid':os.getpid(),'request':count+1,'seconds':round(time.monotonic()-started,6),'restart_after_reply':count+1>=max_requests}
        stream_out.write(json.dumps(response,ensure_ascii=False)+'\n');stream_out.flush()


if __name__=='__main__':
    sys.stdin.reconfigure(encoding='utf-8');sys.stdout.reconfigure(encoding='utf-8')
    serve(sys.stdin,sys.stdout)
