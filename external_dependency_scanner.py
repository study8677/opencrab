"""
Static scanner for external AI dependencies (e.g., claude/codex).
Scans Python files for import statements or function calls that reference
known external agents, and produces a weaning list.
"""

import ast
import os
import sys
from pathlib import Path
from typing import List, Dict, Tuple

# Keywords indicating external AI calls
EXTERNAL_KEYWORDS = {'claude', 'codex'}


class ExternalCallFinder(ast.NodeVisitor):
    """AST visitor that finds import statements or calls referencing EXTERNAL_KEYWORDS."""
    
    def __init__(self, filename: str):
        self.filename = filename
        self.findings: List[Dict] = []  # each dict: file, line, col, code, type
    
    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            if any(kw in alias.name.lower() for kw in EXTERNAL_KEYWORDS):
                self.findings.append({
                    'file': self.filename,
                    'line': node.lineno,
                    'col': node.col_offset,
                    'code': ast.dump(node),
                    'type': 'import'
                })
        self.generic_visit(node)
    
    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module and any(kw in node.module.lower() for kw in EXTERNAL_KEYWORDS):
            self.findings.append({
                'file': self.filename,
                'line': node.lineno,
                'col': node.col_offset,
                'code': ast.dump(node),
                'type': 'import_from'
            })
        else:
            for alias in node.names:
                if any(kw in alias.name.lower() for kw in EXTERNAL_KEYWORDS):
                    self.findings.append({
                        'file': self.filename,
                        'line': node.lineno,
                        'col': node.col_offset,
                        'code': ast.dump(node),
                        'type': 'import_from'
                    })
        self.generic_visit(node)
    
    def visit_Call(self, node: ast.Call):
        # Check if the call is to a function whose name contains keywords
        if isinstance(node.func, ast.Name):
            if any(kw in node.func.id.lower() for kw in EXTERNAL_KEYWORDS):
                self.findings.append({
                    'file': self.filename,
                    'line': node.lineno,
                    'col': node.col_offset,
                    'code': ast.dump(node),
                    'type': 'call'
                })
        # Also check attributes like obj.claude()
        elif isinstance(node.func, ast.Attribute):
            if any(kw in node.func.attr.lower() for kw in EXTERNAL_KEYWORDS):
                self.findings.append({
                    'file': self.filename,
                    'line': node.lineno,
                    'col': node.col_offset,
                    'code': ast.dump(node),
                    'type': 'call'
                })
        self.generic_visit(node)


def scan_file(filepath: str) -> List[Dict]:
    """Scan a single Python file for external calls."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)
        finder = ExternalCallFinder(filepath)
        finder.visit(tree)
        return finder.findings
    except SyntaxError:
        print(f"Warning: syntax error in {filepath}, skipping", file=sys.stderr)
        return []
    except Exception as e:
        print(f"Warning: error scanning {filepath}: {e}", file=sys.stderr)
        return []


def scan_directory(directory: str = '.') -> List[Dict]:
    """Scan all .py files in a directory recursively."""
    findings = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                findings.extend(scan_file(filepath))
    return findings


def generate_weaning_list(findings: List[Dict]) -> str:
    """Generate a human-readable weaning list from scan results."""
    if not findings:
        return "No external AI dependencies found."
    lines = ["External AI dependencies (weaning list):"]
    for f in findings:
        lines.append(f"  {f['file']}:{f['line']}:{f['col']} - {f['type']} (code: {f['code'][:100]}...)")
    return '\n'.join(lines)


def check_for_new_calls(baseline_file: str, current_scan: List[Dict]) -> Tuple[bool, List[Dict]]:
    """
    Compare current scan results with a baseline list to detect new external calls.
    Returns (is_clean, new_calls).
    """
    if not os.path.exists(baseline_file):
        # If no baseline, assume current scan is the baseline (first run)
        return True, current_scan
    
    baseline = []
    try:
        with open(baseline_file, 'r', encoding='utf-8') as f:
            baseline = ast.literal_eval(f.read())
    except Exception:
        baseline = []
    
    baseline_set = {(item['file'], item['line'], item['col']) for item in baseline}
    new_calls = [f for f in current_scan if (f['file'], f['line'], f['col']) not in baseline_set]
    
    return len(new_calls) == 0, new_calls


def update_baseline(baseline_file: str, scan_results: List[Dict]):
    """Update the baseline file with current scan results."""
    with open(baseline_file, 'w', encoding='utf-8') as f:
        f.write(repr(scan_results))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Scan for external AI dependencies.')
    parser.add_argument('--dir', default='.', help='Directory to scan')
    parser.add_argument('--output', help='Output weaning list to file')
    parser.add_argument('--check-baseline', help='Baseline file to compare against')
    args = parser.parse_args()
    
    results = scan_directory(args.dir)
    weaning_list = generate_weaning_list(results)
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(weaning_list)
        print(f"Weaning list written to {args.output}")
    else:
        print(weaning_list)
    
    if args.check_baseline:
        is_clean, new_calls = check_for_new_calls(args.check_baseline, results)
        if not is_clean:
            print("WARNING: New external calls detected!", file=sys.stderr)
            for call in new_calls:
                print(f"  New: {call['file']}:{call['line']}", file=sys.stderr)
            sys.exit(1)
        else:
            print("Baseline check passed: no new external calls.")
            # Update baseline with current results
            update_baseline(args.check_baseline, results)
    else:
        # No baseline check requested, just scan
        sys.exit(0)
