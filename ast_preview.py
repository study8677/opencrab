"""
将受限补丁转成 AST 差分预览的模块
"""
import ast
from typing import Tuple, Optional

class ASTDiffPreview:
    """将受限补丁转成 AST 差分预览"""
    
    def generate_preview(self, original_code: str, patched_code: str) -> Optional[str]:
        """
        生成 AST 差分预览
        
        Args:
            original_code: 原始代码字符串
            patched_code: 应用补丁后的代码字符串
            
        Returns:
            AST 差分预览字符串，如果解析失败则返回 None
        """
        try:
            original_ast = ast.parse(original_code)
            patched_ast = ast.parse(patched_code)
            
            diff_lines = []
            self._compare_nodes(original_ast, patched_ast, diff_lines, indent=0)
            
            if diff_lines:
                return "AST Diff Preview:\n" + "\n".join(diff_lines)
            else:
                return "AST Diff Preview: No differences detected"
                
        except SyntaxError as e:
            return f"AST Diff Preview Error: {e}"
    
    def _compare_nodes(self, node1, node2, diff_lines: list, indent: int):
        """递归比较 AST 节点"""
        indent_str = "  " * indent
        
        if type(node1) != type(node2):
            diff_lines.append(f"{indent_str}[Type Changed] {type(node1).__name__} -> {type(node2).__name__}")
            return
        
        # 比较节点属性
        for attr in set(dir(node1)) & set(dir(node2)):
            if attr.startswith('_') or attr in ('lineno', 'col_offset', 'end_lineno', 'end_col_offset'):
                continue
                
            val1 = getattr(node1, attr)
            val2 = getattr(node2, attr)
            
            if isinstance(val1, (str, int, float, bool, type(None))):
                if val1 != val2:
                    diff_lines.append(f"{indent_str}[{attr}] {val1!r} -> {val2!r}")
            elif isinstance(val1, list):
                if val1 != val2:
                    diff_lines.append(f"{indent_str}[{attr}] list changed: {len(val1)} -> {len(val2)} items")
        
        # 递归比较子节点
        children1 = list(ast.iter_child_nodes(node1))
        children2 = list(ast.iter_child_nodes(node2))
        
        for child1, child2 in zip(children1, children2):
            self._compare_nodes(child1, child2, diff_lines, indent + 1)
        
        # 如果有额外的子节点
        if len(children1) > len(children2):
            for extra_child in children1[len(children2):]:
                diff_lines.append(f"{indent_str}[Removed Node] {type(extra_child).__name__}")
        elif len(children2) > len(children1):
            for extra_child in children2[len(children1):]:
                diff_lines.append(f"{indent_str}[Added Node] {type(extra_child).__name__}")
    
    def validate_patch(self, patch: str) -> Tuple[bool, str]:
        """验证受限补丁是否为合法 Python 代码"""
        try:
            ast.parse(patch)
            return True, "Patch is valid Python syntax"
        except SyntaxError as e:
            return False, f"Patch syntax error: {e}"

# 创建单例实例
ast_diff_preview = ASTDiffPreview()
