"""Capture only this app's real Tk windows; annotations are rendered as Tk labels before capture.
All data and map drawing are offline demonstration fixtures, not real Tencent tiles.
"""
import ctypes,os,sys,time
from ctypes import wintypes
from pathlib import Path
from PIL import Image
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE))
os.environ['GHOSTRUNNER_STATE_DIR']=str(BASE/'evidence/screenshots-state')
import app as module
module.Application.first_launch=lambda self:self.show_demo()
a=module.Application(demo=True)
a.root.geometry('1120x900')
a.dialog.askokcancel=lambda *x,**y:True
errors=[];a.dialog.showerror=lambda *x,**y:errors.append(x)
marks=[]
def pump(seconds=.3):
    end=time.monotonic()+seconds
    while time.monotonic()<end:a.root.update();time.sleep(.02)
def until(test):
    end=time.monotonic()+20
    while time.monotonic()<end:
        a.root.update()
        if test():return
        time.sleep(.02)
    raise AssertionError(a.status.get())
def mark(widget,text):
    a.root.update()
    label=a.tk.Label(a.root,text=text,bg='#174ebf',fg='white',font=('Microsoft YaHei UI',12,'bold'),padx=5,pady=2)
    x=widget.winfo_rootx()-a.root.winfo_rootx()
    y=widget.winfo_rooty()-a.root.winfo_rooty()
    label.place(x=max(2,x-24),y=max(2,y-4));marks.append(label)
def clear():
    for label in marks:label.destroy()
    marks.clear()
def capture(name):
    pump()
    u=ctypes.WinDLL('user32',use_last_error=True);g=ctypes.WinDLL('gdi32',use_last_error=True)
    u.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT];u.GetAncestor.restype=wintypes.HWND
    u.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    u.GetDC.argtypes=[wintypes.HWND];u.GetDC.restype=wintypes.HDC
    u.ReleaseDC.argtypes=[wintypes.HWND,wintypes.HDC]
    u.PrintWindow.argtypes=[wintypes.HWND,wintypes.HDC,wintypes.UINT]
    g.CreateCompatibleDC.argtypes=[wintypes.HDC];g.CreateCompatibleDC.restype=wintypes.HDC
    g.CreateCompatibleBitmap.argtypes=[wintypes.HDC,ctypes.c_int,ctypes.c_int];g.CreateCompatibleBitmap.restype=wintypes.HBITMAP
    g.SelectObject.argtypes=[wintypes.HDC,wintypes.HGDIOBJ];g.SelectObject.restype=wintypes.HGDIOBJ
    g.DeleteObject.argtypes=[wintypes.HGDIOBJ];g.DeleteDC.argtypes=[wintypes.HDC]
    class HEADER(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('width',wintypes.LONG),('height',wintypes.LONG),('planes',wintypes.WORD),('bits',wintypes.WORD),('compression',wintypes.DWORD),('image_size',wintypes.DWORD),('x',wintypes.LONG),('y',wintypes.LONG),('colors',wintypes.DWORD),('important',wintypes.DWORD)]
    class INFO(ctypes.Structure):_fields_=[('header',HEADER),('colors',wintypes.DWORD*3)]
    g.GetDIBits.argtypes=[wintypes.HDC,wintypes.HBITMAP,wintypes.UINT,wintypes.UINT,ctypes.c_void_p,ctypes.POINTER(INFO),wintypes.UINT]
    hwnd=u.GetAncestor(a.root.winfo_id(),2);rect=wintypes.RECT();assert u.GetWindowRect(hwnd,ctypes.byref(rect))
    w,h=rect.right-rect.left,rect.bottom-rect.top
    dc=u.GetDC(hwnd);mem=g.CreateCompatibleDC(dc);bitmap=g.CreateCompatibleBitmap(dc,w,h);old=g.SelectObject(mem,bitmap)
    try:
        assert u.PrintWindow(hwnd,mem,2)
        g.SelectObject(mem,old)
        info=INFO();info.header=HEADER(ctypes.sizeof(HEADER),w,-h,1,32,0,w*h*4,0,0,0,0)
        pixels=ctypes.create_string_buffer(w*h*4)
        assert g.GetDIBits(mem,bitmap,0,h,pixels,ctypes.byref(info),0)==h
        pic=Image.frombuffer('RGB',(w,h),pixels.raw,'raw','BGRX',0,1)
        pic.save(BASE/'docs/screenshots'/name)
    finally:g.DeleteObject(bitmap);g.DeleteDC(mem);u.ReleaseDC(hwnd,dc)

def draw_map():
    a.map_hint.place_forget()
    canvas=a.tk.Canvas(a.map_frame,bg='#e9f1eb',highlightthickness=0,width=1,height=1)
    canvas.pack(fill='both',expand=True);a.root.update()
    pts=a.route['points'];lats=[p[0] for p in pts];lons=[p[1] for p in pts]
    w,h=canvas.winfo_width(),canvas.winfo_height()
    def xy(lat,lon):return (40+(lon-min(lons))/max(1e-9,max(lons)-min(lons))*(w-80),30+(max(lats)-lat)/max(1e-9,max(lats)-min(lats))*(h-80))
    for x in range(0,w,60):canvas.create_line(x,0,x,h,fill='#d4dfd7')
    for y in range(0,h,60):canvas.create_line(0,y,w,y,fill='#d4dfd7')
    canvas.create_line(*[v for p in pts for v in xy(*p)],fill='#2673de',width=3)
    for cp in a.route['checkpoints']:
        x,y=xy(cp['latitude'],cp['longitude']);canvas.create_oval(x-7,y-7,x+7,y+7,fill='#e55151',outline='white',width=2)
    canvas.create_text(w/2,h-18,text='离线路线示意（非腾讯在线底图）',fill='#465b4c',font=('Microsoft YaHei UI',11))
a.load_map=lambda:None
try:
    pump()
    a.show_capture_page();a.capture_title.set('抓取已开始，请立即打开小程序！')
    a.capture_status.set('请在 Windows 微信电脑版打开校园跑步小程序，进入成绩页或刷新页面。')
    a.capture_remaining.set('剩余 180 秒 · 等待小程序请求（离线截图演示）')
    a.capture_cancel.configure(state='normal')
    for widget in a.capture_tab.winfo_children():
        if 'textvariable' in widget.keys() and str(widget.cget('textvariable'))==str(a.capture_title):mark(widget,'①')
    mark(a.capture_cancel,'③');mark(a.capture_progress,'②')
    capture('01-capture.png');clear()
    a.enter_running();until(lambda:a.route is not None and not a.planning)
    draw_map();mark(a.km_entry,'①');mark(a.jitter_controls[0],'②');mark(a.replan_button,'③');mark(a.execute_button,'④')
    capture('02-route.png');clear()
    a.execute_run();until(lambda:a.run_state=='finished')
    mark(a.execution_progress,'①');mark(a.request_tree,'②');mark(a.execution_retry,'③');mark(a.execution_stop,'④')
    capture('03-execution.png');clear()
    assert not errors,errors
    for name in ('01-capture.png','02-route.png','03-execution.png'):
        with Image.open(BASE/'docs/screenshots'/name) as im:im.verify()
    print('SCREENSHOTS_OK: three real Tk window captures with rendered numbered labels; offline demo only')
finally:a.close()
