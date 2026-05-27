import time
import json
from pathlib import Path

class AutonomyMeter:
    """追踪自改过程中的外部AI调用记录，提供brain-only状态检查"""
    
    def __init__(self, log_path="autonomy_audit.jsonl"):
        self.log_path = Path(log_path)
        self.current_session = {
            "session_id": str(int(time.time())),
            "start_time": time.time(),
            "external_calls": [],
            "brain_only": True
        }
    
    def record_external_call(self, tool_name, context=""):
        """记录一次外部AI调用"""
        call_record = {
            "timestamp": time.time(),
            "tool": tool_name,
            "context": context
        }
        self.current_session["external_calls"].append(call_record)
        self.current_session["brain_only"] = False
        
        # 写入日志文件
        self._write_log(call_record)
    
    def is_brain_only(self):
        """返回当前会话是否为纯脑力模式"""
        return self.current_session["brain_only"]
    
    def get_session_summary(self):
        """获取当前会话摘要"""
        return {
            "session_id": self.current_session["session_id"],
            "brain_only": self.current_session["brain_only"],
            "external_call_count": len(self.current_session["external_calls"]),
            "session_duration": time.time() - self.current_session["start_time"]
        }
    
    def _write_log(self, record):
        """写入JSONL日志"""
        log_entry = {
            "session_id": self.current_session["session_id"],
            **record
        }
        with open(self.log_path, "a") as f:
            f.write(json.dumps(log_entry) + "\n")

# 全局单例
meter = AutonomyMeter()

def check_brain_only():
    """便捷函数：检查当前会话是否为纯脑力模式"""
    return meter.is_brain_only()

def record_external_call(tool_name, context=""):
    """便捷函数：记录外部AI调用"""
    meter.record_external_call(tool_name, context)
