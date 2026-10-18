$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:PYTHONPATH = (Join-Path $PSScriptRoot '.vendor')
python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
python -m PyInstaller --noconfirm --windowed --onefile --name GhostRunner --distpath dist-1.0.1 --version-file version_info.txt --paths .vendor --runtime-hook 'packaging/pyi_rth_qt_icu.py' --add-data 'map_runtime.js;.' --add-data 'ui;ui' --add-data 'third_party/material-components-pyside;third_party/material-components-pyside' --collect-data mitmproxy --hidden-import mitmproxy_rs --hidden-import PySide6.QtWebEngineQuick --hidden-import PySide6.QtQuickControls2 --hidden-import stylemanager app.py
if ($LASTEXITCODE -ne 0) { throw 'Portable build failed' }
python -c "import subprocess,sys; p=subprocess.run(['dist-1.0.1/GhostRunner.exe','--smoke-test'],timeout=120); sys.exit(p.returncode)"
if ($LASTEXITCODE -ne 0) { throw 'Packaged Material UI smoke test failed' }
Write-Output 'BUILD_OK: dist-1.0.1/GhostRunner.exe (Material You, portable, no installer)'
