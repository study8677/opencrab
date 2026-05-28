#!/usr/bin/env python3
"""
闭环进化脚本：评测 → 弱点分析 → 训练 → 再评
实现完整的「评测→弱点→训练→再评」进化环
"""
import json
import sys
from datetime import datetime
from pathlib import Path

def main():
    print("=" * 60)
    print("🦀 开始闭环进化：评测→弱点→训练→再评")
    print("=" * 60)
    
    # 1. 运行基线评测
    print("\n📊 第一步：运行黄金基线评测...")
    try:
        from evalbench_golden_baseline import run_golden_baseline
        baseline_results = run_golden_baseline()
        
        if not baseline_results or 'score' not in baseline_results:
            print("❌ 基线评测失败：无法获取分数")
            return False
            
        baseline_score = baseline_results['score']
        weaknesses = baseline_results.get('weaknesses', [])
        
        print(f"✅ 基线评测完成，综合分数: {baseline_score:.2f}")
        print(f"   发现弱点方向: {len(weaknesses)}个")
        
        if not weaknesses:
            print("🎉 没有发现明显弱点，无需训练")
            return True
            
    except ImportError as e:
        print(f"❌ 无法导入评测模块: {e}")
        return False
    except Exception as e:
        print(f"❌ 基线评测异常: {e}")
        return False
    
    # 2. 分析最弱方向
    print("\n🔍 第二步：分析最弱方向...")
    try:
        # 按分数排序，找到最弱方向
        weaknesses.sort(key=lambda x: x.get('score', 1.0))
        weakest = weaknesses[0] if weaknesses else None
        
        if not weakest:
            print("⚠️  未找到明确的弱点方向")
            return True
            
        weakness_name = weakest.get('name', 'unknown')
        weakness_score = weakest.get('score', 0.0)
        
        print(f"🎯 最弱方向: {weakness_name} (得分: {weakness_score:.2f})")
        
    except Exception as e:
        print(f"❌ 弱点分析异常: {e}")
        return False
    
    # 3. 针对性训练
    print("\n🏋️ 第三步：针对性训练...")
    try:
        from train_weakness import train_on_weakness
        
        training_results = train_on_weakness(
            weakness_name=weakness_name,
            baseline_results=baseline_results,
            intensity="moderate"  # 中等强度训练
        )
        
        if not training_results or not training_results.get('success'):
            print(f"❌ 训练失败: {training_results.get('error', '未知错误')}")
            return False
            
        print(f"✅ 训练完成")
        print(f"   训练轮次: {training_results.get('rounds', 0)}")
        print(f"   改善幅度: {training_results.get('improvement', 0):.2f}")
        
    except ImportError as e:
        print(f"❌ 无法导入训练模块: {e}")
        return False
    except Exception as e:
        print(f"❌ 训练异常: {e}")
        return False
    
    # 4. 再次评测
    print("\n📈 第四步：再次评测...")
    try:
        # 运行训练后的评测
        post_training_results = run_golden_baseline()
        
        if not post_training_results or 'score' not in post_training_results:
            print("❌ 再次评测失败")
            return False
            
        post_score = post_training_results['score']
        improvement = post_score - baseline_score
        
        print(f"✅ 再次评测完成")
        print(f"   训练前分数: {baseline_score:.2f}")
        print(f"   训练后分数: {post_score:.2f}")
        print(f"   改善幅度: {improvement:+.2f}")
        
        # 检查弱点是否改善
        post_weaknesses = post_training_results.get('weaknesses', [])
        weakness_improved = False
        
        for w in post_weaknesses:
            if w.get('name') == weakness_name:
                old_score = weakness_score
                new_score = w.get('score', 0.0)
                if new_score > old_score:
                    weakness_improved = True
                    print(f"   💪 弱点 '{weakness_name}' 改善: {old_score:.2f} → {new_score:.2f}")
                else:
                    print(f"   ⚠️  弱点 '{weakness_name}' 未改善: {old_score:.2f} → {new_score:.2f}")
                break
        
        # 5. 保存证据
        print("\n📝 第五步：保存证据...")
        evidence = {
            "timestamp": datetime.now().isoformat(),
            "baseline_score": baseline_score,
            "post_score": post_score,
            "improvement": improvement,
            "weakness_targeted": weakness_name,
            "weakness_improved": weakness_improved,
            "training_rounds": training_results.get('rounds', 0),
            "success": improvement > 0
        }
        
        evidence_path = Path("evidence/close_loop_results.jsonl")
        evidence_path.parent.mkdir(exist_ok=True)
        
        with open(evidence_path, "a") as f:
            f.write(json.dumps(evidence) + "\n")
            
        print(f"✅ 证据已保存: {evidence_path}")
        
        if improvement > 0:
            print("\n" + "=" * 60)
            print("🎉 闭环进化成功！系统能力得到提升")
            print("=" * 60)
            return True
        else:
            print("\n" + "=" * 60)
            print("⚠️  闭环进化完成，但未观察到显著提升")
            print("    建议调整训练策略或弱点分析")
            print("=" * 60)
            return False
            
    except Exception as e:
        print(f"❌ 再次评测异常: {e}")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
