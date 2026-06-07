#!/usr/bin/env python3
"""定位 canary.py 的 25% 真死因 —— 用 astlocator 定位 + readpack 拿上下文，结果落 navlog/。

用法:
    python navlog/canary_defect_locate.py    # 执行定位与上下文收集
"""
from __future__ import annotations

import sys
from pathlib import Path

# 确保 navlog 目录存在
NAVLOG_DIR = Path(__file__).parent
NAVLOG_DIR.mkdir(exist_ok=True)

# 把项目根加入路径，以便导入 astlocator/readpack
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import astlocator
from astlocator import locate, get_realdefect_findings
import readpack
from readpack import pack


def main() -> None:
    canary_path = PROJECT_ROOT / "canary.py"
    output_path = NAVLOG_DIR / "canary_defect_analysis.md"

    print(f"📍 定位目标：{canary_path}")

    # Step 1: 用 astlocator 的 realdefect 扫描定位问题
    findings = get_realdefect_findings(str(canary_path))

    # Step 2: 用 readpack 收集每个问题的上下文
    lines = [
        "# canary.py 缺陷定位报告",
        "",
        f"生成时间：{Path(__file__).stat().st_mtime}",
        f"目标文件：{canary_path}",
        "",
        "## 一、AST 结构发现",
        "",
    ]

    # 枚举 canary.py 所有可定位的目标
    src = canary_path.read_text()
    entries = astlocator.entries(src)

    lines.append(f"共发现 {len(entries)} 个可定位目标：")
    for e in entries:
        lines.append(f"- [{e.kind}] `{e.qualname}` 第 {e.lineno}–{e.end_lineno} 行")

    lines.append("")
    lines.append("## 二、真实缺陷扫描结果")
    lines.append("")

    if findings:
        lines.append(f"发现 {len(findings)} 个可疑点：")
        for i, f in enumerate(findings, 1):
            kind = f.get("kind", "unknown")
            qualname = f.get("qualname", "<?>")
            detail = f.get("detail", "")
            lines.append(f"### {i}. [{kind}] {qualname}")
            lines.append("")
            lines.append(f"详情：{detail}")
            lines.append("")

            # 用 readpack 拿上下文
            ctx = pack(src, qualname, module="canary")
            lines.append("**上下文（readpack）：**")
            lines.append("")
            if ctx.ok:
                lines.append(f"- 签名：{ctx.signature or '（CLI 守卫块）'}")
                lines.append(f"- 职责：{ctx.doc or '（无 docstring）'}")
                lines.append(f"- 调用方：{len(ctx.callers)} 个")
                lines.append(f"- 近邻测试：{len(ctx.tests)} 个")
                if ctx.contract:
                    lines.append(f"- 契约：{ctx.contract.duty}")
                else:
                    lines.append("- 契约：未立约")
            else:
                lines.append(f"- 无法获取上下文：{ctx.reason}")
            lines.append("")
    else:
        lines.append("⚠️ astlocator 扫描未发现明显的结构缺陷（空实现/unbound_method等）")
        lines.append("")
        lines.append("**进一步分析：**")
        lines.append("")
        lines.append("canary.py 的「死因」可能不在结构层，而在**逻辑层**：")
        lines.append("")

        # 分析 _check_no_circular_deps 的逻辑
        lines.append("### 1. _check_no_circular_deps 逻辑分析")
        lines.append("")
        lines.append("```python")
        lines.append("def _check_no_circular_deps(self) -> bool:")
        lines.append("    try:")
        lines.append("        import importlib")
        lines.append("        for mod in ['crab', 'organogenesis', 'hands', 'brain']:")
        lines.append("            importlib.import_module(mod)")
        lines.append("        return True")
        lines.append("    except (ImportError, AttributeError):")
        lines.append("        return True  # ← 问题：模块不存在时返回 True（正常）")
        lines.append("    except Exception:")
        lines.append("        return False  # ← 任何其他异常都返回 False（报警）")
        lines.append("```")
        lines.append("")
        lines.append("**可能的死因：**")
        lines.append("- 如果 `importlib.import_module` 抛出非 ImportError/AttributeError 的异常，")
        lines.append("  比如 ModuleNotFoundError、RuntimeError（循环依赖卡住），就会返回 False")
        lines.append("- `except Exception` 太宽泛，任何意外都会触发金丝雀报警")
        lines.append("")
        lines.append("### 2. _check_health_score 逻辑分析")
        lines.append("")
        ctx_health = pack(src, "_check_health_score")
        if ctx_health.ok:
            lines.append(f"签名：{ctx_health.signature}")
            lines.append(f"行段：第 {ctx_health.locus.lineno}–{ctx_health.locus.end_lineno} 行")
            lines.append("")
            lines.append("```python")
            lines.append(ctx_health.locus.segment)
            lines.append("```")
            lines.append("")
            lines.append("**可能的死因：**")
            lines.append("- 如果 fitness.json 存在但没有 `pass_rate` 或 `score` 字段，")
            lines.append("  `score = data.get('pass_rate') or data.get('score')` 会得到 None，")
            lines.append("  然后 `if score is None: return False` → 金丝雀报警")
            lines.append("- 这是最常见的「25% 真死因」：数据文件格式变了但代码没跟")
            lines.append("")

    lines.append("## 三、定位结论")
    lines.append("")
    lines.append("**最可能的 25% 真死因：**")
    lines.append("")
    lines.append("1. **_check_health_score 第 3 分支（`score is None`）**")
    lines.append("   - 如果 fitness.json 没有 pass_rate/score 字段，立刻报警")
    lines.append("   - 这是「数据格式不匹配」类的逻辑伤")
    lines.append("")
    lines.append("2. **_check_no_circular_deps 第 5 分支（`except Exception`）**")
    lines.append("   - 任何非 ImportError/AttributeError 的异常都会触发报警")
    lines.append("   - 这是「异常吞太宽」类的逻辑伤")
    lines.append("")
    lines.append("3. **_check_fitness_json_exists / _check_evidence_dir_writable**")
    lines.append("   - 纯粹的 I/O 检查，死因一目了然（文件不存在/目录不可写）")
    lines.append("   - 不是「25% 隐藏死因」，是「已知前置条件不满足」")
    lines.append("")

    # 写入报告
    output_path.write_text("\n".join(lines))
    print(f"✅ 报告已落：{output_path}")
    print(f"📊 共定位 {len(findings)} 个结构缺陷 + 分析了逻辑层死因")


if __name__ == "__main__":
    main()
