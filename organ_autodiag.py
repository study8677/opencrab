"""
自动诊断器：扫描领地里所有标着"?"的未知模块，对每个跑最小探针（import/CLI/函数签名/契约），
自动推断能力分类并生成清账报告。这样未来每长一个新模块都不会再悄悄变成"?"。
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

# 复用现有探针模块的核心功能
from .unknown_organ_prober import probe_module, get_unknown_organs

class OrganAutoDiag:
    """自动诊断器"""
    
    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or Path(__file__).parent / "diagnosis_reports"
        self.output_dir.mkdir(exist_ok=True)
        
        # 分类阈值配置
        self.thresholds = {
            "high_trust": 0.7,      # 高信任分
            "medium_trust": 0.4,    # 中信任分
            "low_trust": 0.2        # 低信任分（退役候选）
        }
        
        # 能力分类映射
        self.capability_categories = {
            "data_validation": ["validate", "check", "verify", "assert"],
            "cli_tool": ["cli", "command", "main", "argparse"],
            "event_handler": ["handle", "process", "callback"],
            "registry": ["register", "registry", "catalog"],
            "monitor": ["watch", "monitor", "observe", "detect"],
            "optimizer": ["optimize", "improve", "enhance"],
            "debugger": ["debug", "trace", "inspect"],
            "unknown": []  # 无法分类的归为此类
        }
    
    def classify_capability(self, capability_description: str) -> str:
        """根据能力描述自动分类模块"""
        if not capability_description:
            return "unknown"
        
        desc_lower = capability_description.lower()
        
        # 遍历分类，寻找关键词匹配
        for category, keywords in self.capability_categories.items():
            for keyword in keywords:
                if keyword in desc_lower:
                    return category
        
        # 如果没匹配到任何关键词，尝试根据导出接口数量判断
        if "导出" in capability_description and "接口" in capability_description:
            # 提取数字，例如"导出 15 个接口"
            try:
                parts = capability_description.split("导出")
                if len(parts) > 1:
                    num_part = parts[1].split("个")[0]
                    count = int(num_part.strip())
                    if count > 10:
                        return "hub"  # 大量导出的可能是枢纽模块
                    elif count > 5:
                        return "library"  # 中等数量的可能是库模块
            except:
                pass
        
        return "unknown"
    
    def classify_by_trust_score(self, trust_score: float) -> str:
        """根据信任分数分类"""
        if trust_score >= self.thresholds["high_trust"]:
            return "healthy"
        elif trust_score >= self.thresholds["medium_trust"]:
            return "marginal"
        elif trust_score >= self.thresholds["low_trust"]:
            return "fragile"
        else:
            return "retirement_candidate"
    
    def generate_recommendations(self, probe_result: Dict) -> List[str]:
        """根据探测结果生成建议"""
        recommendations = []
        trust = probe_result["trust_score"]
        
        if not probe_result["import_success"]:
            recommendations.append("修复导入错误：检查依赖和语法")
        
        if trust < self.thresholds["low_trust"]:
            recommendations.append("严重信任问题：考虑退役或重写")
        elif trust < self.thresholds["medium_trust"]:
            recommendations.append("需要改进：增加文档、CLI或契约")
        
        if not probe_result["has_cli"]:
            recommendations.append("建议添加CLI入口提升可用性")
        
        if not probe_result["has_contracts"]:
            recommendations.append("建议实现契约接口增强互操作性")
        
        if not probe_result["capability_description"] or probe_result["capability_description"] == "未知功能":
            recommendations.append("需要明确能力描述")
        
        return recommendations
    
    def run_full_diagnosis(self, max_modules: Optional[int] = None) -> Dict[str, Any]:
        """运行完整诊断流程"""
        start_time = time.time()
        unknown_modules = get_unknown_organs()
        
        if max_modules:
            unknown_modules = unknown_modules[:max_modules]
        
        results = []
        summary = {
            "timestamp": datetime.now().isoformat(),
            "total_unknown": len(unknown_modules),
            "categories": {},
            "trust_levels": {},
            "errors": [],
            "top_recommendations": []
        }
        
        print(f"🔬 自动诊断器启动：发现 {len(unknown_modules)} 个未知模块")
        
        for i, module_name in enumerate(unknown_modules, 1):
            print(f"[{i}/{len(unknown_modules)}] 探测: {module_name}")
            
            try:
                # 运行探针
                probe_result = probe_module(module_name)
                
                # 自动分类
                capability_class = self.classify_capability(probe_result["capability_description"])
                trust_class = self.classify_by_trust_score(probe_result["trust_score"])
                
                # 生成建议
                recommendations = self.generate_recommendations(probe_result)
                
                # 组装结果
                result = {
                    **probe_result,
                    "capability_class": capability_class,
                    "trust_class": trust_class,
                    "recommendations": recommendations,
                    "probe_timestamp": datetime.now().isoformat()
                }
                
                results.append(result)
                
                # 更新统计
                summary["categories"][capability_class] = summary["categories"].get(capability_class, 0) + 1
                summary["trust_levels"][trust_class] = summary["trust_levels"].get(trust_class, 0) + 1
                
                # 打印简要结果
                status = "✓" if probe_result["import_success"] else "✗"
                trust = f"{probe_result['trust_score']:.2f}"
                print(f"  {status} 信任:{trust} 分类:{capability_class} 状态:{trust_class}")
                
            except Exception as e:
                error_msg = f"探测{module_name}失败: {str(e)}"
                print(f"  ✗ {error_msg}")
                summary["errors"].append(error_msg)
        
        # 生成报告
        report = {
            "summary": summary,
            "details": results,
            "generation_time": time.time() - start_time
        }
        
        # 保存报告
        self.save_report(report)
        
        # 生成简要摘要
        self.print_summary(summary)
        
        return report
    
    def save_report(self, report: Dict) -> Path:
        """保存诊断报告"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = self.output_dir / f"autodiag_report_{timestamp}.json"
        
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"📄 诊断报告已保存: {report_file}")
        
        # 同时生成一个纯文本摘要
        summary_file = self.output_dir / f"autodiag_summary_{timestamp}.txt"
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write("=== 自动诊断报告摘要 ===\n")
            f.write(f"生成时间: {report['summary']['timestamp']}\n")
            f.write(f"总未知模块: {report['summary']['total_unknown']}\n\n")
            
            f.write("分类统计:\n")
            for category, count in report['summary']['categories'].items():
                f.write(f"  {category}: {count}\n")
            
            f.write("\n信任等级统计:\n")
            for level, count in report['summary']['trust_levels'].items():
                f.write(f"  {level}: {count}\n")
            
            if report['summary']['errors']:
                f.write(f"\n错误 ({len(report['summary']['errors'])} 个):\n")
                for error in report['summary']['errors'][:5]:  # 只显示前5个
                    f.write(f"  - {error}\n")
        
        return report_file
    
    def print_summary(self, summary: Dict):
        """打印诊断摘要"""
        print("\n" + "="*50)
        print("📊 自动诊断完成")
        print(f"总未知模块: {summary['total_unknown']}")
        
        print("\n分类分布:")
        for category, count in sorted(summary['categories'].items(), key=lambda x: x[1], reverse=True):
            percentage = (count / summary['total_unknown']) * 100 if summary['total_unknown'] > 0 else 0
            print(f"  {category}: {count} ({percentage:.1f}%)")
        
        print("\n信任等级分布:")
        for level, count in sorted(summary['trust_levels'].items(), key=lambda x: x[1], reverse=True):
            percentage = (count / summary['total_unknown']) * 100 if summary['total_unknown'] > 0 else 0
            print(f"  {level}: {count} ({percentage:.1f}%)")
        
        if summary['errors']:
            print(f"\n⚠️ 遇到 {len(summary['errors'])} 个错误")
        
        print("="*50)

def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="自动诊断器：扫描未知模块并生成清账报告")
    parser.add_argument("--max", type=int, help="最大扫描模块数（调试用）")
    parser.add_argument("--output", type=str, help="输出目录路径")
    
    args = parser.parse_args()
    
    output_dir = Path(args.output) if args.output else None
    diagnoser = OrganAutoDiag(output_dir=output_dir)
    
    report = diagnoser.run_full_diagnosis(max_modules=args.max)
    
    print("\n✅ 诊断完成！报告已生成。")
    
    # 返回退出码：如果有错误或大量退役候选，返回非零
    retirement_candidates = report['summary']['trust_levels'].get('retirement_candidate', 0)
    if report['summary']['errors'] or retirement_candidates > 5:
        return 1
    return 0

if __name__ == "__main__":
    exit(main())
