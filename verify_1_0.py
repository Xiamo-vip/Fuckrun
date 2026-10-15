"""Offline portable 1.0 release, docs, screenshots and copy-only rollback verification."""
import difflib,hashlib,os,shutil,subprocess,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
os.chdir(ROOT)
os.environ['GHOSTRUNNER_STATE_DIR']=str(ROOT/'evidence/1.0-verification-state')
os.environ['PYTHONUTF8']='1'
expected={'app.py':'b18ccc142b4c01ded1f590670795ba6a7fc6f65b3c4fe8b2577f1cd6c08f3624',
'core.py':'1dda7f14fa8bc337effc36df73493e9a49701625c30e1d4603258735c4006d2a',
'proxy_capture.py':'eb826aa1b0e85afc59783ad5b4e4ccb9d2946f8c45c2c6167c3c98daa4aed068'}
for name,sha in expected.items():assert hashlib.sha256((ROOT/'evidence/v7'/name).read_bytes()).hexdigest()==sha
artifacts={'MODIFIED_FILE':ROOT/'app.py','DIFF_FILE':ROOT/'DIFF_FILE.patch','VERIFICATION':ROOT/'VERIFICATION.txt','ROLLBACK':ROOT/'ROLLBACK.sh'}
report=['GhostRunner 1.0 portable verification',
'Changed fields/branches: APP_VERSION=1.0; DEFAULT_TENCENT_KEY and DEFAULT_KEY_NOTICE; Settings defaults preserve custom keys; app title and PE version 1.0; onefile portable build; workflow pages gain space; guardian independent extraction environment; concise README, three annotated offline screenshots and DISCLAIMER.',
'Test env GHOSTRUNNER_STATE_DIR='+os.environ['GHOSTRUNNER_STATE_DIR'],
'INITIAL UI CHECK: first isolated-map visibility check failed, then unchanged source/direct and two isolated retests passed. A later copy encountered an EXE lock from orphaned test GUI children: the onefile test harness killed only the bootloader parent. Harness now cleans its owned process tree; old test-only children cleaned. User v7 process left untouched. Initial output retained in evidence/1.0-verification-initial.log. Fresh full suite follows.']
report += [name+': '+str(path) for name,path in artifacts.items()]
report += ['ORIGINAL_SHA256 '+name+' '+sha for name,sha in expected.items()]
diff=[]
for name in ['app.py','core.py','proxy_capture.py','README.md','DISCLAIMER.md','build.ps1','version_info.txt']:
    old=ROOT/'evidence/v7'/name
    before=old.read_text(encoding='utf-8-sig').splitlines(True) if old.exists() else []
    after=(ROOT/name).read_text(encoding='utf-8-sig').splitlines(True)
    diff.extend(difflib.unified_diff(before,after,fromfile='v7/'+name if old.exists() else '/dev/null',tofile='1.0/'+name))
(ROOT/'DIFF_FILE.patch').write_text(''.join(diff),encoding='utf-8')
def check(label,cmd,input_text,cwd=ROOT):
    p=subprocess.run(cmd,cwd=cwd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
    output=p.stdout+p.stderr
    report.extend(['','['+label+']','CWD: '+str(cwd),'COMMAND: '+subprocess.list2cmdline(cmd),'INPUT: '+input_text,'LITERAL OUTPUT:',output.rstrip(),'EXIT: '+str(p.returncode)])
    (ROOT/'evidence'/('1.0-'+label.lower()+'.log')).write_text(output,encoding='utf-8')
    print(label+' EXIT='+str(p.returncode)+' '+output.strip(),flush=True)
    if p.returncode:
        (ROOT/'VERIFICATION.txt').write_text('\n'.join(report),encoding='utf-8');raise SystemExit(p.returncode)
check('BASELINE',[sys.executable,'tests/release_probe.py','evidence/v7'],'preserved v7 core; no version/default Key constants')
check('BASELINE_TESTS',[sys.executable,'-c',"import sys,unittest; sys.path[:0]=['evidence/v7','tests']; r=unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromName('test_desktop')); sys.exit(not r.wasSuccessful())"],'12 release-v7 offline desktop fixtures')
check('MODIFIED',[sys.executable,'tests/release_probe.py'],'fresh temporary config; version 1.0; supplied default Keys and expiry notice')
check('PYTHON',[sys.executable,'-m','unittest','discover','-s','tests','-v'],'51 offline fixtures; no real platform writes')
for label,script,extra in [('CAPTURE','gui_capture_smoke.py',[]),('SESSION','gui_session_smoke.py',[]),('RETRY','gui_execution_error.py',[]),('RETRY_STOP','gui_execution_error.py',['--stop']),('JITTER','gui_jitter_smoke.py',[]),('GUI_FLOW','gui_flow_smoke.py',[])]:
    check(label,[sys.executable,'tests/'+script,*extra],'offline Tkinter fixtures; fake credentials/transport/capture only')
exe=ROOT/'dist-1.0/GhostRunner.exe'
with exe.open('rb') as f:assert f.read(2)==b'MZ'
check('PE_VERSION',['powershell','-NoProfile','-Command',"$v=(Get-Item 'dist-1.0/GhostRunner.exe').VersionInfo; if($v.FileVersion -ne '1.0' -or $v.ProductVersion -ne '1.0'){exit 1}; Write-Output ('FILE_VERSION='+$v.FileVersion+' PRODUCT_VERSION='+$v.ProductVersion)"],'Windows PE version resource')
check('PACKAGED',[str(exe),'--smoke-test'],'single EXE offline UI launch; no installation, Python or companion _internal folder')
copydir=ROOT/'evidence/portable-1.0'
copydir.mkdir(exist_ok=True)
copyexe=copydir/'GhostRunner.exe';shutil.copy2(exe,copyexe)
assert set(p.name for p in copydir.iterdir())=={'GhostRunner.exe'}
check('ISOLATED',[str(copyexe),'--smoke-test'],'directory contains only copied EXE; offline GUI startup',copydir)
os.environ['GHOSTRUNNER_PACKAGED_EXE']=str(copyexe)
check('PORTABLE_MAP',[sys.executable,'tests/map_smoke.py','--packaged','--input'],'isolated single EXE child process; offline WebView2 mouse input; HWND remains visible')
os.environ.pop('GHOSTRUNNER_PACKAGED_EXE',None)
no_journal=ROOT/'evidence/1.0-absent-proxy-journal.json';assert not no_journal.exists()
check('GUARDIAN',[str(copyexe),'--guardian','0',str(no_journal)],'single EXE guardian mode, nonexistent journal; no proxy changes',copydir)
target=ROOT/'evidence/rollback-1.0';target.mkdir(exist_ok=True)
for name in expected:shutil.copy2(ROOT/name,target/name)
check('ROLLBACK',[r'C:\Program Files\Git\bin\bash.exe','-c','chmod +x ROLLBACK.sh && ./ROLLBACK.sh evidence/rollback-1.0'],'independent copies of modified app.py/core.py/proxy_capture.py')
for name,sha in expected.items():
    assert hashlib.sha256((target/name).read_bytes()).hexdigest()==sha
    assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=sha
check('RESTORED',[sys.executable,'tests/release_probe.py',str(target)],'restored v7 core; default Keys empty and no release constant')
report.append('RESTORED STATUS: three v7 hashes match on independent copy; prior defaults restored; current source remains changed.')
report.append('LIVE STATUS: supplied Key stored as default, not validated against Tencent; real WeChat capture, certificate installation and real create/upload/finish not exercised.')
report.append('PORTABLE STATUS: isolated directory contains only GhostRunner.exe; no installer invoked; runtime state/config still stored in user locations.')
report.append('EXE SHA256='+hashlib.sha256(exe.read_bytes()).hexdigest()+' SIZE='+str(exe.stat().st_size))
assets=[ROOT/'docs/screenshots'/name for name in ['01-capture.png','02-route.png','03-execution.png']]
for path in assets:
    data=path.read_bytes();assert data[:8]==b'\x89PNG\r\n\x1a\n';assert len(data)>10000
    report.append('SCREENSHOT '+str(path)+' SHA256='+hashlib.sha256(data).hexdigest())
report.append('SCREENSHOT STATUS: actual application window captures with Tk-rendered number labels, offline demo data and offline route illustration; visually inspected before packaging.')
for path in [ROOT/'README.md',ROOT/'DISCLAIMER.md']:
    assert path.read_text(encoding='utf-8-sig').strip()
(ROOT/'VERIFICATION.txt').write_text('\n'.join(report)+'\n',encoding='utf-8')
portable=ROOT/'dist-1.0/GhostRunner-1.0-Portable.zip'
with zipfile.ZipFile(portable,'w',zipfile.ZIP_DEFLATED) as z:
    z.write(exe,'GhostRunner.exe')
    for path in [ROOT/'README.md',ROOT/'DISCLAIMER.md',*assets]:z.write(path,path.relative_to(ROOT).as_posix())
with zipfile.ZipFile(portable) as z:
    assert z.testzip() is None and 'GhostRunner.exe' in z.namelist()
    assert not any('Setup' in name or '_internal' in name for name in z.namelist())
include=set()
for pattern in ['*.py','*.js','*.ps1','requirements.txt','README.md','DISCLAIMER.md','version_info.txt','VERIFICATION.txt','DIFF_FILE.patch','ROLLBACK.sh','tests/*.py','tests/*.js','docs/screenshots/*.png']:
    include.update(ROOT.glob(pattern))
include={p for p in include if not p.name.startswith('verify_') and p.name!='installer.py'}
include.update([ROOT/'verify_1_0.py',ROOT/'verify_delivery.py',ROOT/'evidence/v7/test_desktop.py'])
include.update(ROOT/'evidence/v7'/name for name in expected)
source=ROOT/'dist-1.0/GhostRunner-1.0-Source.zip'
with zipfile.ZipFile(source,'w',zipfile.ZIP_DEFLATED) as z:
    for path in sorted(include):z.write(path,'GhostRunnerDesktop/'+path.relative_to(ROOT).as_posix())
with zipfile.ZipFile(source) as z:assert z.testzip() is None
for path in artifacts.values():
    with path.open('rb') as f:assert f.read(1)
print('DELIVERY_1_0_OK: standalone EXE, portable ZIP, source ZIP, docs/screenshots/disclaimer and copy-only rollback verified',flush=True)
