#!/usr/bin/env python3
"""核真 .gitignore 是否真的忽略 state/，以及 projects/ 的位置"""
import pathlib

def main():
    gi = pathlib.Path(".gitignore")
    if not gi.exists():
        print("❌ .gitignore 不存在")
        return
    
    lines = gi.read_text().splitlines()
    print(f"=== .gitignore 全文 ({len(lines)} 行) ===")
    for i, line in enumerate(lines, 1):
        print(f"  {i:2}: {line}")
    
    print(f"\n=== 分析 ===")
    state_related = []
    for i, l in enumerate(lines, 1):
        stripped = l.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "state" in stripped:
            state_related.append((i, stripped))
    
    if state_related:
        print(f"找到 {len(state_related)} 个 state 相关条目:")
        for i, entry in state_related:
            print(f"  行 {i}: {entry}")
    else:
        print("❌ .gitignore 中没有任何 state 相关条目")
    
    # 检查项目结构
    print(f"\n=== 目录结构检查 ===")
    for d in ["state", "projects", "ledger"]:
        p = pathlib.Path(d)
        exists = p.exists()
        print(f"  {d}/: {'✅ 存在' if exists else '❌ 不存在'}")
        if exists:
            items = list(p.iterdir())[:3]
            print(f"    → {len(items)} 个子项: {[x.name for x in items]}")

if __name__ == "__main__":
    main()
