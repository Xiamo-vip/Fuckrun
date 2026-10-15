"""Compare release baseline with current retry/capture-guide implementation."""
import ast,copy,importlib.util
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
source=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT
spec=importlib.util.spec_from_file_location('probe_retry',source/'running.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
page=any(isinstance(n,ast.FunctionDef) and n.name=='build_capture_page' for n in ast.walk(ast.parse((source/'app.py').read_text(encoding='utf-8-sig'))))
cps=[dict(id=1,latitude=25.,longitude=118.,radius=10)]
p=m.generate_plan(cps,'OFFLINE',1,leg=lambda a,b:{'points':[a,b]})
calls=[];events=[];chunks=[];clock=[1700000000000]
def send(path,payload=None):
    calls.append(path)
    if path=='/login/wechat/info':return dict(data=dict(student_number='TEST'))
    if path=='/create_running_record':return dict(data=dict(record_id=7,run_session_id='TEST',session_salt='SALT',checkpoints=cps))
    if path=='/upload_running_chunk':
        chunks.append(copy.deepcopy(payload))
        if len(chunks)==1:raise RuntimeError('HTTP 503: offline')
    return dict(code=200)
def wait(sec):clock[0]+=max(1,int(sec*1000))
s=m.RunSession('OFFLINE',p,lambda n,d:events.append((n,d)),send,lambda:clock[0],wait)
s.run()
if hasattr(s,'retry_now'):
    assert page
    assert chunks[0]==chunks[1]
    assert any(n=='run_retry_wait' for n,_ in events)
    assert any(n=='run_finished' for n,_ in events)
    assert calls.count('/create_running_record')==1
    print('MODIFIED_OK: HTTP503 waits then retries same chunk; one session finished; capture guide present')
else:
    assert not page
    assert any(n=='run_error' for n,_ in events)
    assert len(chunks)==1
    print('BASELINE_NO_RETRY_GUIDE: HTTP503 ends task; no capture instruction page')
