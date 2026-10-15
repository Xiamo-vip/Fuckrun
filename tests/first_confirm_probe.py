"""Offline first-confirm probe, usable against preserved or current running.py."""
import importlib.util
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
source=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT
spec=importlib.util.spec_from_file_location('probe_session',source/'running.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
cps=[dict(id=1,latitude=25.,longitude=118.,radius=10)]
actual=[dict(id=2,latitude=30.,longitude=120.,radius=10)]
def plan(points):return m.generate_plan(points,'OFFLINE',1,leg=lambda a,b:{'points':[a,b]})
events=[];calls=[];clock=[1700000000000]
def send(path,payload=None):
    calls.append((path,payload))
    if path=='/login/wechat/info':return dict(data=dict(student_number='TEST'))
    if path=='/create_running_record':return dict(data=dict(record_id=914240,run_session_id='TEST',session_salt='SALT',checkpoints=actual))
    return dict(code=200)
def wait(seconds):clock[0]+=max(1,int(seconds*1000))
s=m.RunSession('OFFLINE',plan(cps),lambda n,d:events.append((n,d)),send,lambda:clock[0],wait,replan=plan)
s.run()
assert sum(p=='/create_running_record' for p,_ in calls)==1
if any(n=='run_finished' for n,_ in events):
    assert calls[-1][0]=='/finish_running_record'
    assert calls[-1][1]['record_id']==914240
    assert all(cp['reached'] for cp in calls[-1][1]['client_checkpoint_data'])
    print('FIRST_CONFIRM_OK: one confirmation; one create; actual checkpoints replanned; same record finished')
else:
    assert any(n=='run_replanned' for n,_ in events)
    assert len(calls)==2
    print('BASELINE_FIRST_CONFIRM_PAUSED: checkpoint change requires a second confirmation; no upload')
