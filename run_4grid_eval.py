#!/usr/bin/env python3
"""run_4grid_eval: Run arena/boundaryeval/regression/canary and return real scores."""
import sys
import os
import json
import traceback

def safe_import_and_run(module_name):
    """Try to import and run a module's main evaluation."""
    try:
        mod = __import__(module_name)
        
        # Check for different entry points
        if hasattr(mod, 'run'):
            result = mod.run()
            if isinstance(result, (int, float)):
                return {'module': module_name, 'score': result, 'status': 'ok'}
            return {'module': module_name, 'result': result, 'status': 'ok'}
        
        if hasattr(mod, 'evaluate'):
            result = mod.evaluate()
            return {'module': module_name, 'result': result, 'status': 'ok'}
        
        if hasattr(mod, 'main'):
            # Capture stdout
            import io
            from contextlib import redirect_stdout
            f = io.StringIO()
            with redirect_stdout(f):
                mod.main()
            output = f.getvalue()
            return {'module': module_name, 'output': output, 'status': 'ok'}
        
        # No standard entry point – return module attributes
        attrs = {k: v for k, v in vars(mod).items() if not k.startswith('_')}
        return {
            'module': module_name,
            'attrs': list(attrs.keys())[:20],
            'status': 'no_entry_point'
        }
    except Exception as e:
        return {
            'module': module_name,
            'error': str(e),
            'traceback': traceback.format_exc(),
            'status': 'error'
        }

def main():
    modules_to_eval = [
        'arena',
        'boundaryeval', 
        'boundaryeval_aegis_absorption_regression',
        'boundaryeval_malicious_intent_regression',
        'boundaryeval_redteam_regression',
        'boundaryeval_regression',
        'regression',
        'canary',
        'canary_75',
        'brainonly_benefit_chain_regression',
        'brainonly_blindfix_regression',
        'brainonly_canary_patch',
    ]
    
    results = {}
    for m in modules_to_eval:
        print(f"\n=== Evaluating: {m} ===")
        r = safe_import_and_run(m)
        results[m] = r
        print(json.dumps(r, indent=2))
    
    # Save full results
    with open('4grid_eval_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    # Summary table
    print("\n\n=== SUMMARY TABLE ===")
    print(f"{'Module':<50} {'Status':<20} {'Score/Result'}")
    print("-" * 90)
    for name, r in results.items():
        status = r.get('status', 'unknown')
        if status == 'ok':
            score = r.get('score', r.get('result', 'N/A'))
            print(f"{name:<50} {status:<20} {score}")
        else:
            print(f"{name:<50} {status:<20} ERROR: {r.get('error', 'unknown')[:50]}")

if __name__ == '__main__':
    main()
