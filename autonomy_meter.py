import time
import json
from pathlib import Path


class AutonomyMeter:
    """追踪自改过程中的外部AI调用与brain-only落地证据，给出可运行自主度评分"""

    def __init__(self, log_path="autonomy_audit.jsonl"):
        self.log_path = Path(log_path)
        self.current_session = {
            "session_id": str(int(time.time())),
            "start_time": time.time(),
            "external_calls": [],
            "brain_only_landings": [],
            "brain_only": True
        }

    def record_external_call(self, tool_name, context=""):
        """记录一次外部AI调用"""
        call_record = {
            "event": "external_call",
            "timestamp": time.time(),
            "tool": tool_name,
            "context": context
        }
        self.current_session["external_calls"].append(call_record)
        self.current_session["brain_only"] = False
        self._write_log(call_record)

    def record_brain_only_landing(self, task="", evidence="", passed=True):
        """记录一次brain-only落地证据：没有外援、可复验、最好带测试/编译/运行结果"""
        landing_record = {
            "event": "brain_only_landing",
            "timestamp": time.time(),
            "task": task,
            "evidence": evidence,
            "passed": bool(passed),
            "brain_only": self.current_session["brain_only"]
        }
        self.current_session["brain_only_landings"].append(landing_record)
        self._write_log(landing_record)

    def is_brain_only(self):
        """返回当前会话是否为纯脑力模式"""
        return self.current_session["brain_only"]

    def get_session_summary(self):
        """获取当前会话摘要"""
        return {
            "session_id": self.current_session["session_id"],
            "brain_only": self.current_session["brain_only"],
            "external_call_count": len(self.current_session["external_calls"]),
            "brain_only_landing_count": len(self.current_session["brain_only_landings"]),
            "session_duration": time.time() - self.current_session["start_time"]
        }

    def autonomy_score(self, window_days=14):
        """计算自主度评分：brain-only落地率、外援残留、证据新鲜度 -> 0..100"""
        events = self._load_events()
        events.extend(self._current_session_events())

        now = time.time()
        window_seconds = max(float(window_days), 0.001) * 86400.0
        fresh_cutoff = now - window_seconds
        fresh_events = [
            event for event in events
            if self._event_time(event) >= fresh_cutoff
        ]

        landing_events = [
            event for event in fresh_events
            if event.get("event") == "brain_only_landing"
        ]
        passed_landings = [
            event for event in landing_events
            if event.get("passed", True) and event.get("brain_only", True)
        ]
        external_calls = [
            event for event in fresh_events
            if event.get("event") == "external_call"
        ]

        landing_rate = self._safe_ratio(len(passed_landings), len(landing_events))
        residue_ratio = self._safe_ratio(len(external_calls), len(fresh_events))
        external_residue_score = 1.0 - min(1.0, residue_ratio)
        freshness_score = self._freshness_score(events, now, window_seconds)

        total = (
            45.0 * landing_rate +
            35.0 * external_residue_score +
            20.0 * freshness_score
        )

        return {
            "score": round(total, 2),
            "brain_only_landing_rate": round(landing_rate, 4),
            "external_residue_ratio": round(residue_ratio, 4),
            "evidence_freshness": round(freshness_score, 4),
            "window_days": window_days,
            "counts": {
                "fresh_events": len(fresh_events),
                "brain_only_landings": len(landing_events),
                "passed_brain_only_landings": len(passed_landings),
                "external_calls": len(external_calls)
            },
            "verdict": self._verdict(total)
        }

    def autonomy_report(self, window_days=14):
        """返回适合人工阅读的自主度报告"""
        score = self.autonomy_score(window_days=window_days)
        counts = score["counts"]
        return (
            f"autonomy_score={score['score']} verdict={score['verdict']} "
            f"brain_only_landing_rate={score['brain_only_landing_rate']} "
            f"external_residue_ratio={score['external_residue_ratio']} "
            f"evidence_freshness={score['evidence_freshness']} "
            f"fresh_events={counts['fresh_events']} "
            f"landings={counts['brain_only_landings']} "
            f"external_calls={counts['external_calls']}"
        )

    def _write_log(self, record):
        """写入JSONL日志"""
        log_entry = {
            "session_id": self.current_session["session_id"],
            **record
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    def _load_events(self):
        if not self.log_path.exists():
            return []

        events = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "event" not in event:
                    event["event"] = "external_call"
                events.append(event)
        return events

    def _current_session_events(self):
        events = []
        events.extend(self.current_session["external_calls"])
        events.extend(self.current_session["brain_only_landings"])
        return events

    @staticmethod
    def _event_time(event):
        try:
            return float(event.get("timestamp", 0.0))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _safe_ratio(numerator, denominator):
        if denominator <= 0:
            return 0.0
        return float(numerator) / float(denominator)

    @staticmethod
    def _freshness_score(events, now, window_seconds):
        if not events:
            return 0.0
        newest = max(AutonomyMeter._event_time(event) for event in events)
        age = max(0.0, now - newest)
        return max(0.0, 1.0 - age / window_seconds)

    @staticmethod
    def _verdict(score):
        if score >= 85:
            return "independent"
        if score >= 65:
            return "mostly_autonomous"
        if score >= 40:
            return "mixed"
        return "dependent"


# 全局单例
meter = AutonomyMeter()


def check_brain_only():
    """便捷函数：检查当前会话是否为纯脑力模式"""
    return meter.is_brain_only()


def record_external_call(tool_name, context=""):
    """便捷函数：记录外部AI调用"""
    meter.record_external_call(tool_name, context)


def record_brain_only_landing(task="", evidence="", passed=True):
    """便捷函数：记录brain-only落地证据"""
    meter.record_brain_only_landing(task=task, evidence=evidence, passed=passed)


def autonomy_score(window_days=14):
    """便捷函数：计算自主度评分"""
    return meter.autonomy_score(window_days=window_days)


def autonomy_report(window_days=14):
    """便捷函数：生成自主度报告"""
    return meter.autonomy_report(window_days=window_days)
