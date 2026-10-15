"""Temporary proxy with durable recovery journal and independent guardian."""
import asyncio
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from core import HOST, STATE, atomic_json, token_text

REG_PATH = r'Software\Microsoft\Windows\CurrentVersion\Internet Settings'
NAMES = ('ProxyEnable', 'ProxyServer', 'ProxyOverride', 'AutoConfigURL', 'AutoDetect')
JOURNAL = STATE / 'proxy-backup.json'
LOCK = threading.RLock()


def command(*args):
    if getattr(sys, 'frozen', False):
        return [sys.executable, *map(str, args)]
    return [sys.executable, str(Path(__file__).with_name('app.py')), *map(str, args)]


class Registry:
    def read(self, name):
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH) as key:
            try:
                value, kind = winreg.QueryValueEx(key, name)
                return {'exists': True, 'value': value, 'type': kind}
            except FileNotFoundError:
                return {'exists': False}

    def write(self, name, state):
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if state['exists']:
                winreg.SetValueEx(key, name, 0, state['type'], state['value'])
            else:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass

    def notify(self):
        api = ctypes.WinDLL('wininet', use_last_error=True)
        api.InternetSetOptionW(None, 39, None, 0)
        api.InternetSetOptionW(None, 37, None, 0)


class ProxyLease:
    def __init__(self, registry=None, journal=JOURNAL):
        self.registry = registry or Registry()
        self.journal = Path(journal)

    def begin(self, port):
        with LOCK:
            if self.journal.exists():
                raise RuntimeError('存在未恢复代理，请先恢复')
            backup = {name: self.registry.read(name) for name in NAMES}
            atomic_json(self.journal, {'pid': os.getpid(), 'values': backup})
            try:
                for name, value, kind in [('ProxyEnable', 1, 4), ('ProxyServer', f'127.0.0.1:{port}', 1),
                                          ('ProxyOverride', '<local>', 1), ('AutoDetect', 0, 4)]:
                    self.registry.write(name, {'exists': True, 'value': value, 'type': kind})
                self.registry.write('AutoConfigURL', {'exists': False})
                self.registry.notify()
            except Exception:
                self.restore()
                raise

    def restore(self):
        with LOCK:
            if not self.journal.exists():
                return
            backup = json.loads(self.journal.read_text(encoding='utf-8'))
            for name, state in backup['values'].items():
                self.registry.write(name, state)
            self.registry.notify()
            self.journal.unlink(missing_ok=True)


def guardian(pid, journal):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x100000, False, int(pid))
    if handle:
        kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
        kernel.CloseHandle(handle)
    ProxyLease(journal=journal).restore()


def install_cert(path):
    # UAC elevation is confined to certutil; the application stays in the user's session.
    from ctypes import wintypes
    class SHELLEXECUTEINFO(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('fMask', wintypes.ULONG), ('hwnd', wintypes.HWND),
                    ('lpVerb', wintypes.LPCWSTR), ('lpFile', wintypes.LPCWSTR), ('lpParameters', wintypes.LPCWSTR),
                    ('lpDirectory', wintypes.LPCWSTR), ('nShow', ctypes.c_int), ('hInstApp', wintypes.HINSTANCE),
                    ('lpIDList', ctypes.c_void_p), ('lpClass', wintypes.LPCWSTR), ('hkeyClass', wintypes.HKEY),
                    ('dwHotKey', wintypes.DWORD), ('hIcon', wintypes.HANDLE), ('hProcess', wintypes.HANDLE)]
    info = SHELLEXECUTEINFO()
    info.cbSize, info.fMask, info.lpVerb = ctypes.sizeof(info), 0x40, 'runas'
    info.lpFile = str(Path(os.environ['SystemRoot']) / 'System32' / 'certutil.exe')
    info.lpParameters = subprocess.list2cmdline(['-addstore', '-f', 'Root', str(path)])
    info.nShow = 0
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        raise RuntimeError('证书安装已取消或启动失败')
    kernel = ctypes.WinDLL('kernel32')
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
    code = wintypes.DWORD()
    kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    kernel.CloseHandle(info.hProcess)
    if code.value:
        raise RuntimeError('证书安装失败，退出码 ' + str(code.value))


def extract_token(host, header):
    if host.lower().rstrip('.') != HOST or not header or not header.lower().startswith('bearer '):
        return None
    try:
        return token_text(header)
    except ValueError:
        return None


class Capture:
    def __init__(self, emit, timeout=180):
        self.emit, self.timeout = emit, timeout
        self.cancel = threading.Event()
        self.thread = None
        self.master = None
        self.lease = ProxyLease()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.cancel.clear()
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def stop(self):
        self.cancel.set()

    def _worker(self):
        try:
            asyncio.run(self._run())
        except Exception as exc:
            # Do not expose requests, headers or credentials in error messages.
            self.emit('error', '抓取失败：' + type(exc).__name__ + '；请检查端口、证书或手动填写')
        finally:
            try:
                self.lease.restore()
                self.emit('capture_end', '抓取结束，原有系统代理已恢复')
            except Exception:
                self.emit('error', '代理恢复未完成，请点击恢复代理；备份日志已保留')

    async def _run(self):
        from mitmproxy.options import Options
        from mitmproxy.tools.dump import DumpMaster
        owner = self
        captured = []
        ready = asyncio.Event()
        class Listener:
            def request(self, flow):
                token = extract_token(flow.request.host, flow.request.headers.get('Authorization'))
                if token and not captured:
                    captured.append(token)
                    owner.cancel.set()

            def running(self):
                ready.set()
                owner.emit('proxy_ready', None)

        confdir = STATE / 'mitmproxy'
        confdir.mkdir(parents=True, exist_ok=True)
        options = Options(listen_host='127.0.0.1', listen_port=8080, confdir=str(confdir),
                          allow_hosts=[r'^campusrun\.mzwu\.edu\.cn(?::\d+)?$'])
        self.master = DumpMaster(options, with_termlog=False, with_dumper=False)
        self.master.addons.add(Listener())
        task = asyncio.create_task(self.master.run())
        try:
            cert = confdir / 'mitmproxy-ca-cert.cer'
            for _ in range(150):
                if task.done():
                    await task
                    raise RuntimeError('代理启动失败')
                if cert.exists() and ready.is_set():
                    break
                if self.cancel.is_set():
                    return
                await asyncio.sleep(0.1)
            if not cert.exists() or not ready.is_set():
                raise RuntimeError('证书生成超时')
            self.emit('status', '正在申请安装 mitmproxy 根证书，请处理 Windows 提示')
            await asyncio.to_thread(install_cert, cert)
            if self.cancel.is_set():
                return
            # Guardian starts before any registry modifications.
            # A one-file guardian must have its own extraction directory so it
            # can restore the proxy after the UI process exits unexpectedly.
            env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1')
            subprocess.Popen(command('--guardian', os.getpid(), JOURNAL), creationflags=0x08000000, env=env)
            self.lease.begin(8080)
            self.emit('capture_waiting', {'timeout': self.timeout})
            self.emit('status', '请打开 Windows 微信电脑版中的小程序，进入成绩页（180 秒内）')
            deadline = time.monotonic() + self.timeout
            while not self.cancel.is_set() and time.monotonic() < deadline:
                if task.done():
                    await task
                    raise RuntimeError('代理提前结束')
                await asyncio.sleep(0.15)
            self.lease.restore()
            if captured:
                self.emit('token', captured[0])
            elif not self.cancel.is_set():
                self.emit('status', '抓取超时，请重试或手动填写 tasktoken')
        finally:
            self.master.shutdown()
            await task
