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
import shutil
from datetime import datetime, timedelta, timezone
from core import HOST, STATE, atomic_json, token_text

REG_PATH = r'Software\Microsoft\Windows\CurrentVersion\Internet Settings'
NAMES = ('ProxyEnable', 'ProxyServer', 'ProxyOverride', 'AutoConfigURL', 'AutoDetect')
JOURNAL = STATE / 'proxy-backup.json'
LOCK = threading.RLock()
CERT_DIR = STATE / 'mitmproxy'
CERT_FILE = CERT_DIR / 'mitmproxy-ca-cert.cer'


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


def certificate_info(path):
    """Validate the generated CA and return its Windows SHA-1 thumbprint."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    path = Path(path)
    data = path.read_bytes()
    # mitmproxy writes ``mitmproxy-ca-cert.cer`` as PEM even though the .cer
    # extension is also commonly used for DER.  Parsing it as DER unconditionally
    # raises ValueError and rotate_invalid_ca then deletes a perfectly valid CA,
    # causing every capture attempt to regenerate and reject the same PEM file.
    if data.lstrip().startswith(b'-----BEGIN CERTIFICATE-----'):
        cert = x509.load_pem_x509_certificate(data)
    else:
        cert = x509.load_der_x509_certificate(data)
    expires = cert.not_valid_after_utc if hasattr(cert, 'not_valid_after_utc') else cert.not_valid_after.replace(tzinfo=timezone.utc)
    if expires <= datetime.now(timezone.utc) + timedelta(days=7):
        raise ValueError('mitmproxy 根证书已过期或即将过期')
    if not cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
        raise ValueError('mitmproxy 证书不是有效根 CA')
    return cert.fingerprint(hashes.SHA1()).hex().upper(), expires


def certificate_trusted(thumbprint, user=True):
    args = [str(Path(os.environ['SystemRoot']) / 'System32' / 'certutil.exe')]
    if user:
        args.append('-user')
    args.extend(['-store', 'Root', thumbprint])
    result = subprocess.run(args, capture_output=True, creationflags=0x08000000, timeout=20)
    return result.returncode == 0


def certificate_status(confdir=CERT_DIR, trust_checker=certificate_trusted):
    """Return a read-only diagnosis without changing proxy or trust settings."""
    cert = Path(confdir) / 'mitmproxy-ca-cert.cer'
    if not cert.exists():
        return {'ok': False, 'state': 'missing', 'message': '未找到 mitmproxy 根证书，请点击“安装证书”。'}
    try:
        thumbprint, expires = certificate_info(cert)
    except (OSError, ValueError) as exc:
        return {'ok': False, 'state': 'invalid', 'message': f'证书文件无效：{exc}。请点击“一键修复”。'}
    user = trust_checker(thumbprint, user=True)
    machine = trust_checker(thumbprint, user=False)
    if not (user or machine):
        return {'ok': False, 'state': 'untrusted', 'thumbprint': thumbprint,
                'expires': expires.isoformat(), 'message': '证书文件有效，但 Windows 尚未信任；请点击“安装证书”。'}
    store = '当前用户' if user else '本地计算机'
    return {'ok': True, 'state': 'trusted', 'thumbprint': thumbprint,
            'expires': expires.isoformat(), 'store': store,
            'message': f'证书有效并已受信任（{store}，指纹 …{thumbprint[-8:]}）。'}


def ensure_certificate(confdir=CERT_DIR):
    """Create the mitmproxy CA files without starting a proxy listener."""
    confdir = Path(confdir)
    confdir.mkdir(parents=True, exist_ok=True)
    cert = confdir / 'mitmproxy-ca-cert.cer'
    if cert.exists():
        certificate_info(cert)
        return cert
    from mitmproxy.certs import CertStore
    CertStore.from_store(confdir, 'mitmproxy', 2048)
    if not cert.exists():
        raise RuntimeError('mitmproxy 未生成根证书文件')
    certificate_info(cert)
    return cert


def install_certificate(confdir=CERT_DIR):
    cert = ensure_certificate(confdir)
    result = install_cert(cert)
    status = certificate_status(confdir)
    if not status['ok']:
        raise RuntimeError(status['message'])
    return status | {'installed_store': result['store']}


def repair_certificate(confdir=CERT_DIR, backup_root=None):
    """Back up the CA set, regenerate it, install it, and verify exact trust."""
    confdir = Path(confdir)
    backup_root = Path(backup_root or (STATE / 'certificate-backups'))
    backup = backup_root / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup.mkdir(parents=True, exist_ok=False)
    for path in confdir.glob('mitmproxy-ca*') if confdir.exists() else ():
        if path.is_file():
            shutil.copy2(path, backup / path.name)
            path.unlink()
    try:
        status = install_certificate(confdir)
    except Exception:
        for path in confdir.glob('mitmproxy-ca*') if confdir.exists() else ():
            if path.is_file():
                path.unlink()
        for path in backup.iterdir():
            shutil.copy2(path, confdir / path.name)
        raise
    return status | {'backup': str(backup)}


def capture_error_message(exc):
    """Translate known local setup failures without exposing request data."""
    if isinstance(exc, OSError) and 10048 in (getattr(exc, 'winerror', None), getattr(exc, 'errno', None)):
        return '抓取失败：端口 8080 已被占用，请关闭占用程序后重试。'
    message = str(exc).strip()
    if isinstance(exc, (RuntimeError, ValueError)) and message:
        allowed = ('证书', '根 CA', '代理', '端口', 'mitmproxy')
        if any(word in message for word in allowed):
            return '抓取失败：' + message
    return '抓取失败：' + type(exc).__name__ + '；请先点击“验证证书”，仍失败再点击“一键修复”。'


def _install_machine_cert(path):
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


def install_cert(path):
    """Trust the CA before enabling the system proxy.

    Chromium-based WeChat reads the current-user root store reliably.  Older
    builds may read the machine store, so an elevated machine-store fallback is
    retained.  The proxy is never enabled unless one store verifies the exact
    generated certificate thumbprint.
    """
    thumbprint, expires = certificate_info(path)
    if certificate_trusted(thumbprint, user=True) or certificate_trusted(thumbprint, user=False):
        return {'thumbprint': thumbprint, 'expires': expires.isoformat(), 'store': 'existing'}
    certutil = str(Path(os.environ['SystemRoot']) / 'System32' / 'certutil.exe')
    current = subprocess.run([certutil, '-user', '-addstore', '-f', 'Root', str(path)],
                             capture_output=True, creationflags=0x08000000)
    if current.returncode == 0 and certificate_trusted(thumbprint, user=True):
        return {'thumbprint': thumbprint, 'expires': expires.isoformat(), 'store': 'CurrentUser'}
    _install_machine_cert(path)
    if not certificate_trusted(thumbprint, user=False):
        raise RuntimeError('根证书安装后未通过 Windows 信任验证；系统代理尚未启用')
    return {'thumbprint': thumbprint, 'expires': expires.isoformat(), 'store': 'LocalMachine'}


def rotate_invalid_ca(confdir):
    """Remove only an unusable mitmproxy CA set so mitmproxy can regenerate it."""
    cert = Path(confdir) / 'mitmproxy-ca-cert.cer'
    if not cert.exists():
        return False
    try:
        certificate_info(cert)
        return False
    except Exception:
        for path in Path(confdir).glob('mitmproxy-ca*'):
            if path.is_file():
                path.unlink()
        return True


def extract_token(host, header):
    if host.lower().rstrip('.') != HOST or not header or not header.lower().startswith('bearer '):
        return None
    try:
        return token_text(header)
    except ValueError:
        return None


def proxy_option_values(confdir):
    """Return only options supported by the pinned mitmproxy release."""
    return {'listen_host': '127.0.0.1', 'listen_port': 8080,
            'confdir': str(confdir),
            'allow_hosts': [r'^campusrun\.mzwu\.edu\.cn(?::\d+)?$']}


def proxy_options(confdir, options_type=None):
    """Build options supported by current mitmproxy releases.

    ``connection_strategy`` was removed in mitmproxy 12. Passing it to
    ``Options`` raises ``KeyError`` before the certificate or proxy is ready.
    We use ``update_defer`` so that any option name unknown to the installed
    mitmproxy version is silently deferred instead of raising ``KeyError``.
    """
    if options_type is None:
        from mitmproxy.options import Options
        options_type = Options
    opts = options_type()
    values = proxy_option_values(confdir)
    if hasattr(opts, 'update_defer'):
        opts.update_defer(**values)
    else:
        # Very old mitmproxy without update_defer — try update_known first.
        if hasattr(opts, 'update_known'):
            opts.update_known(**values)
        else:
            opts.update(**values)
    return opts


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
        except KeyError as exc:
            self.emit('error', '抓取失败：mitmproxy 配置项不兼容（' + str(exc) + '）；请升级 mitmproxy 或检查版本')
        except ImportError as exc:
            self.emit('error', '抓取失败：缺少依赖（' + str(exc) + '）；请检查 mitmproxy 及其依赖是否正确安装')
        except Exception as exc:
            # Do not expose requests, headers or credentials in error messages.
            self.emit('error', capture_error_message(exc))
        finally:
            try:
                self.lease.restore()
                self.emit('capture_end', '抓取结束，原有系统代理已恢复')
            except Exception:
                self.emit('error', '代理恢复未完成，请点击恢复代理；备份日志已保留')

    async def _run(self):
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

        confdir = CERT_DIR
        confdir.mkdir(parents=True, exist_ok=True)
        rotated = rotate_invalid_ca(confdir)
        if rotated:
            self.emit('status', '检测到失效的旧证书，正在重新生成；系统代理尚未启用')
        options = proxy_options(confdir)
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
            self.emit('status', '正在验证 mitmproxy 根证书；验证完成前不会修改系统代理')
            cert_status = await asyncio.to_thread(install_cert, cert)
            self.emit('certificate_ready', '根证书已在 Windows '+cert_status['store']+' 信任库验证；现在可以启动抓取')
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
