"""
命令失效预警模块：抽样20个常用CLI，记录退出码/JSON形状/首错，生成坏入口修复单
"""
import subprocess
import json
import shlex
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import sys

@dataclass
class CLIHealthReport:
    """单个CLI命令的健康报告"""
    command: str
    exit_code: int
    has_json_output: bool
    json_shape: Optional[str]  # e.g., "dict", "list", "invalid"
    json_keys: Optional[List[str]]  # 顶层键
    first_error: Optional[str]
    stderr_snippet: Optional[str]
    stdout_snippet: Optional[str]

class CLIProbe:
    """命令失效预警探测器"""
    
    # 20个常用CLI命令抽样
    SAMPLE_COMMANDS = [
        "ls --version",
        "git --version",
        "python3 --version",
        "pip --version",
        "curl --version",
        "wget --version",
        "ssh -V",
        "rsync --version",
        "find --version",
        "grep --version",
        "sed --version",
        "awk --version",
        "tar --version",
        "unzip -v",
        "jq --version",
        "node --version",
        "npm --version",
        "docker --version",
        "systemctl --version",
        "journalctl --version"
    ]
    
    def __init__(self, timeout: int = 5):
        self.timeout = timeout
    
    def probe_single(self, command: str) -> CLIHealthReport:
        """探测单个CLI命令的健康状态"""
        try:
            # 安全解析命令
            args = shlex.split(command)
            
            # 执行命令并捕获输出
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            
            # 分析输出
            has_json, json_shape, json_keys = self._analyze_json_output(result.stdout)
            
            # 提取首个错误
            first_error = None
            stderr_snippet = None
            if result.stderr:
                stderr_lines = result.stderr.strip().split('\n')
                first_error = stderr_lines[0] if stderr_lines else None
                stderr_snippet = result.stderr[:200] if len(result.stderr) > 200 else result.stderr
            
            stdout_snippet = result.stdout[:200] if len(result.stdout) > 200 else result.stdout
            
            return CLIHealthReport(
                command=command,
                exit_code=result.returncode,
                has_json_output=has_json,
                json_shape=json_shape,
                json_keys=json_keys,
                first_error=first_error,
                stderr_snippet=stderr_snippet,
                stdout_snippet=stdout_snippet
            )
            
        except FileNotFoundError:
            return CLIHealthReport(
                command=command,
                exit_code=-1,
                has_json_output=False,
                json_shape=None,
                json_keys=None,
                first_error=f"Command not found: {args[0]}",
                stderr_snippet=f"Command not found: {args[0]}",
                stdout_snippet=None
            )
        except subprocess.TimeoutExpired:
            return CLIHealthReport(
                command=command,
                exit_code=-2,
                has_json_output=False,
                json_shape=None,
                json_keys=None,
                first_error="Command timed out",
                stderr_snippet="Command timed out",
                stdout_snippet=None
            )
        except Exception as e:
            return CLIHealthReport(
                command=command,
                exit_code=-3,
                has_json_output=False,
                json_shape=None,
                json_keys=None,
                first_error=str(e),
                stderr_snippet=str(e),
                stdout_snippet=None
            )
    
    def _analyze_json_output(self, stdout: str) -> tuple[bool, Optional[str], Optional[List[str]]]:
        """分析输出是否为JSON，提取形状和顶层键"""
        if not stdout.strip():
            return False, None, None
        
        try:
            # 尝试解析JSON
            data = json.loads(stdout)
            
            if isinstance(data, dict):
                keys = list(data.keys())[:10]  # 取前10个键
                return True, "dict", keys
            elif isinstance(data, list):
                return True, f"list[{len(data)}]", []
            else:
                return True, type(data).__name__, []
                
        except json.JSONDecodeError:
            # 不是JSON输出
            return False, None, None
    
    def probe_sample(self, commands: List[str] = None) -> List[CLIHealthReport]:
        """探测一批CLI命令"""
        if commands is None:
            commands = self.SAMPLE_COMMANDS
        
        reports = []
        for cmd in commands:
            report = self.probe_single(cmd)
            reports.append(report)
        
        return reports
    
    def generate_repair_manifest(self, reports: List[CLIHealthReport]) -> Dict[str, Any]:
        """生成坏入口修复清单"""
        # 统计问题
        broken_commands = []
        json_issues = []
        
        for report in reports:
            if report.exit_code != 0:
                broken_commands.append({
                    "command": report.command,
                    "exit_code": report.exit_code,
                    "error": report.first_error,
                    "severity": self._classify_severity(report)
                })
            
            if report.has_json_output and report.json_shape and "invalid" in report.json_shape:
                json_issues.append({
                    "command": report.command,
                    "issue": "Invalid JSON output",
                    "shape": report.json_shape
                })
        
        # 生成修复建议
        repair_suggestions = []
        for cmd_info in broken_commands:
            suggestion = self._generate_suggestion(cmd_info)
            if suggestion:
                repair_suggestions.append(suggestion)
        
        return {
            "probe_timestamp": self._get_timestamp(),
            "total_commands_probed": len(reports),
            "broken_commands": broken_commands,
            "json_issues": json_issues,
            "repair_suggestions": repair_suggestions,
            "health_score": self._calculate_health_score(reports)
        }
    
    def _classify_severity(self, report: CLIHealthReport) -> str:
        """分类问题严重性"""
        if report.exit_code == -1:  # 命令不存在
            return "critical"
        elif report.exit_code == -2:  # 超时
            return "warning"
        elif report.exit_code == 0:
            return "none"
        else:
            # 检查错误信息
            error = report.first_error or ""
            if "permission" in error.lower() or "denied" in error.lower():
                return "critical"
            elif "not found" in error.lower():
                return "high"
            else:
                return "medium"
    
    def _generate_suggestion(self, cmd_info: Dict) -> Optional[Dict]:
        """根据问题生成修复建议"""
        command = cmd_info["command"]
        error = cmd_info.get("error", "")
        
        suggestions = {
            "Command not found": f"Install the package providing '{command.split()[0]}'",
            "Permission denied": f"Check permissions for '{command.split()[0]}'",
            "timed out": f"Increase timeout for '{command}'",
            "No such file": f"Check if required files exist for '{command}'"
        }
        
        for pattern, suggestion in suggestions.items():
            if pattern.lower() in (error or "").lower():
                return {
                    "command": command,
                    "issue": pattern,
                    "suggestion": suggestion
                }
        
        return {
            "command": command,
            "issue": cmd_info["severity"],
            "suggestion": f"Debug '{command}' with exit code {cmd_info['exit_code']}"
        }
    
    def _calculate_health_score(self, reports: List[CLIHealthReport]) -> float:
        """计算整体健康评分 (0-100)"""
        if not reports:
            return 100.0
        
        healthy = sum(1 for r in reports if r.exit_code == 0)
        return (healthy / len(reports)) * 100
    
    def _get_timestamp(self) -> str:
        """获取时间戳"""
        from datetime import datetime
        return datetime.now().isoformat()


def run_cli_health_check(sample_size: int = 20) -> Dict[str, Any]:
    """运行CLI健康检查（主入口函数）"""
    probe = CLIProbe()
    
    # 抽样命令（默认使用预设列表，也可以随机抽样）
    if sample_size < len(CLIProbe.SAMPLE_COMMANDS):
        import random
        commands = random.sample(CLIProbe.SAMPLE_COMMANDS, sample_size)
    else:
        commands = CLIProbe.SAMPLE_COMMANDS[:sample_size]
    
    print(f"正在探测 {len(commands)} 个CLI命令...")
    
    # 执行探测
    reports = probe.probe_sample(commands)
    
    # 生成修复清单
    manifest = probe.generate_repair_manifest(reports)
    
    # 输出简要报告
    print(f"\n=== CLI健康检查报告 ===")
    print(f"健康评分: {manifest['health_score']:.1f}%")
    print(f"损坏命令数: {len(manifest['broken_commands'])}")
    print(f"JSON问题数: {len(manifest['json_issues'])}")
    
    if manifest['broken_commands']:
        print("\n损坏的命令:")
        for cmd in manifest['broken_commands'][:5]:  # 显示前5个
            print(f"  - {cmd['command']} (退出码: {cmd['exit_code']}, 严重性: {cmd['severity']})")
    
    return manifest


if __name__ == "__main__":
    # 当直接运行时执行检查
    manifest = run_cli_health_check(sample_size=20)
    
    # 保存报告
    with open("cli_health_report.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    
    print("\n完整报告已保存到 cli_health_report.json")
