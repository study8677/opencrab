import subprocess
result = subprocess.run(["python", "showcase_refresher.py"], capture_output=True, text=True)
print("STDOUT:", result.stdout)
print("STDERR:", result.stderr)
print("Return code:", result.returncode)
