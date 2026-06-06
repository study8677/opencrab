import subprocess
result = subprocess.run(['python3', 'peeking_showcase.py'], capture_output=True, text=True)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)
