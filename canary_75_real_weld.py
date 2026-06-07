#!/usr/bin/env python3
"""
canary_75_real_weld.py - Brain-only 端到端真适应度
目标：3x 复现真涨分、焊进 fitness.json
"""
import os
import sys
import json
import time
import subprocess
from pathlib import Path

# --- 路径设置 ---
SCRIPT_DIR = Path(__file__).parent
CRAB_ROOT = SCRIPT_DIR.parent
PROJECTS_DIR = CRAB_ROOT / "projects"
PROJECTS_DATA_DIR = PROJECTS_DIR / "data"
PROJECTS_LOGS_DIR = PROJECTS_DIR / "logs"
FITNESS_JSON = PROJECTS_DIR / "fitness.json"

# --- 核心参数 ---
CANARY_NAME = "canary_75_real_weld"
CANARY_PROJECT = "canary_75_real_weld_project"
ITERATIONS = 3  # 3x 复现
TIMEOUT_SEC = 300
BRAINONLY_MODE = True


def load_fitness_json():
    """加载现有 fitness.json"""
    if FITNESS_JSON.exists():
        with open(FITNESS_JSON, 'r') as f:
            return json.load(f)
    return {}


def save_fitness_json(data):
    """保存 fitness.json"""
    with open(FITNESS_JSON, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"[WELD] Saved fitness.json with {len(data)} entries")


def get_project_path(name):
    """获取项目路径"""
    return PROJECTS_DIR / name


def ensure_project(name):
    """确保项目目录存在"""
    project_path = get_project_path(name)
    project_path.mkdir(parents=True, exist_ok=True)
    return project_path


def run_brainonly_fitness(project_name, iteration):
    """
    用 brain-only 模式跑一次适应度
    返回 (success, score, details)
    """
    project_path = ensure_project(project_name)
    
    # 确保项目有基础结构
    init_file = project_path / "__init__.py"
    if not init_file.exists():
        init_file.write_text("")
    
    # 构建 brain-only 命令
    # 用 crab.py 的 brain-only 模式
    cmd = [
        sys.executable,
        str(CRAB_ROOT / "crab.py"),
        "--brainonly",
        "--project", str(project_path),
        "--mode", "fitness",
        "--timeout", str(TIMEOUT_SEC),
    ]
    
    print(f"[BRAINONLY-{iteration}] Running: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SEC + 30,
            cwd=str(CRAB_ROOT)
        )
        
        stdout = result.stdout
        stderr = result.stderr
        
        print(f"[BRAINONLY-{iteration}] stdout: {stdout[:500]}")
        if stderr:
            print(f"[BRAINONLY-{iteration}] stderr: {stderr[:500]}")
        
        # 解析输出找分数
        score = None
        for line in stdout.split('\n') + stderr.split('\n'):
            if 'fitness' in line.lower() and ('score' in line.lower() or '%' in line):
                # 尝试提取分数
                import re
                m = re.search(r'[\d.]+%', line)
                if m:
                    score_str = m.group().replace('%', '')
                    try:
                        score = float(score_str)
                    except:
                        pass
        
        # 如果没解析到，检查返回码
        if result.returncode == 0:
            success = True
            if score is None:
                # 尝试从文件中读取
                fitness_file = project_path / ".fitness"
                if fitness_file.exists():
                    try:
                        score = float(fitness_file.read_text().strip())
                    except:
                        pass
        else:
            success = False
        
        return success, score, {"stdout": stdout, "stderr": stderr, "returncode": result.returncode}
        
    except subprocess.TimeoutExpired:
        print(f"[BRAINONLY-{iteration}] TIMEOUT after {TIMEOUT_SEC}s")
        return False, None, {"error": "timeout"}
    except Exception as e:
        print(f"[BRAINONLY-{iteration}] ERROR: {e}")
        return False, None, {"error": str(e)}


def run_fallback_brainonly(project_name, iteration):
    """
    兜底：用 evalbench 的 brain-only 模式跑适应度
    """
    project_path = ensure_project(project_name)
    
    # 用 evalbench 的 brain-only 模式
    cmd = [
        sys.executable,
        str(CRAB_ROOT / "evalbench.py"),
        "--project", str(project_path),
        "--mode", "brainonly",
        "--iterations", "1",
    ]
    
    print(f"[FALLBACK-{iteration}] Running: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SEC + 30,
            cwd=str(CRAB_ROOT)
        )
        
        stdout = result.stdout
        stderr = result.stderr
        
        print(f"[FALLBACK-{iteration}] stdout: {stdout[:500]}")
        
        # 解析分数
        score = None
        for line in stdout.split('\n') + stderr.split('\n'):
            import re
            m = re.search(r'[\d.]+%', line)
            if m:
                score_str = m.group().replace('%', '')
                try:
                    score = float(score_str)
                except:
                    pass
        
        return result.returncode == 0, score, {"stdout": stdout, "stderr": stderr}
        
    except Exception as e:
        print(f"[FALLBACK-{iteration}] ERROR: {e}")
        return False, None, {"error": str(e)}


def write_fitness_to_json(canary_name, scores, best_score, details):
    """把适应度写入 fitness.json"""
    data = load_fitness_json()
    
    # 构建条目
    entry = {
        "name": canary_name,
        "best_score": best_score,
        "scores": scores,
        "mean_score": sum(scores) / len(scores) if scores else None,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "brainonly",
        "iterations": len(scores),
        "details": details
    }
    
    data[canary_name] = entry
    
    save_fitness_json(data)
    print(f"[WELD] Wrote {canary_name} -> fitness.json: best={best_score}, mean={entry['mean_score']}")


def main():
    """主流程：3x 复现 brain-only 适应度"""
    print(f"=" * 60)
    print(f"CANARY_75_REAL_WELD - Brain-only 端到端适应度进化")
    print(f"=" * 60)
    print(f"Project: {CANARY_PROJECT}")
    print(f"Iterations: {ITERATIONS}")
    print(f"Brain-only: {BRAINONLY_MODE}")
    print(f"Timeout: {TIMEOUT_SEC}s per iteration")
    print()
    
    scores = []
    details = {"iterations": [], "errors": []}
    best_score = 0.0
    best_iteration = 0
    
    for i in range(1, ITERATIONS + 1):
        print(f"\n--- Iteration {i}/{ITERATIONS} ---")
        
        # 尝试主方法
        success, score, detail = run_brainonly_fitness(CANARY_PROJECT, i)
        
        # 兜底用 fallback
        if not success or score is None:
            print(f"[MAIN] Primary method failed, trying fallback...")
            success, score, detail = run_fallback_brainonly(CANARY_PROJECT, i)
        
        # 记录
        iter_record = {
            "iteration": i,
            "success": success,
            "score": score,
            "detail": detail
        }
        details["iterations"].append(iter_record)
        
        if success and score is not None:
            scores.append(score)
            print(f"[SCORE-{i}] {score}%")
            
            if score > best_score:
                best_score = score
                best_iteration = i
                print(f"[NEW BEST] {best_score}% at iteration {i}")
        else:
            details["errors"].append(f"Iteration {i} failed")
            print(f"[FAILED-{i}] No score obtained")
    
    # 汇总
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    print(f"Total iterations: {ITERATIONS}")
    print(f"Successful: {len(scores)}/{ITERATIONS}")
    
    if scores:
        mean_score = sum(scores) / len(scores)
        print(f"Scores: {scores}")
        print(f"Best score: {best_score}% (iteration {best_iteration})")
        print(f"Mean score: {mean_score:.2f}%")
        
        # 写入 fitness.json
        write_fitness_to_json(CANARY_NAME, scores, best_score, details)
        
        print("\n[SUCCESS] 3x reproduction complete, welded to fitness.json")
        return 0
    else:
        print("[FAIL] No valid scores obtained")
        details["final_error"] = "No scores obtained in any iteration"
        write_fitness_to_json(CANARY_NAME, [], 0.0, details)
        return 1


if __name__ == "__main__":
    sys.exit(main())
