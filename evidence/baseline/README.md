# 真适应度基线证据账本

本目录保存 `run_fitness_baseline.py` 运行产生的基线评测证据。

## 文件结构

```
baseline/
├── README.md           # 本文件
├── index.json          # 所有基线的索引
├── latest.json         # 最新基线的快速引用
├── baseline_*.json     # 每次运行的详细结果
└── report_*.md         # 可读的 Markdown 报告
```

## 使用方式

### 运行基线评测
```bash
python run_fitness_baseline.py
python run_fitness_baseline.py --quick      # 快速 smoke
python run_fitness_baseline.py --label v1   # 带标签
```

### 将结果加入 git 跟踪
```bash
git add evidence/baseline/
git diff --cached --stat   # 查看变更
git commit -m "基线: 真适应度初始刻度"
```

### 对比基线
```bash
# 查看历史基线
cat evidence/baseline/index.json

# 对比两次基线
python -c "
import json
from pathlib import Path
baseline_dir = Path('evidence/baseline')
files = sorted(baseline_dir.glob('baseline_*.json'))
if len(files) >= 2:
    a = json.loads(files[-2].read_text())
    b = json.loads(files[-1].read_text())
    print(f'基线A: {a[\"pass_rate\"]:.1%} ({a[\"timestamp\"]})')
    print(f'基线B: {b[\"pass_rate\"]:.1%} ({b[\"timestamp\"]})')
    diff = b['pass_rate'] - a['pass_rate']
    print(f'变化: {diff:+.1%}')
"
```

## 基线含义

- **arena**: 核心能力竞技场 - 验证基础功能
- **boundaryeval**: 边界条件评测 - 验证鲁棒性
- **regression**: 回归测试 - 确保既有功能不退化
- **canary**: 金丝雀哨兵 - 高风险场景预警

基线通过率代表**真实能力水平**，而非代码行数或模块数量。
