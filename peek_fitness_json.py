#!/usr/bin/env python3
"""peek_fitness_json: Read and display fitness.json if it exists."""
import json
import os

def main():
    # Try common locations
    paths = [
        'fitness.json',
        'fitness/fitness.json',
        'results/fitness.json',
        '.fitness.json',
        'data/fitness.json',
    ]
    for p in paths:
        if os.path.exists(p):
            with open(p) as f:
                data = json.load(f)
            print(f"=== {p} ===")
            print(json.dumps(data, indent=2))
            return

    # If not found, try to generate via check_fitness_json
    print("fitness.json not found in common locations.")
    print("Checking if we can run evaluation to generate it...")
    
    # Try to run arena/boundaryeval/regression/canary evaluation
    try:
        from arena import Arena
        arena = Arena()
        scores = arena.run_all()
        print("=== Arena Scores ===")
        print(json.dumps(scores, indent=2))
        
        # Save to fitness.json
        with open('fitness.json', 'w') as f:
            json.dump(scores, f, indent=2)
        print("\nSaved to fitness.json")
    except Exception as e:
        print(f"Error running arena: {e}")
        print("\nFalling back to individual module inspection...")

if __name__ == '__main__':
    main()
