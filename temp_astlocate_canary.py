"""临时定位 canary.py 25% 真死因"""
import ast
from pathlib import Path

REPO_ROOT = Path(__file__).parent

class DefectLocator(ast.NodeVisitor):
    def __init__(self):
        self.dead_branches = []
        self.bad_conditions = []
        self.fname = ""
        
    def visit_FunctionDef(self, node):
        old = self.fname
        self.fname = node.name
        self.generic_visit(node)
        self.fname = old
        
    def visit_If(self, node):
        cond = ast.unparse(node.test) if hasattr(ast, 'unparse') else ""
        # 检测 always-True/False 死分支
        if isinstance(node.test, ast.Constant) and node.test.value is True:
            self.dead_branches.append((self.fname, cond, "always-True-if"))
        if isinstance(node.test, ast.Constant) and node.test.value is False:
            self.dead_branches.append((self.fname, cond, "always-False-if"))
        self.generic_visit(node)
        
    def visit_For(self, node):
        # 检测空循环或永不执行
        if isinstance(node.iter, ast.Constant) and isinstance(node.iter.value, (list, tuple, str)) and len(node.iter.value) == 0:
            self.dead_branches.append((self.fname, "empty_iter", "dead-loop"))
        self.generic_visit(node)

with open(REPO_ROOT / "canary.py") as f:
    src = f.read()
tree = ast.parse(src)
loc = DefectLocator()
loc.visit(tree)
print("=== 真死因定位 ===")
for item in loc.dead_branches:
    print(f"  [{item[0]}] {item[1]} -> {item[2]}")
print("=== 坏条件 ===")
for item in loc.bad_conditions:
    print(f"  [{item[0]}] {item[1]}")
