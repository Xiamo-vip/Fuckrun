"""WebView2 map hosted in a child HWND inside a Tkinter frame."""
import ctypes
import json
import threading
import time
import urllib.parse


class ResizeGuard:
    """Do not disturb mouse capture by resizing an unchanged WebView HWND."""
    def __init__(self):
        self.previous = None

    def changed(self, width, height):
        size = (max(1, width), max(1, height))
        if size == self.previous:
            return False
        self.previous = size
        return True


def map_html(key, points=None, checkpoints=None):
    from pathlib import Path
    data = json.dumps({'key': key, 'points': points or [], 'checkpoints': checkpoints or []},
                      ensure_ascii=False, allow_nan=False).replace('<', '\\u003c')
    runtime = Path(__file__).with_name('map_runtime.js').read_text(encoding='utf-8')
    return ('<!doctype html><html><head><meta charset="utf-8"><meta name="referrer" content="strict-origin-when-cross-origin">'
            '<title>GhostRunner 路线地图</title><style>html,body,#map{height:100%;margin:0;font-family:Segoe UI,Microsoft YaHei,sans-serif}'
            '#status{position:absolute;top:12px;left:12px;max-width:85%;background:white;padding:10px 14px;border-radius:6px;z-index:5;box-shadow:0 2px 12px #0002;pointer-events:none;user-select:none}'
            '</style></head><body><div id="map"></div><div id="status">正在加载腾讯地图 SDK…</div>'
            '<script>window.GHOSTRUNNER_PLAN=' + data + ';\n' + runtime + '</script></body></html>')


def run_embedded(parent, html_path, input_probe=False):
    import webview
    from pathlib import Path
    import http.server
    import secrets
    import os
    from core import atomic_json
    page_path = '/' + secrets.token_urlsafe(20)
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if urllib.parse.urlsplit(self.path).path != page_path:
                self.send_error(404)
                return
            content = Path(html_path).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1',0), Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}{page_path}'
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.SetParent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user.SetParent.restype = ctypes.c_void_p
    user.IsWindow.argtypes = [ctypes.c_void_p]
    user.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user.MoveWindow.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    user.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
    user.GetParent.argtypes = [ctypes.c_void_p]
    user.GetParent.restype = ctypes.c_void_p
    user.SetWindowPos.argtypes = [ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int,ctypes.c_int,
                                 ctypes.c_int,ctypes.c_int,ctypes.c_uint]
    window = webview.create_window('GhostRunner 地图', url=url,
                                   frameless=True, easy_drag=False, width=700, height=450)
    parent = int(parent)
    state_file = Path(html_path).with_suffix('.ready')
    def publish(**values):
        atomic_json(state_file,dict(pid=os.getpid(),parent=parent,**values))
    def attached():
        try:
            from System import Action
            def ui(action):
                window.native.Invoke(Action(action))
            if not window.events.loaded.wait(35):
                raise RuntimeError('WebView2 初始化超时，请重载地图')
            if not user.IsWindow(parent):
                return
            handles = []
            def attach_on_ui():
                # Keep WinForms' own TopLevel state consistent with WS_CHILD.
                # Changing only Win32 styles leaves a top-level Form that can
                # reactivate/reposition itself when the user clicks the map.
                window.native.TopLevel = False
                handle = int(window.native.Handle.ToInt64())
                style = user.GetWindowLongW(handle,-16)
                user.SetWindowLongW(handle,-16,(style | 0x40000000) & ~0x80000000 & ~0x00C00000)
                user.SetParent(handle,parent)
                if user.GetParent(handle)!=parent:
                    raise RuntimeError('WebView2 绑定父窗口失败')
                window.native.Show()
                user.SetWindowPos(handle,None,0,0,700,450,0x0010|0x0020|0x0040)
                handles.append(handle)
            ui(attach_on_ui)
            handle = handles[0]
            class RECT(ctypes.Structure):
                _fields_ = [(n,ctypes.c_long) for n in ('left','top','right','bottom')]
            guard = ResizeGuard()
            def resize():
                rect = RECT()
                user.GetClientRect(parent,ctypes.byref(rect))
                width,height = max(1,rect.right),max(1,rect.bottom)
                if guard.changed(width,height):
                    ui(lambda:user.SetWindowPos(handle,None,0,0,width,height,0x0010|0x0004))
            resize()
            def focus_browser():
                window.native.ActiveControl = window.native.webview
                window.native.webview.Focus()
            ui(focus_browser)
            # Embedded readiness is independent of SDK/key/network readiness.
            # Publish it before evaluate_js so the Tkinter label cannot cover
            # an interactive browser while an SDK download is still pending.
            publish(embedded=True,hwnd=handle,state='embedded')
            publish(embedded=True,hwnd=handle,state='embedded',
                    ready=window.evaluate_js('document.readyState'),
                    title=window.evaluate_js('document.title'),
                    origin=window.evaluate_js('location.origin'),
                    map_state=window.evaluate_js('window.GHOSTRUNNER_MAP_STATE || null'))
            if input_probe:
                threading.Thread(target=run_input_probe,args=(window,ui,Path(html_path)),daemon=True).start()
            last = Path(html_path).read_text(encoding='utf-8')
            while user.IsWindow(parent) and user.IsWindow(handle):
                resize()
                current = Path(html_path).read_text(encoding='utf-8')
                if current != last:
                    window.load_url(url+'?revision='+str(time.time_ns()))
                    last = current
                time.sleep(.15)
            if user.IsWindow(handle):
                window.destroy()
        except Exception as exc:
            publish(embedded=False,state='error',message=str(exc))
            try:
                window.destroy()
            except Exception:
                pass
    window.events.shown += lambda: threading.Thread(target=attached, daemon=True).start()
    try:
        webview.start(gui='edgechromium', debug=False)
    finally:
        server.shutdown()
        server.server_close()


def run_input_probe(window, ui, html_path):
    """Component test: browser-scoped CDP input, never desktop/global input."""
    from core import atomic_json
    def dispatch(params):
        tasks=[]
        ui(lambda:tasks.append(window.native.webview.CoreWebView2.CallDevToolsProtocolMethodAsync(
            'Input.dispatchMouseEvent',json.dumps(params))))
        task=tasks[0]
        deadline=time.monotonic()+5
        while not task.IsCompleted and time.monotonic()<deadline:
            time.sleep(.01)
        if not task.IsCompleted or task.IsFaulted:
            raise RuntimeError('WebView2 input probe failed')
    # Let the first post-reparent layout/compositor frame settle.
    time.sleep(.4)
    dispatch({'type':'mouseMoved','x':160,'y':180,'button':'none','buttons':0})
    dispatch({'type':'mousePressed','x':160,'y':180,'button':'left','buttons':1,'clickCount':1})
    for x in range(180,361,20):
        dispatch({'type':'mouseMoved','x':x,'y':180,'button':'left','buttons':1})
        time.sleep(.08)
    dispatch({'type':'mouseReleased','x':360,'y':180,'button':'left','buttons':0,'clickCount':1})
    dispatch({'type':'mouseWheel','x':360,'y':180,'deltaX':0,'deltaY':120})
    time.sleep(.25)
    atomic_json(html_path.with_suffix('.interaction.json'),window.evaluate_js('window.INPUT_RESULT'))
