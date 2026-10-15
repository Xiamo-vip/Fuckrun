"""Compatibility entry point for the current desktop delivery verification."""
from pathlib import Path
import runpy

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).with_name('verify_1_0.py')),run_name='__main__')
