import subprocess
result = subprocess.run(["python", "temp_peek_autopsy.py"], capture_output=True, text=True)
print(result.stdout)
print(result.stderr)

result2 = subprocess.run(["python", "crab_autopsy_peek.py"], capture_output=True, text=True)
print(result2.stdout)
print(result2.stderr)

result3 = subprocess.run(["python", "fitness_peek.py"], capture_output=True, text=True)
print(result3.stdout)
print(result3.stderr)
