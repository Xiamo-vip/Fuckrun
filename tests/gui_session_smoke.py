"""Exercise checkpoint changes through the GUI without live API calls."""
from pathlib import Path
import os
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('GHOSTRUNNER_STATE_DIR',str(Path(__file__).resolve().parents[1]/'evidence/gui-session-state'))
import app as module
from running import RunSession

created=[]
OTHER=[{'id':99,'latitude':30.,'longitude':120.,'radius':10}]
class ChangedSession(RunSession):
    def __init__(self,*args,**kwargs):
        original=kwargs['transport']
        def transport(path,payload=None):
            result=original(path,payload)
            if path=='/create_running_record':
                created.append(path)
                result['data']['checkpoints']=OTHER
                result['data']['record_id']=914240
            return result
        kwargs['transport']=transport
        super().__init__(*args,**kwargs)
module.RunSession=ChangedSession
application=module.Application(demo=True)
application.dialog.askokcancel=lambda *args,**kwargs: True
confirmations=[]
application.dialog.askokcancel=lambda *args,**kwargs: confirmations.append(args) or True
application.load_map=lambda:None
errors=[]
application.dialog.showerror=lambda *args,**kwargs:errors.append(args)
def until(predicate):
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        application.root.update()
        if predicate():return
        time.sleep(.02)
    raise AssertionError(application.status.get())
try:
    application.enter_running()
    until(lambda:application.route is not None and not application.planning)
    application.jitter_enabled.set(True)
    application.jitter_seed.set('42')
    application.plan()
    until(lambda:application.route is not None and not application.planning)
    application.execute_run()
    assert application.tabs.select()==str(application.execution_tab)
    until(lambda:application.run_state=='finished')
    assert len(confirmations)==1,confirmations
    assert application.route['checkpoints'][0]['id']==99
    assert application.route['jitter']['seed']=='42'
    assert application.tabs.select()==str(application.execution_tab)
    assert application.progress_value.get()==100
    assert application.pending_session is None
    assert len(created)==1,created
    assert not errors,errors
    print('GUI_SESSION_OK: first confirmation finished; record_id=914240 reused; one create; jitter retained; task page progress=100%')
finally:
    application.close()
