#!/usr/bin/env python3
"""
领土审计模块 - 扫描并分析所有.py文件的活跃度和依赖关系
"""
import os
import ast
import time
import importlib.util
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from collections import defaultdict

class TerritoryAudit:
    """领土审计器，分析代码库的健康度和演化状态"""
    
    def __init__(self, root_dir: str = "."):
        self.root = Path(root_dir).resolve()
        self.files: Dict[str, Path] = {}
        self.imports: Dict[str, Set[str]] = defaultdict(set)
        self.last_modified: Dict[str, float] = {}
        self.complexity_scores: Dict[str, int] = {}
        self._scan_files()
    
    def _scan_files(self) -> None:
        """扫描目录下所有Python文件"""
        for py_file in self.root.glob("*.py"):
            if py_file.is_file():
                file_name = py_file.stem
                self.files[file_name] = py_file
                self.last_modified[file_name] = py_file.stat().st_mtime
                self._analyze_imports(py_file, file_name)
                self._estimate_complexity(py_file, file_name)
    
    def _analyze_imports(self, file_path: Path, module_name: str) -> None:
        """分析文件中的导入语句"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.imports[module_name].add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        self.imports[module_name].add(node.module)
        except (SyntaxError, UnicodeDecodeError):
            pass
    
    def _estimate_complexity(self, file_path: Path, module_name: str) -> None:
        """估计文件的复杂度（基于行数、函数数和类数）"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            lines = len(content.splitlines())
            tree = ast.parse(content)
            
            # 统计函数和类的数量
            function_count = sum(1 for node in ast.walk(tree) if isinstance(node, ast.FunctionDef))
            class_count = sum(1 for node in ast.walk(tree) if isinstance(node, ast.ClassDef))
            
            # 简单复杂度公式：行数 + 5*函数数 + 10*类数
            complexity = lines + 5 * function_count + 10 * class_count
            self.complexity_scores[module_name] = complexity
        except (SyntaxError, UnicodeDecodeError):
            self.complexity_scores[module_name] = 0
    
    def get_hot_modules(self, top_n: int = 10) -> List[Tuple[str, int]]:
        """获取被其他模块导入最多的模块（热度最高的）"""
        import_counts = defaultdict(int)
        
        for module, deps in self.imports.items():
            for dep in deps:
                # 只计算本地模块
                if dep in self.files:
                    import_counts[dep] += 1
        
        # 按导入次数排序
        sorted_modules = sorted(import_counts.items(), key=lambda x: x[1], reverse=True)
        return sorted_modules[:top_n]
    
    def get_recent_changes(self, days: int = 7) -> List[Tuple[str, str, float]]:
        """获取最近修改的文件"""
        cutoff = time.time() - days * 24 * 3600
        recent = []
        
        for module, mtime in self.last_modified.items():
            if mtime > cutoff:
                # 计算距离现在的天数
                days_ago = (time.time() - mtime) / (24 * 3600)
                recent.append((module, self.files[module].name, days_ago))
        
        return sorted(recent, key=lambda x: x[2])
    
    def find_complex_files(self, threshold: int = 100) -> List[Tuple[str, int]]:
        """查找复杂度超过阈值的文件"""
        return [(module, score) for module, score in self.complexity_scores.items() 
                if score > threshold]
    
    def find_dependency_clusters(self) -> List[Set[str]]:
        """识别强依赖集群（互相导入的模块）"""
        clusters = []
        visited = set()
        
        for module in self.files:
            if module in visited:
                continue
                
            cluster = set()
            stack = [module]
            
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                    
                visited.add(current)
                cluster.add(current)
                
                # 查找相互依赖
                deps = self.imports.get(current, set())
                for dep in deps:
                    if dep in self.files and dep not in visited:
                        # 检查是否存在双向依赖
                        if dep in self.imports and current in self.imports[dep]:
                            stack.append(dep)
                        # 或者简单添加所有依赖（包括单向）
                        elif dep not in visited:
                            cluster.add(dep)
                            visited.add(dep)
            
            if len(cluster) > 1:  # 至少两个模块
                clusters.append(cluster)
        
        return clusters
    
    def identify_critical_files(self) -> Dict[str, List[str]]:
        """识别关键文件（被大量依赖且复杂度高的）"""
        critical = {
            "heavily_imported": [],
            "high_complexity": [],
            "recently_changed": [],
            "potential_risk": []  # 复杂度高且最近修改过的
        }
        
        # 获取被导入最多的模块
        hot_modules = self.get_hot_modules(5)
        critical["heavily_imported"] = [m[0] for m in hot_modules]
        
        # 获取复杂度最高的文件
        complex_files = self.find_complex_files(150)
        critical["high_complexity"] = [f[0] for f in complex_files]
        
        # 获取最近修改的文件
        recent_changes = self.get_recent_changes(3)  # 最近3天
        critical["recently_changed"] = [r[0] for r in recent_changes]
        
        # 识别风险文件：复杂度高且最近修改过
        recent_modules = set(r[0] for r in recent_changes)
        complex_modules = set(f[0] for f in complex_files)
        critical["potential_risk"] = list(recent_modules & complex_modules)
        
        return critical
    
    def generate_report(self) -> str:
        """生成审计报告"""
        report_lines = [
            "=" * 60,
            "领土审计报告",
            f"审计时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"总文件数: {len(self.files)}",
            "=" * 60
        ]
        
        # 1. 关键文件识别
        report_lines.append("\n1. 关键文件识别:")
        critical = self.identify_critical_files()
        
        if critical["heavily_imported"]:
            report_lines.append("   - 高被导入模块:")
            for mod in critical["heavily_imported"][:3]:
                report_lines.append(f"     * {mod}")
        
        if critical["high_complexity"]:
            report_lines.append("   - 高复杂度文件:")
            for mod in critical["high_complexity"][:3]:
                report_lines.append(f"     * {mod} (复杂度: {self.complexity_scores[mod]})")
        
        if critical["recently_changed"]:
            report_lines.append("   - 最近修改文件:")
            for mod in critical["recently_changed"][:5]:
                report_lines.append(f"     * {mod}")
        
        if critical["potential_risk"]:
            report_lines.append("   - 潜在风险文件（复杂度高且近期修改）:")
            for mod in critical["potential_risk"]:
                report_lines.append(f"     * {mod}")
        
        # 2. 依赖集群
        clusters = self.find_dependency_clusters()
        if clusters:
            report_lines.append("\n2. 强依赖集群:")
            for i, cluster in enumerate(clusters[:5], 1):
                report_lines.append(f"   集群{i}: {', '.join(list(cluster)[:4])}{'...' if len(cluster) > 4 else ''}")
        
        # 3. 活跃度统计
        report_lines.append("\n3. 最近7天活跃度:")
        recent_files = self.get_recent_changes(7)
        report_lines.append(f"   - 总修改文件数: {len(recent_files)}")
        
        # 4. 复杂度分布
        complexity_dist = {
            "低(0-100)": 0,
            "中(101-200)": 0,
            "高(201+)": 0
        }
        
        for score in self.complexity_scores.values():
            if score <= 100:
                complexity_dist["低(0-100)"] += 1
            elif score <= 200:
                complexity_dist["中(101-200)"] += 1
            else:
                complexity_dist["高(201+)"] += 1
        
        report_lines.append("\n4. 复杂度分布:")
        for level, count in complexity_dist.items():
            report_lines.append(f"   - {level}: {count}个文件")
        
        report_lines.append("\n" + "=" * 60)
        
        return "\n".join(report_lines)


def audit_territory(root_dir: str = ".") -> str:
    """执行领土审计并返回报告"""
    auditor = TerritoryAudit(root_dir)
    return auditor.generate_report()


def get_important_files(root_dir: str = ".") -> Dict[str, List[str]]:
    """获取重要文件分类"""
    auditor = TerritoryAudit(root_dir)
    return auditor.identify_critical_files()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        directory = sys.argv[1]
    else:
        directory = "."
    
    print(audit_territory(directory))
