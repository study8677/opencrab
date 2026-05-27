import ast
import os
import re
import json
from typing import Optional, Dict, Any

class BoundaryCaseExtractor:
    """从外部项目中提取边界用例生成器模式"""
    
    def __init__(self, project_path: str):
        self.project_path = project_path
        self.extracted_patterns = []
    
    def find_boundary_generators(self) -> list[Dict[str, Any]]:
        """扫描项目，寻找边界用例生成器函数"""
        patterns = []
        
        for root, dirs, files in os.walk(self.project_path):
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        
                        tree = ast.parse(content)
                        
                        for node in ast.walk(tree):
                            if isinstance(node, ast.FunctionDef):
                                # 识别边界用例生成器模式
                                if self._is_boundary_generator(node, content):
                                    pattern = {
                                        'file': file_path,
                                        'name': node.name,
                                        'line': node.lineno,
                                        'source': ast.get_source_segment(content, node),
                                        'args': [arg.arg for arg in node.args.args],
                                        'patterns': self._extract_patterns(node)
                                    }
                                    patterns.append(pattern)
                    except Exception as e:
                        continue
        
        return patterns
    
    def _is_boundary_generator(self, node: ast.FunctionDef, content: str) -> bool:
        """判断函数是否为边界用例生成器"""
        # 检查函数名特征
        name = node.name.lower()
        if not any(keyword in name for keyword in ['boundary', 'edge', 'corner', 'extreme', 'limit', 'generate']):
            return False
        
        # 检查函数体特征
        source = ast.get_source_segment(content, node)
        if not source:
            return False
        
        # 检查返回列表或生成器
        has_list_return = 'return [' in source
        has_yield = 'yield ' in source
        
        # 检查边界值模式
        boundary_patterns = [
            r'\b(0|1|-1|float\("inf"\)|float\("-inf"\)|float\("nan"\))\b',
            r'\b(maxsize|maxsize|sys\.maxsize)\b',
            r'\b(empty|none|null|nil)\b',
            r'\b边界|极端|角落|边界值|edge|corner|boundary\b'
        ]
        
        pattern_count = sum(1 for pattern in boundary_patterns 
                          if re.search(pattern, source, re.IGNORECASE))
        
        return (has_list_return or has_yield) and pattern_count >= 2
    
    def _extract_patterns(self, node: ast.FunctionDef) -> list[str]:
        """提取生成的边界值模式"""
        patterns = []
        
        # 分析函数体中的常量值
        for child in ast.walk(node):
            if isinstance(child, ast.Constant):
                if isinstance(child.value, (int, float, str)):
                    patterns.append(repr(child.value))
            elif isinstance(child, ast.Call):
                # 处理构造函数调用，如 int(), float() 等
                if hasattr(child, 'func'):
                    if isinstance(child.func, ast.Name):
                        if child.func.id in ['int', 'float', 'str', 'bool']:
                            patterns.append(f'{child.func.id}()')
        
        return list(set(patterns))[:10]  # 限制模式数量


def extract_and_compile(project_path: str, target_name: Optional[str] = None) -> Optional[str]:
    """提取边界用例生成器并编译为 brain-only 补丁"""
    extractor = BoundaryCaseExtractor(project_path)
    patterns = extractor.find_boundary_generators()
    
    if not patterns:
        return None
    
    # 选择最合适的模式
    selected = None
    if target_name:
        for pattern in patterns:
            if pattern['name'] == target_name:
                selected = pattern
                break
    
    if not selected:
        # 选择最简单的模式（参数最少）
        selected = min(patterns, key=lambda x: len(x['args']))
    
    # 生成 brain-only 补丁
    patch = _compile_to_brainonly_patch(selected)
    
    return patch


def _compile_to_brainonly_patch(pattern: Dict[str, Any]) -> str:
    """将模式编译为 brain-only 补丁"""
    source = pattern['source']
    
    # 确保生成器函数符合 brain-only 要求
    # 1. 无外部依赖
    # 2. 纯函数
    # 3. 可移植
    
    # 注入必要的导入
    patch_lines = [
        f"# Brain-only patch: Boundary case generator extracted from {pattern['file']}",
        f"# Original function: {pattern['name']}",
        "",
        "import random",
        "from typing import List, Any, Generator",
        "",
        "# Ensure this is a pure function with no side effects",
        source,
        "",
        "# Wrapper for compatibility",
        f"def generate_boundary_cases_{pattern['name']}(test_data: Any) -> List[Any]:",
        "    \"\"\"Generate boundary cases for testing\"\"\"",
        "    results = []",
        f"    for case in {pattern['name']}(test_data):",
        "        results.append(case)",
        "    return results",
        "",
        "# Metadata",
        f"EXTRACTED_FROM = '{pattern['file']}'",
        f"ORIGINAL_LINE = {pattern['line']}",
        f"PATTERN_PATTERNS = {json.dumps(pattern['patterns'])}"
    ]
    
    return '\n'.join(patch_lines)
