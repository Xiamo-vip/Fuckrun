"""Remove a PATH-provided ICU DLL that can shadow Windows' ICU for Qt 6."""
from pathlib import Path
import sys


root = Path(getattr(sys, "_MEIPASS", ""))
if root.name.startswith("_MEI"):
    for filename in ("icuuc.dll", "icudt78.dll"):
        try:
            (root / filename).unlink(missing_ok=True)
        except OSError:
            pass
