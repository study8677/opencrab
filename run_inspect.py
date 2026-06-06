import subprocess, sys
r = subprocess.run([sys.executable, 'inspect_showcase.py'], capture_output=True, text=True)
print(r.stdout)
if r.stderr:
    print(r.stderr)
