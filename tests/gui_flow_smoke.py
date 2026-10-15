"""Exercise the real Tkinter workflow using only offline demo fixtures."""
from pathlib import Path
import os
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('GHOSTRUNNER_STATE_DIR',str(Path(__file__).resolve().parents[1]/'evidence/gui-flow-state'))
from app import Application

app=Application(demo=True)
app.dialog.askokcancel=lambda *args,**kwargs: True
errors=[]
app.dialog.showerror=lambda *args,**kwargs: errors.append(args)
def pump_until(predicate,timeout=15):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        app.root.update()
        if predicate():return
        time.sleep(.02)
    raise AssertionError('GUI state transition timed out: '+str(app.run_state)+' '+app.status.get())
try:
    assert str(app.map_tab) not in app.tabs.tabs()
    app.enter_running()
    pump_until(lambda:app.route is not None and not app.planning)
    assert app.tabs.select()==str(app.map_tab)
    pump_until(lambda:app.map_embedded,timeout=40)
    assert not app.map_hint.winfo_manager(), 'startup hint still intercepts map input'
    map_pid=app.map_process.pid
    app.tabs.select(app.tabs.tabs()[0]);app.root.update()
    app.tabs.select(app.map_tab);app.root.update()
    assert not app.map_hint.winfo_manager()
    assert app.map_process.pid==map_pid
    first=app.route['points']
    app.plan()
    pump_until(lambda:app.route is not None and not app.planning)
    assert app.route['points']!=first
    app.km_var.set('1.5')
    assert app.route is None
    assert str(app.execute_button['state'])=='disabled'
    app.plan()
    pump_until(lambda:app.route is not None and not app.planning)
    assert app.route['km']==1.5
    app.execute_run()
    assert app.tabs.select()==str(app.execution_tab)
    assert str(app.replan_button['state'])=='disabled'
    current=app.run_session
    app.execute_run()
    assert app.run_session is current
    pump_until(lambda:app.run_state=='finished',timeout=20)
    assert app.progress['value']==100
    assert app.execution_progress['value']==100
    assert app.execution_percent.get()=='100%'
    assert app.tabs.select()==str(app.execution_tab)
    rows=[app.request_tree.item(i,'values') for i in app.request_tree.get_children()]
    assert rows and any(row[2]=='/upload_running_chunk' for row in rows)
    assert all('成功' in row[5] for row in rows),rows
    assert app.request_successes==len(rows) and app.request_failures==0
    assert app.upload_successes>0
    assert not errors,errors
    print('GUI_EXECUTION_OK: separate task page; progress=100%; request rows successful; upload counters correct; task page retained')
finally:
    app.close()
