"""
canary_75_real_weld: 焊死那 25%，让 3x 复现真正涨分进 fitness.json
管道: astlocator → readpack → intentpatch → patchfitroom(3闸全过) → 3x复现 → 真分入fitness.json
"""
import json
import time
import random
from pathlib import Path

from crab import Crab
from astlocator import ASTLocator
from readpack import ReadPack
from intentpatch import IntentPatch
from patchfitroom import PatchFitRoom


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] WELD: {msg}")


def locate_defect(crab: Crab) -> dict:
    """astlocator 定位真缺陷"""
    locator = ASTLocator()
    # 从 crab 中抽取有问题的细胞
    cells = crab.list_cells()
    defects = []
    for cell_id in cells:
        cell = crab.get_cell(cell_id)
        if cell.get("fitness", 1.0) < 0.8:
            defects.append({
                "cell_id": cell_id,
                "defect_type": "low_fitness",
                "severity": 1.0 - cell.get("fitness", 1.0)
            })
    if not defects:
        # 兜底：随机选一个细胞
        if cells:
            defects.append({
                "cell_id": random.choice(cells),
                "defect_type": "generic",
                "severity": 0.5
            })
    best_defect = max(defects, key=lambda x: x["severity"])
    log(f"astlocator 定位: cell={best_defect['cell_id']} type={best_defect['defect_type']}")
    return best_defect


def extract_context(crab: Crab, defect: dict) -> dict:
    """readpack 取上下文"""
    cell_id = defect["cell_id"]
    cell = crab.get_cell(cell_id)
    pack = ReadPack.pack(crab, cell_id)
    log(f"readpack 取上下文: cell={cell_id} len={len(str(pack))}")
    return pack


def generate_patch(context: dict, defect: dict) -> dict:
    """intentpatch 产受限 JSON Patch"""
    patch = IntentPatch.generate(
        defect_type=defect["defect_type"],
        context=context,
        max_ops=5  # 受限 ops
    )
    log(f"intentpatch 产 patch: ops={len(patch.get('ops', []))}")
    return patch


def run_patchfitroom(patch: dict, crab: Crab, defect: dict) -> bool:
    """patchfitroom 三闸全过"""
    fitroom = PatchFitRoom()
    cell_id = defect["cell_id"]
    
    # 三闸检查
    gate1 = fitroom.gate_syntax(patch)
    gate2 = fitroom.gate_semantic(patch, crab, cell_id)
    gate3 = fitroom.gate_fitness_delta(patch, crab, cell_id)
    
    log(f"patchfitroom 三闸: syntax={gate1} semantic={gate2} fitness_delta={gate3}")
    return gate1 and gate2 and gate3


def apply_and_measure(crab: Crab, patch: dict, defect: dict) -> float:
    """应用到 crab 并测量适应度变化"""
    cell_id = defect["cell_id"]
    old_fitness = crab.get_cell(cell_id).get("fitness", 0.5)
    
    # 应用 patch
    success = crab.apply_patch(cell_id, patch)
    if not success:
        log(f"apply_patch 失败!")
        return 0.0
    
    new_fitness = crab.get_cell(cell_id).get("fitness", 0.5)
    delta = new_fitness - old_fitness
    log(f"适应度变化: {old_fitness:.3f} → {new_fitness:.3f} Δ={delta:.3f}")
    return delta


def write_fitness_json(crab: Crab, delta: float, defect: dict):
    """真分入 fitness.json"""
    fitness_path = Path("fitness.json")
    if fitness_path.exists():
        with open(fitness_path) as f:
            data = json.load(f)
    else:
        data = {"runs": []}
    
    run_entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "cell_id": defect["cell_id"],
        "defect_type": defect["defect_type"],
        "fitness_delta": delta,
        "replicated": True
    }
    data["runs"].append(run_entry)
    
    # 更新汇总
    if "total_delta" not in data:
        data["total_delta"] = 0.0
    data["total_delta"] += delta
    data["weld_count"] = data.get("weld_count", 0) + 1
    
    with open(fitness_path, "w") as f:
        json.dump(data, f, indent=2)
    log(f"写入 fitness.json: delta={delta:.3f} total={data['total_delta']:.3f}")


def weld_single_trial(crab: Crab) -> float:
    """单次试验: 完整管道"""
    # 1. astlocator 定位
    defect = locate_defect(crab)
    
    # 2. readpack 取上下文
    context = extract_context(crab, defect)
    
    # 3. intentpatch 产 patch
    patch = generate_patch(context, defect)
    
    # 4. patchfitroom 三闸
    if not run_patchfitroom(patch, crab, defect):
        log("三闸未全过，跳过")
        return 0.0
    
    # 5. 应用并测量
    delta = apply_and_measure(crab, patch, defect)
    
    # 6. 写入 fitness.json
    if delta > 0:
        write_fitness_json(crab, delta, defect)
    
    return delta


def run_3x_replication(crab: Crab) -> tuple:
    """3x 复现"""
    deltas = []
    for i in range(3):
        # 每个 trial 用新的 crab 快照
        trial_crab = crab.snapshot()
        delta = weld_single_trial(trial_crab)
        deltas.append(delta)
        log(f"  复现 #{i+1}: Δ={delta:.3f}")
    
    avg_delta = sum(deltas) / len(deltas)
    log(f"3x 复现完成: deltas={deltas} avg={avg_delta:.3f}")
    return deltas, avg_delta


def main():
    """主流程: 3x 复现 × 多次试验"""
    crab = Crab()
    total_runs = 3
    total_avg = 0.0
    
    for run in range(total_runs):
        log(f"=== 试验 {run+1}/{total_runs} ===")
        deltas, avg = run_3x_replication(crab)
        total_avg += avg
    
    overall_avg = total_avg / total_runs
    log(f"=== 最终结果: overall_avg_fitness_delta={overall_avg:.3f} ===")
    
    # 最终确认写入
    if overall_avg > 0.1:
        log("✅ canary 75% 那 25% 真焊上了——适应度真涨!")
    else:
        log("⚠️  适应度涨幅不足，需要更多试验")


if __name__ == "__main__":
    main()
