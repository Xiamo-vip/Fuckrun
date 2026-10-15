"""Offline retry task page: recover with same payload or stop while waiting."""
import copy,os
from pathlib import Path
import sys,time
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
os.environ.setdefault('GHOSTRUNNER_STATE_DIR',str(BASE/'evidence/execution-error-state'))
import app as module
from running import RunSession
stop_mode='--stop' in sys.argv
attempts=[]
class FailingSession(RunSession):
    def __init__(self,*args,**kwargs):
        original=kwargs['transport']
        def send(path,payload=None):
            if path=='/upload_running_chunk':
                attempts.append(copy.deepcopy(payload))
                if stop_mode or len(attempts)==1:raise RuntimeError('HTTP 503: /upload_running_chunk')
            return original(path,payload)
        kwargs.update(transport=send,retry_delay=600,retry_max_delay=600)
        super().__init__(*args,**kwargs)
module.RunSession=FailingSession
app=module.Application(demo=True)
app.load_map=lambda:None
app.dialog.askokcancel=lambda *args,**kwargs:True
errors=[];app.dialog.showerror=lambda *args,**kwargs:errors.append(args)
def wait_for(test):
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        app.root.update()
        if test():return
        time.sleep(.02)
    raise AssertionError(app.status.get())
try:
    app.enter_running()
    wait_for(lambda:app.route is not None and not app.planning)
    app.execute_run()
    wait_for(lambda:app.run_state=='retry_wait')
    assert app.tabs.select()==str(app.execution_tab)
    assert '自动重试' in app.execution_state.get()
    assert str(app.execution_retry['state'])=='normal'
    assert str(app.replan_button['state'])=='disabled'
    assert str(app.execution_stop['state'])=='normal'
    original=app.run_session
    app.execute_run();assert app.run_session is original
    rows=[app.request_tree.item(i,'values') for i in app.request_tree.get_children()]
    assert len(rows)==3 and '503' in rows[-1][5]
    assert app.request_failures==1 and app.progress_value.get()<100
    if stop_mode:
        app.stop_run();wait_for(lambda:app.run_state=='stopped')
        assert len(attempts)==1
        assert app.progress_value.get()<100
        print('RETRY_STOP_OK: waiting task cancellable; one failed upload; no finish; task page retained')
    else:
        app.retry_run();wait_for(lambda:app.run_state=='finished')
        assert attempts[0]==attempts[1]
        assert app.progress_value.get()==100
        assert app.request_failures==1
        assert app.tabs.select()==str(app.execution_tab)
        print('RETRY_GUI_OK: countdown visible; retry-now resumes same payload; one session; progress=100%')
    assert str(app.execution_retry['state'])=='disabled'
    assert not errors,errors
finally:app.close()
