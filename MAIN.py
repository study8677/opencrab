#!/usr/bin/env python3
"""执行最终验证"""
import subprocess
import sys

def main():
    files = [
        "canary_75_evolution.py",
        "go_canary_75.py",
        "check_crab.py",
        "execute_canary_75.py",
        "canary_75.py",
        "verify_all.py",
        "do_canary_readpack_brainonly_patch.py",
        "fitness_status.py",
        "check_fitness_json.py",
        "peek_weakest.py",
        "run_now.py",
        "run_canary_evolution.py",
    ]
    
    print("=== 语法检查 ===")
    import py_compile
    for f in files:
        try:
            py_compile.compile(f, doraise=True)
            print(f"OK: {f}")
        except Exception as e:
            print(f"FAIL: {f} - {e}")
            return 1
    
    print("\n=== import crab ===")
    try:
        import crab
        print(f"OK: crab from {crab.__file__}")
    except Exception as e:
        print(f"FAIL: {e}")
        return 1
    
    print("\n=== verify_all ===")
    result = subprocess.run(["python", "verify_all.py"], capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print("verify_all failed")
        return 1
    
    print("\n=== ALL DONE ===")
    return 0

if __name__ == "__main__":
    sys.exit(main())
