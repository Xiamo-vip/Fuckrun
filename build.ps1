$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
$env:PYTHONPATH = (Join-Path $PSScriptRoot '.vendor')
python -m PyInstaller --noconfirm --windowed --onefile --name GhostRunner --distpath dist-1.0 --version-file version_info.txt --paths .vendor --add-data 'map_runtime.js;.' --collect-all mitmproxy --collect-all webview --collect-all pythonnet --collect-all clr_loader --hidden-import mitmproxy_rs app.py
if ($LASTEXITCODE -ne 0) { throw 'Portable build failed' }
python verify_1_0.py
if ($LASTEXITCODE -ne 0) { throw 'Verification failed' }
Write-Output 'BUILD_OK: dist-1.0/GhostRunner.exe (portable, no installer)'
