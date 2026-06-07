import subprocess, sys
result = subprocess.run([sys.executable, 'peek_fitness_baseline_quick_context.py'], 
                       capture_output=True, text=True, timeout=30)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr[:500])
