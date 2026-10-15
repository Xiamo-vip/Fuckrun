"""Run the backed-up renderer against the isolated test HWND/HTML only."""
from pathlib import Path
import importlib.util
import sys
import os
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
sys.path.insert(0,str(BASE/'.vendor'))
old_root=Path(os.environ.get('GHOSTRUNNER_OLD_HOST_DIR') or BASE/'evidence/v3')
spec=importlib.util.spec_from_file_location('old_renderer',old_root/'map_view.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
module.run_embedded(sys.argv[1],sys.argv[2],input_probe=True)
