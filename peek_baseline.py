import subprocess, json

# Run the fitness baseline
result = subprocess.run(
    ["python", "run_fitness_baseline.py"],
    capture_output=True, text=True
)
print("STDOUT:", result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout)
print("STDERR:", result.stderr[-1000:] if len(result.stderr) > 1000 else result.stderr)
