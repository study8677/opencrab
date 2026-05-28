#!/usr/bin/env python3
"""领地耦合体检：孤岛 × 零热力重叠清单

扫描所有 .py 文件的真实调用关系，找出哪些器官从未被任何其他器官引用（孤岛模块），
再交叉比对使用热力图，产出一份"孤岛 × 零热力"重叠清单，对重叠项做最小探针确认
它们真有活路还是该退役。

用法：
    python island_heat_audit.py                     # 运行完整体检
    python island_heat_audit.py --probe             # 额外实跑每扇门的 --help
    python island_heat_audit.py --days 14           # 审计回溯窗口（默认 7 天）
    python island_heat_audit.py --json              # 机读：输出 JSON 格式
    python island_heat_audit.py --quiet             # 静默模式，只输出关键信息
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib
import sys
import traceback
import importlib.util

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@dataclasses.dataclass
class ModuleHealth:
    """模块健康状态"""
    name: str
    is_island: bool = False        # 是否孤岛模块（无引用）
    heat_status: str = ""          # 热力状态（发烫/温活/冰封/常温）
    heat_reasons: list[str] = dataclasses.field(default_factory=list)
    can_import: bool | None = None # 能否正常导入
    has_functions: bool = False    # 是否有可调用的函数/类
    import_error: str = ""         # 导入错误信息
    probe_result: str = ""         # 探针结果描述

    def to_meta(self) -> dict:
        return {
            "name": self.name,
            "is_island": self.is_island,
            "heat_status": self.heat_status,
            "heat_reasons": self.heat_reasons,
            "can_import": self.can_import,
            "has_functions": self.has_functions,
            "import_error": self.import_error,
            "probe_result": self.probe_result,
        }


def run_coupling_audit(days: int = 7, probe: bool = False, quiet: bool = False) -> tuple[list[ModuleHealth], dict]:
    """运行完整的领地耦合体检"""
    import territory_audit
    import usageheat

    # 1. 获取孤岛模块列表
    auditor = territory_audit.TerritoryAudit(str(REPO_ROOT))
    island_modules = auditor.get_island_modules()
    if not quiet:
        print(f"🔍 发现 {len(island_modules)} 个孤岛模块（无引用）")

    # 2. 获取热力图
    heats = usageheat.build(days=days, probe=probe)
    heat_map = {h.name: h for h in heats}

    # 3. 交叉比对：找出孤岛 × 零热力（冰封或常温）的模块
    overlap = []
    all_modules = []
    
    for module_name in sorted(island_modules):
        if module_name in heat_map:
            h = heat_map[module_name]
            is_zero_heat = h.temp in (usageheat.TEMP_COLD, usageheat.TEMP_MILD)
        else:
            # 不在热力图中，视为零热力
            is_zero_heat = True
            h = usageheat.Heat(name=module_name, summary="（无热力数据）")
        
        health = ModuleHealth(
            name=module_name,
            is_island=True,
            heat_status=h.temp,
            heat_reasons=h.reasons,
        )
        all_modules.append(health)
        
        if is_zero_heat:
            overlap.append(health)

    # 4. 对重叠项做最小探针
    if overlap and not quiet:
        print(f"⚠️  发现 {len(overlap)} 个「孤岛 × 零热力」重叠模块，开始探针检查...")

    for health in overlap:
        if not quiet:
            print(f"   🔎 探针 {health.name}.py...", end=" ")
        
        # 尝试导入模块
        try:
            module_path = REPO_ROOT / f"{health.name}.py"
            if not module_path.exists():
                health.can_import = False
                health.import_error = "文件不存在"
                health.probe_result = "❌ 文件缺失"
                if not quiet:
                    print("❌ 文件缺失")
                continue

            # 尝试导入
            spec = importlib.util.spec_from_file_location(health.name, str(module_path))
            if spec is None:
                health.can_import = False
                health.import_error = "无法创建模块规格"
                health.probe_result = "❌ 导入规格错误"
                if not quiet:
                    print("❌ 导入规格错误")
                continue

            module = importlib.util.module_from_spec(spec)
            
            # 检查是否有可调用的函数/类
            try:
                # 执行模块（但不运行 main）
                spec.loader.exec_module(module)
                health.can_import = True
                
                # 检查是否有函数或类定义
                has_functions = False
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if callable(attr) and not attr_name.startswith('_'):
                        has_functions = True
                        break
                
                health.has_functions = has_functions
                
                if has_functions:
                    health.probe_result = "✅ 可导入且有可调用函数"
                else:
                    health.probe_result = "⚠️  可导入但无公开函数"
                
            except Exception as e:
                health.can_import = False
                health.import_error = f"执行错误: {e}"
                health.probe_result = f"❌ 执行失败: {e}"
                if not quiet:
                    print(f"❌ 执行失败")
                
        except Exception as e:
            health.can_import = False
            health.import_error = f"未知错误: {e}"
            health.probe_result = f"❌ 未知错误: {e}"
            if not quiet:
                print(f"❌ 未知错误")

        if not quiet:
            print(health.probe_result)

    # 5. 汇总统计
    stats = {
        "total_modules": len(all_modules),
        "island_modules": len(island_modules),
        "overlap_modules": len(overlap),
        "can_import": sum(1 for h in overlap if h.can_import is True),
        "has_functions": sum(1 for h in overlap if h.has_functions),
        "should_retire": sum(1 for h in overlap if not h.can_import or (h.can_import and not h.has_functions)),
        "probe_summary": {}
    }
    
    # 统计探针结果
    for health in overlap:
        stats["probe_summary"][health.probe_result] = stats["probe_summary"].get(health.probe_result, 0) + 1

    return all_modules, stats


def generate_report(all_modules: list[ModuleHealth], stats: dict, days: int, probed: bool) -> str:
    """生成人类可读的报告"""
    report = []
    report.append("=" * 60)
    report.append("🦠 领地耦合体检报告")
    report.append(f"📅 体检时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"🔍 审计窗口: {days} 天")
    report.append(f"🚀 入口探针: {'已实跑' if probed else '未实跑'}")
    report.append("=" * 60)
    
    report.append("\n📊 总体统计:")
    report.append(f"   总模块数: {stats['total_modules']}")
    report.append(f"   孤岛模块: {stats['island_modules']} 个")
    report.append(f"   孤岛×零热力重叠: {stats['overlap_modules']} 个")
    report.append(f"   可导入: {stats['can_import']} 个")
    report.append(f"   有可调用函数: {stats['has_functions']} 个")
    report.append(f"   建议退役: {stats['should_retire']} 个")
    
    report.append("\n🔍 孤岛×零热力重叠清单:")
    report.append("-" * 60)
    
    # 按探针结果分组显示
    by_probe = {}
    for health in all_modules:
        if health.is_island and health.heat_status in ("冰封", "常温"):
            key = health.probe_result or "待探针"
            by_probe.setdefault(key, []).append(health)
    
    for probe_result, modules in sorted(by_probe.items()):
        report.append(f"\n  {probe_result} ({len(modules)} 个):")
        for health in modules[:10]:  # 只显示前10个
            report.append(f"     • {health.name}.py")
            if health.heat_reasons:
                report.append(f"       热力原因: {', '.join(health.heat_reasons)}")
            if health.import_error:
                report.append(f"       导入错误: {health.import_error}")
        if len(modules) > 10:
            report.append(f"     ... 还有 {len(modules) - 10} 个")
    
    report.append("\n" + "=" * 60)
    
    if stats['should_retire'] > 0:
        report.append(f"\n⚠️  发现 {stats['should_retire']} 个建议退役的模块:")
        report.append("这些模块既不被任何模块引用（孤岛），又零热力，且探针显示")
        report.append("它们要么无法导入，要么导入后没有可调用的功能。")
        report.append("建议：")
        report.append("   1. 检查是否还有依赖关系需要保留")
        report.append("   2. 考虑退役或归档这些模块")
        report.append("   3. 如果仍有用处，尝试建立正确的依赖关系")
    else:
        report.append("\n✅ 未发现建议退役的模块：所有孤岛模块要么有热力，要么探针显示仍有功能")
    
    return "\n".join(report)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="领地耦合体检：孤岛 × 零热力重叠清单")
    ap.add_argument("--days", type=int, default=7, metavar="N",
                    help="审计回溯窗口天数（默认 7）")
    ap.add_argument("--probe", action="store_true",
                    help="额外实跑每扇门的 --help，把推不开的标为发烫")
    ap.add_argument("--json", action="store_true",
                    help="机读：输出 JSON 格式")
    ap.add_argument("--quiet", action="store_true",
                    help="静默模式，只输出关键信息")
    args = ap.parse_args(argv)

    try:
        all_modules, stats = run_coupling_audit(
            days=args.days,
            probe=args.probe,
            quiet=args.quiet
        )
        
        if args.json:
            output = {
                "days": args.days,
                "probed": args.probe,
                "stats": stats,
                "modules": [m.to_meta() for m in all_modules],
                "recommendations": []
            }
            
            # 生成建议
            for health in all_modules:
                if health.is_island and health.heat_status in ("冰封", "常温"):
                    if not health.can_import or (health.can_import and not health.has_functions):
                        output["recommendations"].append({
                            "module": health.name,
                            "reason": health.probe_result,
                            "action": "退役"
                        })
            
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            report = generate_report(all_modules, stats, args.days, args.probe)
            print(report)
            
            # 如果有建议退役的模块，返回非零退出码
            if stats['should_retire'] > 0:
                sys.exit(1)
                
    except Exception as e:
        if not args.quiet:
            print(f"❌ 体检失败: {e}")
            traceback.print_exc()
        sys.exit(2)


if __name__ == "__main__":
    main()
