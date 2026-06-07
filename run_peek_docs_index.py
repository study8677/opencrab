import subprocess
result = subprocess.run(['python', 'peek_docs_index.py'], capture_output=True, text=True)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)
