"""Probe baseline/restored or modified module without network or GUI."""
import importlib.util
import inspect
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
source=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT
spec=importlib.util.spec_from_file_location('probe_running',source/'running.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
if 'jitter' not in inspect.signature(m.generate_plan).parameters:
    print('BASELINE_NO_JITTER: route points have no configurable jitter')
else:
    cps=[dict(latitude=25.,longitude=118.,radius=10),dict(latitude=25.001,longitude=118.001,radius=10)]
    p=m.generate_plan(cps,'OFFLINE',1,leg=lambda a,b:{'points':[a,b]},jitter=dict(enabled=True,amplitude_m=5,smooth_points=12,seed='42'))
    assert p['points']!=p['base_points']
    assert max(m.distance(a,b) for a,b in zip(p['base_points'],p['points']))<=5.000001
    print('MODIFIED_JITTER_OK: enabled; amplitude<=5m; seed=42; actual distance consistent')
