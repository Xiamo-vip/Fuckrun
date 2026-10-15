"""Validate WebView2 HWND reparenting using an offline HTML fixture."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import time
import tkinter as tk
import json

root=tk.Tk()
root.title('GhostRunner 内嵌地图离线验证')
root.geometry('800x500')
frame=tk.Frame(root)
frame.pack(fill='both',expand=True)
root.update()
base=Path(__file__).resolve().parents[1]
html=base/'evidence'/'map-fixture.html'
html.with_suffix('.ready').unlink(missing_ok=True)
html.with_suffix('.interaction.json').unlink(missing_ok=True)
if '--input' in sys.argv:
    content='''<html><head><title>OFFLINE_EMBED_OK</title><style>html,body,#drag{width:100%;height:100%;margin:0;background:#edf5ff}#drag{touch-action:none}</style></head><body><div id="drag">Drag test</div><script>window.INPUT_RESULT={downs:0,moves:0,ups:0,delta:0,wheels:0};let down=false,last=0;const area=document.getElementById('drag');area.addEventListener('pointerdown',e=>{down=true;last=e.clientX;INPUT_RESULT.downs++;area.setPointerCapture(e.pointerId)});area.addEventListener('pointermove',e=>{if(down){INPUT_RESULT.moves++;INPUT_RESULT.delta+=e.clientX-last;last=e.clientX}});area.addEventListener('pointerup',e=>{down=false;INPUT_RESULT.ups++});area.addEventListener('wheel',e=>{INPUT_RESULT.wheels++});</script></body></html>'''
elif '--render' in sys.argv:
    sys.path.insert(0,str(base))
    from map_view import map_html
    stub="""window.TMap={LatLng:class{constructor(a,b){this.a=a;this.b=b;}},
    Map:class{constructor(){document.getElementById('map').style.background='#edf5ff';}fitBounds(b){}on(){}},
    PolylineStyle:class{},MultiPolyline:class{},MarkerStyle:class{},MultiMarker:class{},
    LatLngBounds:class{constructor(sw,ne){if(!sw||!ne)throw Error('sw/ne required');}extend(){}}};"""
    content=map_html('SYNTHETIC_KEY',[(25,118),(25.001,118.001)],
                     [{'id':1,'latitude':25,'longitude':118}])
    content=content.replace('<script>window.GHOSTRUNNER_PLAN','<script>'+stub+'window.GHOSTRUNNER_PLAN')
    content=content.replace('GhostRunner 路线地图','OFFLINE_EMBED_OK')
else:
    content='<html><head><title>OFFLINE_EMBED_OK</title></head><body>WebView2 offline fixture</body></html>'
html.write_text(content,encoding='utf-8')
log=(base/'evidence'/'map-smoke.log').open('w',encoding='utf-8')
program=[os.environ.get('GHOSTRUNNER_PACKAGED_EXE',str(base/'dist-1.0'/'GhostRunner.exe'))] if '--packaged' in sys.argv else [sys.executable,str(base/'app.py')]
extra=['--map-input-probe'] if '--input' in sys.argv else []
args=[*program,'--map',str(frame.winfo_id()),str(html),*extra]
if '--old-host' in sys.argv:args=[sys.executable,str(base/'tests/old_host.py'),str(frame.winfo_id()),str(html)]
child=subprocess.Popen(args,stdout=log,stderr=log,creationflags=0x08000000)
user=ctypes.WinDLL('user32')
user.GetParent.argtypes=[ctypes.c_void_p]
user.GetParent.restype=ctypes.c_void_p
user.EnumChildWindows.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p]
callback_type=ctypes.WINFUNCTYPE(ctypes.c_int,ctypes.c_void_p,ctypes.c_void_p)
embedded=[]
class RECT(ctypes.Structure):
    _fields_=[(n,ctypes.c_long) for n in ('left','top','right','bottom')]
user.GetWindowRect.argtypes=[ctypes.c_void_p,ctypes.c_void_p]
user.IsWindowVisible.argtypes=[ctypes.c_void_p]
def rect_of(hwnd):
    r=RECT();assert user.GetWindowRect(hwnd,ctypes.byref(r))
    return (r.left,r.top,r.right,r.bottom)
initial_rect=None
def callback(hwnd,param):
    if user.GetParent(hwnd)==frame.winfo_id():embedded.append(hwnd)
    return 1
callback_ref=callback_type(callback)
deadline=time.monotonic()+45
try:
    while time.monotonic()<deadline and child.poll() is None:
        root.update()
        user.EnumChildWindows(frame.winfo_id(),callback_ref,None)
        if embedded and html.with_suffix('.ready').exists():
            state=json.loads(html.with_suffix('.ready').read_text(encoding='utf-8'))
            if not state.get('ready'):
                time.sleep(.05)
                continue
            assert state['ready']=='complete' and state['title']=='OFFLINE_EMBED_OK',state
            assert state['origin'].startswith('http://127.0.0.1:'),state
            if initial_rect is None:initial_rect=rect_of(state['hwnd'])
            if '--render' in sys.argv:
                assert state['map_state']['state']=='ready',state
            if '--input' in sys.argv:
                result_path=html.with_suffix('.interaction.json')
                if not result_path.exists():
                    time.sleep(.05)
                    continue
                result=json.loads(result_path.read_text(encoding='utf-8'))
                assert result['downs']==1 and result['ups']==1 and result['moves']>=5 and result['delta']>=180 and result['wheels']>=1,result
                after_rect=rect_of(state['hwnd'])
                if '--old-host' in sys.argv:
                    assert after_rect!=initial_rect,(initial_rect,after_rect)
                    print('BASELINE_WINDOW_MOVED: map drag moved native child; resize would reset its position')
                    break
                assert after_rect==initial_rect,('native map moved during browser drag',initial_rect,after_rect)
                assert user.IsWindowVisible(state['hwnd'])
                for _ in range(10):root.update();time.sleep(.05)
                assert rect_of(state['hwnd'])==initial_rect
                print('MAP_VISIBILITY_OK: native HWND rect unchanged and visible after drag; no resize performed')
                print('MAP_INPUT_OK: drag delta >= 180px; press/move/release and wheel received; resize polling active')
            print('EMBEDDED_MAP_SMOKE_OK: WebView2 HWND parent is Tkinter frame; offline HTML JavaScript executed')
            break
        time.sleep(.1)
    else:
        raise RuntimeError('WebView2 embedding failed; see evidence/map-smoke.log')
finally:
    root.destroy()
    if child.poll() is None:
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # One-file EXEs have a bootloader parent and a GUI child. Clean
            # up the owned process tree, not just its bootloader parent.
            if os.name=='nt':
                subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],capture_output=True,timeout=15)
            else:child.terminate()
            child.wait(timeout=5)
    log.close()
