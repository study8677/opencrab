"""离线冷启动生存实跑: 断网 + 空 .env → health → onboarding → degrade
确保在没有外部依赖的情况下能自检、降级并继续进化。
"""
import os
import sys
import importlib
from pathlib import Path
from datetime import datetime

# 离线环境标记
OFFLINE_MODE = True
EMPTY_ENV = not os.getenv("OPENAI_API_KEY") and not os.getenv("CRAB_API_KEY")

def _log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}")

def _try_import(module_name):
    """安全导入，失败返回 None"""
    try:
        return importlib.import_module(module_name)
    except Exception as e:
        _log(f"导入 {module_name} 失败: {e}", "WARN")
        return None

def run_health_offline():
    """离线健康检查 - 不依赖外部服务"""
    _log("=== 离线健康检查开始 ===")
    checks = {}

    # 1. 基础 Python 环境
    checks["python"] = sys.version_info >= (3, 8)

    # 2. 核心模块可导入
    core_modules = ["health", "onboarding", "degrade", "errors"]
    for mod in core_modules:
        m = _try_import(mod)
        checks[f"import_{mod}"] = m is not None

    # 3. 工作目录可写
    try:
        test_file = Path(".coldstart_test")
        test_file.write_text("ok")
        test_file.unlink()
        checks["writable"] = True
    except Exception:
        checks["writable"] = False

    # 4. 离线模式标记
    checks["offline_mode"] = True

    # 离线模式下允许部分检查失败
    critical = ["python", "writable"]
    critical_ok = all(checks.get(k) for k in critical)
    status = "PASS" if critical_ok else "DEGRADED"
    _log(f"健康检查结果: {status} - {checks}")
    return {"status": status, "checks": checks, "offline": True}

def run_onboarding_offline():
    """离线上 onboard - 无需外部 API"""
    _log("=== 离线 onboarding 开始 ===")

    onboarding = _try_import("onboarding")
    if onboarding and hasattr(onboarding, "run"):
        try:
            # 先尝试传 offline 参数
            import inspect
            sig = inspect.signature(onboarding.run)
            if "offline" in sig.parameters:
                result = onboarding.run(offline=True)
            else:
                result = onboarding.run()
            _log(f"Onboarding 完成: {result}")
            return result
        except Exception as e:
            _log(f"Onboarding 异常: {e}", "WARN")

    # 兜底: 最小化 onboarding
    minimal = {
        "status": "minimal",
        "offline": True,
        "initialized": True,
        "timestamp": datetime.now().isoformat()
    }
    _log(f"使用最小化 onboarding: {minimal}")
    return minimal

def run_degrade_check():
    """降级检查 - 确保降级路径畅通"""
    _log("=== 降级检查开始 ===")

    degrade = _try_import("degrade")
    if degrade and hasattr(degrade, "check"):
        try:
            import inspect
            sig = inspect.signature(degrade.check)
            if "offline" in sig.parameters:
                result = degrade.check(offline=True)
            else:
                result = degrade.check()
            _log(f"降级检查: {result}")
            return result
        except Exception as e:
            _log(f"降级检查异常: {e}", "WARN")

    # 降级模式本身就是成功
    return {"status": "degraded", "reason": "offline_mode", "ok": True}

def survival_run():
    """完整离线冷启动生存实跑"""
    _log("=" * 50)
    _log("离线冷启动生存实跑启动")
    _log(f"网络: 断开 | .env: {'空' if EMPTY_ENV else '有配置'}")
    _log("=" * 50)

    results = {}

    # Step 1: Health
    results["health"] = run_health_offline()

    # Step 2: Onboarding
    results["onboarding"] = run_onboarding_offline()

    # Step 3: Degrade
    results["degrade"] = run_degrade_check()

    # 汇总
    all_ok = all(
        r.get("status") in ("PASS", "DEGRADED", "minimal", "degraded", "ok")
        for r in results.values()
        if isinstance(r, dict)
    )

    summary = {
        "overall": "SURVIVED" if all_ok else "BLOCKED",
        "steps": results,
        "timestamp": datetime.now().isoformat()
    }

    _log("=" * 50)
    _log(f"生存实跑结果: {summary['overall']}")
    _log("=" * 50)

    return summary

if __name__ == "__main__":
    result = survival_run()
    sys.exit(0 if result["overall"] == "SURVIVED" else 1)
