import sys
sys.path.insert(0, '.')
from autopsy_canary_80_3x import load_autopsy_data

data = load_autopsy_data()
print("=== CANARY 80 3X AUTOPSY ===")
print(f"Total failing cases: {data['summary']['total_failing']}")
print(f"Failing cells: {data['summary']['failing_cells']}")
print()

# Find smallest case (fewest failing scenarios)
cases = data.get('cases', [])
if not cases:
    cases = data.get('failing_cases', [])
    
min_case = None
min_count = 999
for c in cases:
    count = len(c.get('failing_scenarios', []))
    if count > 0 and count < min_count:
        min_count = count
        min_case = c
        
if min_case:
    print(f"MINIMAL FAILING CASE (cell={min_case.get('cell')}, failing={min_count}):")
    print(f"  Patch attempted: {min_case.get('patch_attempted')}")
    print(f"  Failure reason: {min_case.get('failure_reason')}")
    print(f"  Failing scenarios: {min_case.get('failing_scenarios', [])[:5]}")
else:
    # Look at all failing cases
    print("All failing cases:")
    for c in cases[:5]:
        print(f"  Cell {c.get('cell')}: {c.get('failure_reason')}")
        print(f"    Scenarios: {len(c.get('failing_scenarios', []))}")
