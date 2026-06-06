#!/usr/bin/env python3
import subprocess, sys
# 运行验证脚本
r = subprocess.run([sys.executable, "temp_verify_canary_75_weld.py"], capture_output=True, text=True)
print(r.stdout)
print(r.stderr)
sys.exit(r.returncode)
