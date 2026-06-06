#!/usr/bin/env python3
"""临时：验证改动的三个文件语法正确"""
import subprocess, sys

files = ["go_canary_75.py", "do_canary_75_final.py", "canary_75_weld.py"]
ok = True
for f in files:
    r = subprocess.run([sys.executable, "-m", "py_compile", f], capture_output=True, text=True)
    if r.returncode == 0:
        print(f"  py_compile OK: {f}")
    else:
        print(f"  py_compile FAIL: {f}")
        print(r.stderr)
        ok = False
sys.exit(0 if ok else 1)
