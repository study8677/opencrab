#!/usr/bin/env python3
"""修复 .gitignore 让 state/ 被正确忽略"""
import pathlib

def main():
    gi = pathlib.Path(".gitignore")
    
    print("=== 检查 .gitignore 当前状态 ===")
    
    if not gi.exists():
        print("❌ .gitignore 不存在，先创建")
        gi.write_text("state/\n")
        print("✅ 已创建 .gitignore 并写入 'state/'")
        return
    
    lines = gi.read_text().splitlines()
    print(f"当前 {len(lines)} 行:")
    for i, l in enumerate(lines, 1):
        print(f"  {i:2}: {l}")
    
    # 检查第 11 行
    print(f"\n=== 核真 .gitignore 第 11 行 ===")
    if len(lines) >= 11:
        line11 = lines[10].strip()
        print(f"第 11 行: {repr(line11)}")
        if line11 == "state/" or line11 == "state":
            print("✅ 第 11 行正确忽略 state/")
            return
        else:
            print(f"❌ 第 11 行不是 'state/'，实际是: {repr(line11)}")
            print("需要修复")
    else:
        print(f"❌ 只有 {len(lines)} 行，不够 11 行")
        print("需要添加 state/ 条目")
    
    # 修复方案：添加 state/ 到 .gitignore
    state_exists = any("state" in l.strip() and not l.strip().startswith("#") 
                       for l in lines)
    
    if not state_exists:
        print("\n=== 执行修复 ===")
        new_lines = lines + ["state/"]
        gi.write_text("\n".join(new_lines) + "\n")
        print("✅ 已添加 'state/' 到 .gitignore 末尾")
        
        # 验证
        new_content = gi.read_text().splitlines()
        print(f"\n修复后共 {len(new_content)} 行:")
        for i, l in enumerate(new_content, 1):
            marker = " ◄◄◄ 行 11" if i == 11 else ""
            print(f"  {i:2}: {l}{marker}")
    else:
        print("⚠️  state 相关条目已存在，无需添加")

if __name__ == "__main__":
    main()
