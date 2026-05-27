"""文档真伪闸：自动核对 README 能力表与真实 CLI/证据。

输出三类清单：
- missing: README 中列出但代码/证据中缺失
- exaggerated: 代码/证据中存在但 README 未记录（可能虚夸）
- outdated: README 中记录但代码/证据已过期/不再支持
"""
import os
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple


class DocumentSyncChecker:
    """文档真伪闸核心检查器。"""
    
    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)
        self.readme_path = self.project_root / "README.md"
        self.capabilities_from_readme: Dict[str, str] = {}
        self.capabilities_from_code: Dict[str, str] = {}
        self.cli_commands: Set[str] = set()
        self.evidence_files: Set[str] = set()
        
    def parse_readme_capabilities(self) -> Dict[str, str]:
        """从 README 中解析能力表。"""
        capabilities = {}
        
        if not self.readme_path.exists():
            return capabilities
        
        content = self.readme_path.read_text(encoding="utf-8")
        
        # 查找能力表（通常是以 | 开头的表格）
        table_pattern = r'\|([^|]+)\|([^|]+)\|'
        matches = re.findall(table_pattern, content)
        
        for match in matches:
            name, description = match[0].strip(), match[1].strip()
            if name and name.lower() not in ['能力名称', '名称', '能力', '功能', 'feature']:
                capabilities[name] = description
        
        self.capabilities_from_readme = capabilities
        return capabilities
    
    def scan_cli_commands(self) -> Set[str]:
        """扫描代码中的 CLI 命令。"""
        cli_commands = set()
        
        # 扫描可能的 CLI 入口文件
        for py_file in self.project_root.glob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
                
                # 查找 argparse 解析
                if 'add_argument' in content or 'ArgumentParser' in content:
                    # 提取命令名称（简化实现）
                    command_match = re.search(r'parse_args\(\)', content)
                    if command_match:
                        # 尝试从文件名推断命令
                        cmd_name = py_file.stem.replace('_', '-')
                        cli_commands.add(cmd_name)
                
                # 查找 click 命令
                if '@click.command' in content or '@click.group' in content:
                    cmd_match = re.search(r"@click\.(command|group)\(['\"]([^'\"]+)['\"]\)", content)
                    if cmd_match:
                        cli_commands.add(cmd_match.group(2))
                        
            except (UnicodeDecodeError, Exception):
                continue
        
        self.cli_commands = cli_commands
        return cli_commands
    
    def scan_evidence_files(self) -> Set[str]:
        """扫描证据文件（证据相关模块）。"""
        evidence_files = set()
        
        # 查找证据相关文件
        for py_file in self.project_root.glob("evidence*.py"):
            evidence_files.add(py_file.stem)
            
        # 查找证据目录
        evidence_dir = self.project_root / "evidence"
        if evidence_dir.is_dir():
            for evidence_file in evidence_dir.glob("*.py"):
                evidence_files.add(f"evidence/{evidence_file.stem}")
        
        self.evidence_files = evidence_files
        return evidence_files
    
    def infer_capabilities_from_code(self) -> Dict[str, str]:
        """从代码推断能力。"""
        capabilities = {}
        
        # 1. 从文件名推断
        for py_file in self.project_root.glob("*.py"):
            name = py_file.stem
            if name.startswith("test_") or name.startswith("_"):
                continue
            
            # 跳过已知非能力模块
            if name in ['sitecustomize', 'errors', 'conftest']:
                continue
                
            # 简单描述：用文件名作为能力名称
            description = f"模块 {name} 提供的功能"
            capabilities[name] = description
        
        # 2. 添加 CLI 命令作为能力
        if not self.cli_commands:
            self.scan_cli_commands()
        for cmd in self.cli_commands:
            capabilities[f"cli:{cmd}"] = f"CLI 命令 {cmd}"
        
        # 3. 添加证据模块作为能力
        if not self.evidence_files:
            self.scan_evidence_files()
        for evidence in self.evidence_files:
            capabilities[f"evidence:{evidence}"] = f"证据模块 {evidence}"
        
        self.capabilities_from_code = capabilities
        return capabilities
    
    def check_sync(self) -> Tuple[List[str], List[str], List[str]]:
        """检查文档与代码的同步状态。"""
        # 1. 解析 README
        if not self.capabilities_from_readme:
            self.parse_readme_capabilities()
        
        # 2. 推断代码能力
        if not self.capabilities_from_code:
            self.infer_capabilities_from_code()
        
        readme_names = set(self.capabilities_from_readme.keys())
        code_names = set(self.capabilities_from_code.keys())
        
        # 3. 计算差异
        missing = list(readme_names - code_names)  # README 中有，代码中无
        exaggerated = list(code_names - readme_names)  # 代码中有，README 中无
        outdated = []
        
        # 4. 过期检查：检查 README 中但代码中不再存在的
        for name in missing:
            # 检查是否确实是能力名称（而不是描述文字）
            if len(name) > 2 and not name.startswith('#'):
                outdated.append(name)
        
        # 5. 排除过期中的重复项
        outdated = list(set(outdated))
        missing = list(set(missing) - set(outdated))
        
        return missing, exaggerated, outdated
    
    def generate_report(self) -> str:
        """生成同步报告。"""
        missing, exaggerated, outdated = self.check_sync()
        
        report = ["文档真伪闸同步报告", "=" * 40, ""]
        
        if missing:
            report.append("缺失清单（README 中列出但代码中缺失）:")
            for name in sorted(missing):
                desc = self.capabilities_from_readme.get(name, "")
                report.append(f"  - {name}: {desc}")
            report.append("")
        
        if exaggerated:
            report.append("虚夸清单（代码中存在但 README 未记录）:")
            for name in sorted(exaggerated):
                desc = self.capabilities_from_code.get(name, "")
                report.append(f"  - {name}: {desc}")
            report.append("")
        
        if outdated:
            report.append("过期清单（README 中记录但代码已过期）:")
            for name in sorted(outdated):
                report.append(f"  - {name}")
            report.append("")
        
        if not missing and not exaggerated and not outdated:
            report.append("✅ 文档与代码完全同步！")
        
        return "\n".join(report)


def main():
    """命令行入口。"""
    import argparse
    
    parser = argparse.ArgumentParser(description="文档真伪闸：检查 README 与代码的同步状态")
    parser.add_argument("--project-root", default=".", help="项目根目录")
    parser.add_argument("--output", help="输出文件路径（默认输出到标准输出）")
    parser.add_argument("--check-only", action="store_true", help="仅检查，不生成详细报告")
    
    args = parser.parse_args()
    
    checker = DocumentSyncChecker(args.project_root)
    missing, exaggerated, outdated = checker.check_sync()
    
    if args.check_only:
        if missing or exaggerated or outdated:
            print(f"发现 {len(missing)} 个缺失，{len(exaggerated)} 个虚夸，{len(outdated)} 个过期")
            return 1
        else:
            print("文档与代码同步")
            return 0
    
    report = checker.generate_report()
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"报告已保存到: {args.output}")
    else:
        print(report)
    
    return 0 if not (missing or exaggerated or outdated) else 1


if __name__ == "__main__":
    exit(main())
