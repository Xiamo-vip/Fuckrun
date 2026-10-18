import importlib.util
from pathlib import Path
import sys,tempfile
ROOT=Path(__file__).resolve().parents[1]
source=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT
spec=importlib.util.spec_from_file_location('probe_core',source/'core.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
if hasattr(m,'APP_VERSION'):
    assert m.APP_VERSION=='1.0.1'
    with tempfile.TemporaryDirectory() as d:
        s=m.Settings(Path(d)/'config.json')
        assert s.data['tencent_key']==m.DEFAULT_TENCENT_KEY
        assert s.data['tencent_js_key']==m.DEFAULT_TENCENT_KEY
    assert '未来可能无法使用' in m.DEFAULT_KEY_NOTICE
    print('RELEASE_1_0_1_OK: version=1.0.1; default keys populated; expiry notice present')
else:
    print('BASELINE_V7: version=7; default Tencent keys empty; installer-oriented build')
