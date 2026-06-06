#!/usr/bin/env python3
import subprocess
result = subprocess.run(["git", "diff", "--cached", "--stat"], capture_output=True, text=True)
print(result.stdout)
print(result.stderr)
# Check if only journal/ remains
lines = result.stdout.strip().split('\n')
if not lines or lines == ['']:
    print("NO STAGED FILES - .gitignore weld successful, only journal/ left")
else:
    non_journal = [l for l in lines if 'journal/' not in l and 'state/' not in l]
    if non_journal:
        print("WARNING: Non-journal/state files staged:", non_journal)
    else:
        print("OK: Only state/journal entries remain staged")
