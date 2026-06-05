#!/usr/bin/env python3
"""一次性脚本：运行 showcase_refresher 刷新 docs/index.html"""
import subprocess
import sys

result = subprocess.run([sys.executable, "-c", """
import showcase_refresher
showcase_refresher.main()
"""], capture_output=True, text=True)

print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)
print("Return code:", result.returncode)
