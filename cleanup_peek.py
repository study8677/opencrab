import subprocess
result = subprocess.run(["rm", "-f", "temp_peek_autopsy.py", "crab_autopsy_peek.py", "fitness_peek.py", "run_peek.py"], capture_output=True, text=True)
print(result.stdout, result.stderr)
