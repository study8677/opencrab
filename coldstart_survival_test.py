"""离线冷启动生存实跑测试"""
import sys
import os

# 强制离线模式
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("CRAB_API_KEY", None)

from coldstart_survival import survival_run

def test_survival():
    result = survival_run()
    assert result["overall"] == "SURVIVED", f"生存实跑失败: {result}"
    assert result["steps"]["health"]["offline"] is True
    assert result["steps"]["onboarding"]["offline"] is True
    print("✅ 离线冷启动生存实跑通过!")
    return True

if __name__ == "__main__":
    success = test_survival()
    sys.exit(0 if success else 1)
