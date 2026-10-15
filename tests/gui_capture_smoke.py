"""Offline Tkinter capture instructions; no proxy or certificate changes."""
from pathlib import Path
import os,sys,time
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
os.environ.setdefault('GHOSTRUNNER_STATE_DIR',str(BASE/'evidence/capture-page-state'))
import app as module
created=[]
class Thread:
    alive=False
    def is_alive(self):return self.alive
class FakeCapture:
    def __init__(self,emit):self.emit=emit;self.thread=Thread();created.append(self)
    def start(self):self.thread.alive=True;self.emit('capture_waiting',dict(timeout=180))
    def stop(self):self.thread.alive=False;self.emit('capture_end','抓取结束，原有系统代理已恢复')
module.Capture=FakeCapture
module.Application.first_launch=lambda self:None
module.ProxyLease=lambda:type('Lease',(),{'restore':lambda self:None})()
a=module.Application(demo=True)
a.demo=False
a.refresh=lambda:None
a.dialog.askokcancel=lambda *x,**y:True
errors=[];a.dialog.showerror=lambda *x,**y:errors.append(x)
def until(test):
    end=time.monotonic()+5
    while time.monotonic()<end:
        a.root.update()
        if test():return
        time.sleep(.02)
    raise AssertionError(a.capture_status.get())
try:
    assert str(a.capture_tab) not in a.tabs.tabs()
    a.start_capture()
    assert a.tabs.select()==str(a.capture_tab)
    assert '微信电脑版' in a.capture_title.get()
    until(lambda:a.capture_phase=='waiting')
    assert '抓取已开始' in a.capture_title.get()
    assert '180' in a.capture_remaining.get()
    a.start_capture();assert len(created)==1
    a.capture_deadline=time.monotonic()+10;a.capture_tick()
    assert '剩余' in a.capture_remaining.get()
    a.emit('token','OFFLINE-CAPTURE-TOKEN');a.capture.stop()
    until(lambda:not a.capture_ui_active)
    assert a.capture_phase=='success'
    assert '抓取成功' in a.capture_title.get()
    assert module.Settings(a.settings.path).data['tasktoken']=='OFFLINE-CAPTURE-TOKEN'
    assert 'OFFLINE-CAPTURE-TOKEN' not in a.capture_status.get()
    assert str(a.capture_results['state'])=='normal'
    a.start_capture();until(lambda:a.capture_phase=='waiting')
    a.emit('status','抓取超时，请重试或手动填写 tasktoken');a.capture.stop()
    until(lambda:not a.capture_ui_active)
    assert a.capture_phase=='timeout'
    assert '超时' in a.capture_title.get()
    a.start_capture();until(lambda:a.capture_phase=='waiting')
    a.stop_capture();until(lambda:not a.capture_ui_active)
    assert a.capture_phase=='ended'
    assert str(a.capture_cancel['state'])=='disabled'
    assert str(a.capture_retry['state'])=='normal'
    assert not errors,errors
    print('CAPTURE_PAGE_OK: instructions visible on start; readiness/countdown; success saved; timeout/cancel; no token displayed')
finally:a.close()
