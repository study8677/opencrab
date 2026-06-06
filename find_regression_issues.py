#!/usr/bin/env python3
"""find_regression_issues: look for brain-only patchable bugs in regression.py."""
import ast
import os

def analyze_file(filepath):
    """Analyze a Python file for potential issues."""
    try:
        with open(filepath) as f:
            content = f.read()
        tree = ast.parse(content)
        
        issues = []
        funcs = []
        classes = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                funcs.append(node.name)
                # Check for common issues
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Name):
                            if child.func.id == 'TODO':
                                issues.append(f"Function {node.name}: contains TODO call")
        
        return {
            'filepath': filepath,
            'functions': funcs,
            'issues': issues,
            'ast_nodes': len(list(ast.walk(tree)))
        }
    except Exception as e:
        return {'filepath': filepath, 'error': str(e)}

def main():
    files_to_check = [
        'regression.py',
        'canary.py', 
        'canary_75.py',
        'boundaryeval.py',
        'arena.py',
        'brainonly_replay.py',
        'brainonly_canary_patch.py',
        'brainonly_blindfix_regression.py',
        'brainonly_benefit_chain_regression.py',
    ]
    
    print("=== File Analysis ===\n")
    results = {}
    for f in files_to_check:
        if os.path.exists(f):
            r = analyze_file(f)
            results[f] = r
            print(f"[{f}]")
            print(f"  Functions: {r.get('functions', [])[:10]}")
            print(f"  Issues: {r.get('issues', [])}")
            print(f"  AST nodes: {r.get('ast_nodes', 'N/A')}")
            print()
        else:
            print(f"[{f}] NOT FOUND\n")
    
    # Save results
    import json
    with open('file_analysis.json', 'w') as f:
        json.dump(results, f, indent=2)

if __name__ == '__main__':
    main()
