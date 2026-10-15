"""Offline Tkinter jitter controls and preview/execution consistency."""
import copy
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('GHOSTRUNNER_STATE_DIR',str(Path(__file__).resolve().parents[1]/'evidence/gui-jitter-state'))
from app import Application
app=Application(demo=True)
app.load_map=lambda:None
app.dialog.askokcancel=lambda *a,**k:True
errors=[]
app.dialog.showerror=lambda *a,**k:errors.append(a)
def until(predicate):
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        app.root.update()
        if predicate():return
        time.sleep(.02)
    raise AssertionError(app.status.get())
try:
    app.jitter_enabled.set(True)
    app.jitter_amplitude.set('5')
    app.jitter_smooth.set('20')
    app.jitter_seed.set('42')
    app.enter_running()
    until(lambda:app.route is not None and not app.planning)
    assert app.route['jitter']==dict(enabled=True,amplitude_m=5.,smooth_points=20,seed='42')
    assert app.route['points']!=app.route['base_points']
    assert '种子42' in app.run_info.get()
    app.jitter_amplitude.set('6')
    assert app.route is None and str(app.execute_button['state'])=='disabled'
    app.plan()
    until(lambda:app.route is not None and not app.planning)
    preview=copy.deepcopy(app.route)
    app.execute_run()
    assert all(str(w['state'])=='disabled' for w in app.jitter_controls)
    assert app.run_session.plan['points']==preview['points']
    replanned=app.run_session.replan(preview['checkpoints'])
    assert replanned['jitter']==preview['jitter']
    assert replanned['requested_km']==preview['requested_km']
    until(lambda:app.run_state=='finished')
    assert all(str(w['state'])=='normal' for w in app.jitter_controls)
    assert app.progress_value.get()==100
    assert not errors,errors
    print('GUI_JITTER_OK: controls invalidate preview; execution points match; replan retains config; locked during run; completed=100%')
finally:
    app.close()
