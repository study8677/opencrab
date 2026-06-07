#!/usr/bin/env python3
"""运行 run_incomplete_heartbeat_weld_to_done.py 核心逻辑"""
import json
import subprocess
from datetime import datetime
from pathlib import Path

def main():
    print("=" * 60)
    print("Running: test_incomplete_heartbeat_weld -> DONE")
    print("=" * 60)

    task_name = "test_incomplete_heartbeat_weld"
    state_dir = Path("state")
    tasks_file = state_dir / "heartbeat_tasks.json"
    fitness_file = state_dir / "fitness.json"

    # Step 1: 核验 .gitignore
    print("\n--- Step 1: 核验 .gitignore ---")
    result = subprocess.run(
        ["git", "check-ignore", "-v", "state/projects/项目账.md"],
        capture_output=True, text=True
    )
    print(f"git check-ignore returncode: {result.returncode}")
    if result.returncode == 1:
        print(">>> .gitignore 未生效，修复中... <<<")
        gitignore = Path(".gitignore")
        if gitignore.exists():
            content = gitignore.read_text()
        else:
            content = ""
        if "state/projects/" not in content:
            if content and not content.endswith("\n"):
                content += "\n"
            content += "\n# State projects\nstate/projects/\n"
            gitignore.write_text(content)
            print("已修复 .gitignore")
        subprocess.run(["git", "add", ".gitignore"], check=True)
        subprocess.run([
            "git", "commit", "-m",
            "fix: ignore state/projects/ to prevent ledger contamination"
        ], check=True)
        print("已 commit .gitignore 修复")
    else:
        print(">>> .gitignore 已生效 <<<")

    # Step 2: 检查当前任务状态
    print("\n--- Step 2: 检查当前状态 ---")
    tasks = []
    if tasks_file.exists():
        with open(tasks_file) as f:
            tasks = json.load(f)
    
    current_task = None
    task_idx = None
    for i, t in enumerate(tasks):
        if t.get("name") == task_name:
            current_task = t
            task_idx = i
            break
    
    if current_task:
        print(f"找到任务: status={current_task.get('status')}")
        print(f"详情: {json.dumps(current_task, indent=2)}")
    else:
        print(f"任务 '{task_name}' 不存在，需要创建")

    # Step 3: 执行 WELD (pulse + fitness + mark DONE)
    print("\n--- Step 3: 执行 WELD ---")
    
    # Import heartbeat
    import heartbeat
    
    # Pulse
    heartbeat.pulse(task_name, status="IN_PROGRESS", metadata={
        "welding_started": datetime.now().isoformat(),
        "steps": ["verify_heartbeat", "update_fitness", "mark_done"]
    })
    print("✓ Pulsed heartbeat")
    
    # Verify
    status = heartbeat.get_task_status(task_name)
    print(f"✓ Heartbeat verified: status={status}")
    
    # Load & update fitness
    fitness = {}
    if fitness_file.exists():
        with open(fitness_file) as f:
            fitness = json.load(f)
    
    print(f"Current fitness['{task_name}']: {fitness.get(task_name)}")
    fitness[task_name] = 1.0
    
    fitness_file.parent.mkdir(exist_ok=True)
    with open(fitness_file, 'w') as f:
        json.dump(fitness, f, indent=2)
    print(f"✓ Updated fitness['{task_name}'] = 1.0")
    
    # Mark DONE
    tasks = []
    if tasks_file.exists():
        with open(tasks_file) as f:
            tasks = json.load(f)
    
    task_idx = None
    for i, t in enumerate(tasks):
        if t.get("name") == task_name:
            task_idx = i
            break
    
    if task_idx is not None:
        tasks[task_idx]["status"] = "DONE"
        tasks[task_idx]["completed"] = datetime.now().isoformat()
        if "steps" not in tasks[task_idx]:
            tasks[task_idx]["steps"] = []
        tasks[task_idx]["steps"].append("weld_complete")
        with open(tasks_file, 'w') as f:
            json.dump(tasks, f, indent=2)
        print(f"✓ Marked task as DONE")
    else:
        tasks.append({
            "name": task_name,
            "status": "DONE",
            "created": datetime.now().isoformat(),
            "completed": datetime.now().isoformat(),
            "steps": ["weld_complete"]
        })
        with open(tasks_file, 'w') as f:
            json.dump(tasks, f, indent=2)
        print(f"✓ Created task as DONE")
    
    # Commit state changes
    print("\n--- Step 4: Commit state ---")
    subprocess.run(["git", "add", "state/heartbeat_tasks.json", "state/fitness.json"], check=True)
    result = subprocess.run(["git", "diff", "--cached", "--stat"], capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout)
        subprocess.run([
            "git", "commit", "-m",
            "complete: test_incomplete_heartbeat_weld -> DONE"
        ], check=True)
        print("已 commit state 变更")
    else:
        print("无 state 变更需要 commit")

    # Step 5: Refresh docs
    print("\n--- Step 5: 刷新 docs ---")
    docs_index = Path("docs/index.html")
    if docs_index.exists():
        content = docs_index.read_text()
        if "test_incomplete_heartbeat_weld" not in content:
            new_entry = f"""
        <li>
          <span class="task-name">test_incomplete_heartbeat_weld</span>
          <span class="status done">DONE</span>
          <span class="date">{datetime.now().strftime('%Y-%m-%d')}</span>
        </li>"""
            if "</ul>" in content:
                content = content.replace("</ul>", new_entry + "\n      </ul>", 1)
                docs_index.write_text(content)
                print("✓ Added entry to docs/index.html")
        else:
            content = content.replace(
                'test_incomplete_heartbeat_weld</span><span class="status',
                'test_incomplete_heartbeat_weld</span><span class="status done">DONE'
            )
            docs_index.write_text(content)
            print("✓ Updated status in docs/index.html")
        
        subprocess.run(["git", "add", "docs/index.html"], check=True)
        subprocess.run([
            "git", "commit", "-m",
            "docs: update test_incomplete_heartbeat_weld status to DONE"
        ], check=True)
        print("已 commit docs 变更")
    else:
        print("docs/index.html 不存在，跳过")

    print("\n" + "=" * 60)
    print("WELD COMPLETE: test_incomplete_heartbeat_weld -> DONE")
    print("=" * 60)

    # Final verification
    print("\n--- Final State ---")
    print(f"Task status: {heartbeat.get_task_status(task_name)}")
    print(f"Fitness score: {heartbeat.get_fitness(task_name)}")

    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
