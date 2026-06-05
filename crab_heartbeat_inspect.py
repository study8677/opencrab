import ast, sys

# 读取 crab.py
with open('crab.py', 'r') as f:
    crab_src = f.read()

print("=== crab.py AST ===")
tree = ast.parse(crab_src)
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef):
        print(f"  Function: {node.name} @ line {node.lineno}")
        if any(isinstance(n, ast.Name) and 'heartbeat' in n.id for n in ast.walk(node)):
            print(f"    -> references heartbeat")
    elif isinstance(node, ast.ClassDef):
        print(f"Class: {node.name} @ line {node.lineno}")
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                print(f"  Method: {item.name}")

print("\n=== heartbeat.py AST ===")
with open('heartbeat.py', 'r') as f:
    hb_src = f.read()
hb_tree = ast.parse(hb_src)
for node in ast.walk(hb_tree):
    if isinstance(node, ast.FunctionDef):
        print(f"  Function: {node.name} @ line {node.lineno}")
    elif isinstance(node, ast.ClassDef):
        print(f"Class: {node.name} @ line {node.lineno}")
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                print(f"  Method: {item.name}")
