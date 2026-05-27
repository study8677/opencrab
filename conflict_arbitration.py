import os
import json
from typing import Dict, Any, Optional, List, Tuple


class ConflictArbitrator:
    """Conflict arbitration helpers.

    The original source-vs-source conflict checks are kept for compatibility.
    The plan arbitration contract added here is intentionally small:
    - input: a list of strategy plans (dicts)
    - conflict key: action target/path/file/name/id
    - conflict: same target with different operation/value signatures
    - winner: highest score, then lowest input order, then stable plan id
    - output: JSON-serialisable audit dict
    """

    ARBITRATION_SCHEMA_VERSION = "conflict-arbitration.v1"

    def __init__(self, evidence_path: str = 'evidence.py', replay_path: str = 'replay.py', readme_path: str = 'README.md'):
        self.evidence_path = evidence_path
        self.replay_path = replay_path
        self.readme_path = readme_path
        self.evidence_data = None
        self.replay_data = None
        self.readme_content = None

    def load_data(self):
        """加载证据账本、回放结果和README内容。"""
        # 尝试导入 evidence 模块获取数据
        try:
            import evidence
            if hasattr(evidence, 'get_ledger'):
                self.evidence_data = evidence.get_ledger()
            else:
                self.evidence_data = getattr(evidence, 'LEDGER', {})
        except ImportError:
            self.evidence_data = {}

        # 尝试导入 replay 模块获取数据
        try:
            import replay
            if hasattr(replay, 'get_results'):
                self.replay_data = replay.get_results()
            else:
                self.replay_data = getattr(replay, 'RESULTS', {})
        except ImportError:
            self.replay_data = {}

        # 读取 README 文件
        if os.path.exists(self.readme_path):
            with open(self.readme_path, 'r', encoding='utf-8') as f:
                self.readme_content = f.read()
        else:
            self.readme_content = ''

    def extract_evidence_claims(self) -> Dict[str, Any]:
        """从证据账本提取声明（键值对）。"""
        return self.evidence_data or {}

    def extract_replay_claims(self) -> Dict[str, Any]:
        """从回放结果提取声明（键值对）。"""
        return self.replay_data or {}

    def extract_readme_claims(self) -> Dict[str, Any]:
        """从 README 提取声明（简单键值对解析）。"""
        claims = {}
        if self.readme_content:
            lines = self.readme_content.split('\n')
            for line in lines:
                if ':' in line:
                    key, value = line.split(':', 1)
                    claims[key.strip()] = value.strip()
        return claims

    def check_conflicts(self) -> Dict[str, Any]:
        """检查三个数据源之间的冲突。返回冲突详情字典。"""
        evidence_claims = self.extract_evidence_claims()
        replay_claims = self.extract_replay_claims()
        readme_claims = self.extract_readme_claims()

        conflicts = {}
        # 比较证据与回放
        for key in set(evidence_claims.keys()) & set(replay_claims.keys()):
            if evidence_claims[key] != replay_claims[key]:
                conflicts[key] = {
                    'evidence': evidence_claims[key],
                    'replay': replay_claims[key],
                    'readme': readme_claims.get(key, 'N/A')
                }
        # 比较证据与 README
        for key in set(evidence_claims.keys()) & set(readme_claims.keys()):
            if evidence_claims[key] != readme_claims[key]:
                if key not in conflicts:
                    conflicts[key] = {
                        'evidence': evidence_claims[key],
                        'replay': replay_claims.get(key, 'N/A'),
                        'readme': readme_claims[key]
                    }
                else:
                    conflicts[key]['readme'] = readme_claims[key]
        # 比较回放与 README
        for key in set(replay_claims.keys()) & set(readme_claims.keys()):
            if replay_claims[key] != readme_claims[key]:
                if key not in conflicts:
                    conflicts[key] = {
                        'evidence': evidence_claims.get(key, 'N/A'),
                        'replay': replay_claims[key],
                        'readme': readme_claims[key]
                    }
                else:
                    conflicts[key]['readme'] = readme_claims[key]
        return conflicts

    def generate_recheck_command(self, conflicts: Dict[str, Any]) -> str:
        """基于冲突生成最小复验命令字符串。"""
        if not conflicts:
            return "echo 'No conflicts detected.'"
        # 生成一个 Python 命令来重新运行仲裁并打印冲突详情
        cmd = (
            "python -c \""
            "from conflict_arbitration import ConflictArbitrator; "
            "a = ConflictArbitrator(); a.load_data(); "
            "c = a.check_conflicts(); print(c)\""
        )
        return cmd

    @staticmethod
    def _jsonable(value: Any) -> Any:
        """Return a deterministic JSON-safe value."""
        try:
            json.dumps(value, sort_keys=True, ensure_ascii=False)
            return value
        except (TypeError, ValueError):
            return repr(value)

    @staticmethod
    def _stable_text(value: Any) -> str:
        return json.dumps(ConflictArbitrator._jsonable(value), sort_keys=True, ensure_ascii=False, separators=(',', ':'))

    @staticmethod
    def _as_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _normalise_plan(self, plan: Dict[str, Any], index: int) -> Dict[str, Any]:
        if not isinstance(plan, dict):
            plan = {"plan": plan}
        plan_id = str(plan.get("id") or plan.get("plan_id") or plan.get("name") or "plan-%d" % index)
        actions = plan.get("actions", [])
        if actions is None:
            actions = []
        if not isinstance(actions, list):
            actions = [actions]
        priority = self._as_float(plan.get("priority", 0.0))
        confidence = self._as_float(plan.get("confidence", 0.0))
        risk = self._as_float(plan.get("risk", 0.0))
        evidence_items = plan.get("evidence", [])
        if evidence_items is None:
            evidence_items = []
        if not isinstance(evidence_items, list):
            evidence_items = [evidence_items]
        score = round(priority * 100.0 + confidence * 10.0 + len(evidence_items) - risk * 25.0, 6)
        return {
            "id": plan_id,
            "strategy": str(plan.get("strategy") or plan.get("source") or plan_id),
            "input_order": index,
            "priority": priority,
            "confidence": confidence,
            "risk": risk,
            "evidence_count": len(evidence_items),
            "score": score,
            "actions": actions,
        }

    def _normalise_action(self, action: Any, action_index: int) -> Dict[str, Any]:
        if isinstance(action, dict):
            target = action.get("target") or action.get("path") or action.get("file") or action.get("name") or action.get("id")
            operation = action.get("op") or action.get("operation") or action.get("type") or action.get("kind") or "change"
            value = action.get("value", action.get("content", action.get("patch", action.get("args", ""))))
        else:
            text = str(action)
            target = text
            operation = text.split(None, 1)[0] if text.split(None, 1) else "change"
            value = text
        if target is None:
            target = "action-%d" % action_index
        return {
            "target": str(target),
            "operation": str(operation),
            "value": self._jsonable(value),
            "signature": "%s:%s" % (str(operation), self._stable_text(value)),
        }

    def arbitrate_plans(self, plans: List[Dict[str, Any]], contract: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Arbitrate conflicting multi-strategy plans and return an auditable dict.

        Minimal contract:
        plans = [
            {
                "id": "planner-a",
                "strategy": "fast_fix",
                "priority": 1,
                "confidence": 0.7,
                "risk": 0.2,
                "evidence": ["test-x"],
                "actions": [{"target": "crab.py", "op": "edit", "value": "..."}],
            }
        ]

        The result is JSON-serialisable and deterministic.
        """
        contract = contract or {}
        normalised = [self._normalise_plan(plan, index) for index, plan in enumerate(plans or [])]
        by_target: Dict[str, List[Dict[str, Any]]] = {}
        selected_actions: List[Dict[str, Any]] = []
        rejected_actions: List[Dict[str, Any]] = []
        conflicts: List[Dict[str, Any]] = []
        decisions: List[Dict[str, Any]] = []

        for plan in normalised:
            for action_index, action in enumerate(plan["actions"]):
                item = self._normalise_action(action, action_index)
                item.update({
                    "plan_id": plan["id"],
                    "strategy": plan["strategy"],
                    "input_order": plan["input_order"],
                    "score": plan["score"],
                    "action_index": action_index,
                    "raw_action": self._jsonable(action),
                })
                by_target.setdefault(item["target"], []).append(item)

        for target in sorted(by_target):
            contenders = by_target[target]
            signatures = {item["signature"] for item in contenders}
            if len(signatures) <= 1:
                for item in sorted(contenders, key=lambda x: (x["input_order"], x["action_index"], x["plan_id"])):
                    selected_actions.append(item)
                continue

            ranked = sorted(contenders, key=lambda x: (-x["score"], x["input_order"], x["plan_id"], x["action_index"]))
            winner = ranked[0]
            losers = ranked[1:]
            conflict = {
                "target": target,
                "reason": "same target has incompatible action signatures",
                "winner_plan_id": winner["plan_id"],
                "winner_signature": winner["signature"],
                "contenders": [
                    {
                        "plan_id": item["plan_id"],
                        "strategy": item["strategy"],
                        "action_index": item["action_index"],
                        "operation": item["operation"],
                        "signature": item["signature"],
                        "score": item["score"],
                        "input_order": item["input_order"],
                    }
                    for item in ranked
                ],
            }
            decision = {
                "target": target,
                "policy": "highest_score_then_input_order",
                "winner_plan_id": winner["plan_id"],
                "rejected_plan_ids": [item["plan_id"] for item in losers],
                "score_explanation": "score = priority*100 + confidence*10 + evidence_count - risk*25",
            }
            conflicts.append(conflict)
            decisions.append(decision)
            selected_actions.append(winner)
            rejected_actions.extend(losers)

        audit = {
            "schema_version": self.ARBITRATION_SCHEMA_VERSION,
            "status": "conflicts_resolved" if conflicts else "no_conflicts",
            "contract": self._jsonable(contract),
            "plan_count": len(normalised),
            "policy": "highest_score_then_input_order",
            "plans": [
                {
                    "id": plan["id"],
                    "strategy": plan["strategy"],
                    "input_order": plan["input_order"],
                    "priority": plan["priority"],
                    "confidence": plan["confidence"],
                    "risk": plan["risk"],
                    "evidence_count": plan["evidence_count"],
                    "score": plan["score"],
                    "action_count": len(plan["actions"]),
                }
                for plan in normalised
            ],
            "conflicts": conflicts,
            "decisions": decisions,
            "accepted_plan_ids": sorted({item["plan_id"] for item in selected_actions}),
            "rejected_plan_ids": sorted({item["plan_id"] for item in rejected_actions}),
            "selected_actions": [
                {
                    "plan_id": item["plan_id"],
                    "strategy": item["strategy"],
                    "target": item["target"],
                    "operation": item["operation"],
                    "signature": item["signature"],
                    "score": item["score"],
                    "raw_action": item["raw_action"],
                }
                for item in sorted(selected_actions, key=lambda x: (x["target"], x["input_order"], x["action_index"], x["plan_id"]))
            ],
            "rejected_actions": [
                {
                    "plan_id": item["plan_id"],
                    "strategy": item["strategy"],
                    "target": item["target"],
                    "operation": item["operation"],
                    "signature": item["signature"],
                    "score": item["score"],
                    "raw_action": item["raw_action"],
                }
                for item in sorted(rejected_actions, key=lambda x: (x["target"], x["input_order"], x["action_index"], x["plan_id"]))
            ],
            "recheck_command": (
                "python -c \"import json; "
                "from conflict_arbitration import ConflictArbitrator; "
                "print(json.dumps(ConflictArbitrator().arbitrate_plans([]), sort_keys=True, ensure_ascii=False))\""
            ),
        }
        json.dumps(audit, sort_keys=True, ensure_ascii=False)
        return audit

    def arbitrate_plans_json(self, plans: List[Dict[str, Any]], contract: Optional[Dict[str, Any]] = None, indent: int = 2) -> str:
        """Return the plan arbitration audit as deterministic JSON text."""
        return json.dumps(self.arbitrate_plans(plans, contract=contract), sort_keys=True, ensure_ascii=False, indent=indent)


# 便捷函数
def arbitrate_conflicts() -> str:
    """检查冲突并返回复验命令。"""
    arbitrator = ConflictArbitrator()
    arbitrator.load_data()
    conflicts = arbitrator.check_conflicts()
    return arbitrator.generate_recheck_command(conflicts)


def arbitrate_plans(plans: List[Dict[str, Any]], contract: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Convenience wrapper for the minimal plan arbitration contract."""
    return ConflictArbitrator().arbitrate_plans(plans, contract=contract)


def arbitrate_plans_json(plans: List[Dict[str, Any]], contract: Optional[Dict[str, Any]] = None, indent: int = 2) -> str:
    """Convenience wrapper returning an auditable JSON arbitration report."""
    return ConflictArbitrator().arbitrate_plans_json(plans, contract=contract, indent=indent)


if __name__ == '__main__':
    print(arbitrate_conflicts())
