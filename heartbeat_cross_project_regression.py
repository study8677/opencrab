#!/usr/bin/env python3
"""跨心跳项目连续性回归测试 🏹🏹 —— 验证「续旧」vs「开新」的意图记忆。

意图的心脏是 form_intent，它必须能认出「同一项目的新一轮心跳」，
而不是每次都把它当成「从未见过的全新项目」。

测试逻辑：
1. 用 projects账本.json 锁定一个测试项目
2. 跑一次心跳，记下当时的意图输出
3. 改 projects账本.json 里该项目的一个状态字段（如 priority）
4. 再跑一次，断言它认出了「续旧」而非「开新」

退出码：0 = 连续性完好；1 = 意图漂移（把续认成了新）
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent
_PY = sys.executable

# 跑心跳时强制的环境：梦境模式（不真打大脑），白名单全开（不漏能力）
_DREAM_ENV = {
    "OPENCRAB_API_KEY": "",
    "OPENCRAB_CAPABILITIES": "",
    "OPENCRAB_AUTONOMY": "journal",
    "PYTHONIOENCODING": "utf-8",
}


def _run_heartbeat_once(cwd: pathlib.Path) -> tuple[int, str]:
    """在 cwd 下跑一次心跳（once 模式），返回 (退出码, stdout+stderr)。"""
    env = {**os.environ, **_DREAM_ENV}
    try:
        proc = subprocess.run(
            [_PY, "crab.py", "once"],
            cwd=str(cwd), env=env,
            capture_output=True, text=True, timeout=120,
        )
        return proc.returncode, proc.stdout + proc.stderr
    except Exception as e:
        return -1, f"<执行异常> {e!r}"


def _find_ledger_path(cwd: pathlib.Path) -> pathlib.Path | None:
    """找项目账本：优先 projects账本.json，其次 projects_ledger.json。"""
    for name in ("projects账本.json", "projects_ledger.json", "ledger.json"):
        p = cwd / name
        if p.exists():
            return p
    return None


def _load_ledger(ledger_path: pathlib.Path) -> list[dict]:
    """加载账本，返回项目列表。"""
    try:
        data = json.loads(ledger_path.read_text("utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "projects" in data:
            return data["projects"]
        if isinstance(data, dict) and "items" in data:
            return data["items"]
        return []
    except Exception:
        return []


def _save_ledger(ledger_path: pathlib.Path, projects: list[dict]) -> None:
    """保存账本，保持原有格式风格。"""
    text = json.dumps(projects, ensure_ascii=False, indent=2)
    ledger_path.write_text(text + "\n", "utf-8")


def _extract_intent(output: str) -> dict:
    """从心跳输出中提取意图信息。

    尝试匹配以下模式：
    - 「开新」/ 「新项目」/ 「新意图」 -> new_project
    - 「续旧」/ 「继续」/ 「已有」 -> continuation
    - 项目名提取
    """
    text_lower = output.lower()
    if any(kw in text_lower for kw in ["开新", "新项目", "new project", "new intent"]):
        kind = "new_project"
    elif any(kw in text_lower for kw in ["续旧", "继续", "已有", "continuation", "resume"]):
        kind = "continuation"
    else:
        kind = "unknown"

    # 尝试提取项目名
    project_names = re.findall(r'["\'"]?([\w\u4e00-\u9fff-]+)["\'"]?(?:项目|intent|ledger)', output)
    project = project_names[0] if project_names else None

    return {"kind": kind, "project": project, "raw_snippet": output[:500]}


def test_cross_heartbeat_continuity() -> tuple[bool, str]:
    """核心测试：跨心跳项目连续性。

    步骤：
    1. 准备一个干净的临时副本
    2. 跑第一次心跳，记录输出
    3. 修改账本中某个项目的状态
    4. 跑第二次心跳，断言意图类型为「续旧」
    """
    with tempfile.TemporaryDirectory(prefix="opencrab-continuity-") as tmp:
        sandbox = pathlib.Path(tmp)
        # 复制仓库（跳过 .git/state/__pycache__）
        import shutil
        shutil.copytree(
            REPO_ROOT, sandbox,
            ignore=shutil.ignore_patterns(".git", "state", "__pycache__", ".env", "*.pyc"),
        )

        ledger_path = _find_ledger_path(sandbox)
        if ledger_path is None:
            return False, "找不到 projects账本.json 或等价物"

        projects = _load_ledger(ledger_path)
        if not projects:
            return False, "账本为空，没有可测试的项目"

        # 选第一个项目作为测试目标
        target = projects[0].copy()
        if "id" not in target and "name" not in target:
            target["id"] = "test-project-001"
        original_status = target.get("status", "unknown")
        target["status"] = "in_progress_test"

        # 第一次心跳前：确保目标项目在账本中
        projects[0] = target
        _save_ledger(ledger_path, projects)

        # === 第一次心跳 ===
        code1, out1 = _run_heartbeat_once(sandbox)
        if code1 != 0:
            return False, f"第一次心跳失败（退出码 {code1}）：{out1[:200]}"

        intent1 = _extract_intent(out1)
        print(f"  [第一次心跳] 意图类型: {intent1['kind']}, 项目: {intent1['project']}")

        # === 修改项目状态 ===
        projects[0]["status"] = "modified_for_continuity_test"
        projects[0]["last_heartbeat"] = "2024-01-01T00:00:00"  # 确保有时间戳可追溯
        _save_ledger(ledger_path, projects)
        print(f"  [修改后] 项目状态已改为: {projects[0]['status']}")

        # === 第二次心跳 ===
        code2, out2 = _run_heartbeat_once(sandbox)
        if code2 != 0:
            return False, f"第二次心跳失败（退出码 {code2}）：{out2[:200]}"

        intent2 = _extract_intent(out2)
        print(f"  [第二次心跳] 意图类型: {intent2['kind']}, 项目: {intent2['project']}")

        # === 断言：第二次心跳应该认出「续旧」而非「开新」===
        # 如果 form_intent 正确实现，它应该：
        # 1. 认出这是同一个项目（通过 id 或 name）
        # 2. 生成「续旧」意图而非「新开」意图
        if intent2["kind"] == "new_project":
            return False, (
                f"跨心跳连续性失败：第二次心跳识别为「开新项目」而非「续旧」。\n"
                f"  第一次: {intent1}\n"
                f"  第二次: {intent2}\n"
                f"  这说明 form_intent 没有记住上次心跳的项目状态。"
            )

        if intent2["kind"] == "continuation":
            return True, (
                f"✅ 跨心跳连续性验证通过：第二次心跳正确识别为「续旧」而非「开新」。\n"
                f"  项目: {intent2['project']}\n"
                f"  第一次意图: {intent1['kind']}\n"
                f"  第二次意图: {intent2['kind']}"
            )

        # unknown 类型：可能是输出格式变化，也可能是逻辑问题
        return False, (
            f"意图类型为「unknown」，无法判断连续性。\n"
            f"  输出片段: {intent2['raw_snippet']}\n"
            f"  请检查 form_intent 的输出格式。"
        )


def main() -> None:
    print("🏹 跨心跳项目连续性回归测试\n")
    print("目标：验证 form_intent 能认出「续旧」而非「开新」\n")

    ok, detail = test_cross_heartbeat_continuity()
    print(detail)
    print()

    if ok:
        print("🦀 回归测试通过：无跨心跳意图漂移")
        sys.exit(0)
    else:
        print("❌ 回归测试失败：form_intent 没有正确维持跨心跳连续性")
        sys.exit(1)


if __name__ == "__main__":
    main()
