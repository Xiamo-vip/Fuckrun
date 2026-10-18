"""GhostRunner Windows entry point."""
from __future__ import annotations

import argparse
import ctypes
import os

from proxy_capture import guardian


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--guardian", nargs=2, metavar=("PID", "JOURNAL"))
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--no-update-check", action="store_true")
    args = parser.parse_args()
    if args.guardian:
        guardian(*args.guardian)
        return 0
    if os.name != "nt":
        parser.error("仅支持 Windows")

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    mutex_name = "Local\\GhostRunnerDesktopSmoke" if args.smoke_test else "Local\\GhostRunnerDesktop"
    mutex = kernel.CreateMutexW(None, False, mutex_name)
    if ctypes.get_last_error() == 183:
        ctypes.windll.user32.MessageBoxW(None, "GhostRunner 已在运行。", "GhostRunner", 0)
        return 0
    try:
        from material_app import run

        return run(demo=args.demo, smoke_test=args.smoke_test,
                   check_updates=not args.no_update_check)
    finally:
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(mutex)


if __name__ == "__main__":
    raise SystemExit(main())
