"""
evolution_mirror.py – 实时进化动态板块生成器
自动从 timeline、evidence、skillgraph 等模块提取数据，
生成一个可嵌入展示页的动态进化状态镜面。
"""

import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import importlib

def _safe_import(module_name: str):
    """安全导入模块，避免因单个模块缺失导致整体失败"""
    try:
        return importlib.import_module(module_name)
    except ImportError:
        return None

def get_evolution_snapshot() -> Dict[str, Any]:
    """获取当前进化状态快照"""
    snapshot = {
        "timestamp": time.time(),
        "human_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "modules_available": {},
        "recent_activities": [],
        "evidence_state": {},
        "skill_growth": {},
        "milestones": [],
        "health_indicators": {},
        "display_ready": False
    }
    
    # 1. 检查哪些模块可用
    modules_to_check = [
        "timeline", "evidence", "skillgraph", "health", "milestone", "trustscore"
    ]
    
    for mod_name in modules_to_check:
        snapshot["modules_available"][mod_name] = importlib.util.find_spec(mod_name) is not None
    
    # 2. 从 timeline 提取最近活动
    if snapshot["modules_available"]["timeline"]:
        try:
            timeline = importlib.import_module("timeline")
            if hasattr(timeline, "get_recent_events"):
                recent_events = timeline.get_recent_events(limit=5)
                snapshot["recent_activities"] = recent_events
        except Exception as e:
            snapshot["recent_activities"] = [{"error": f"Timeline access error: {str(e)}"}]
    
    # 3. 从 evidence 提取证据状态
    if snapshot["modules_available"]["evidence"]:
        try:
            evidence = importlib.import_module("evidence")
            if hasattr(evidence, "get_evidence_summary"):
                evidence_summary = evidence.get_evidence_summary()
                snapshot["evidence_state"] = evidence_summary
            elif hasattr(evidence, "count_evidence"):
                # 备用方案：至少获取证据数量
                total = evidence.count_evidence()
                snapshot["evidence_state"] = {
                    "total_evidence": total,
                    "source": "count_fallback"
                }
        except Exception as e:
            snapshot["evidence_state"] = {"error": f"Evidence access error: {str(e)}"}
    
    # 4. 从 skillgraph 提取技能增长数据
    if snapshot["modules_available"]["skillgraph"]:
        try:
            skillgraph = importlib.import_module("skillgraph")
            if hasattr(skillgraph, "get_growth_metrics"):
                growth_metrics = skillgraph.get_growth_metrics()
                snapshot["skill_growth"] = growth_metrics
            elif hasattr(skillgraph, "get_skill_count"):
                # 备用方案：至少获取技能数量
                skill_count = skillgraph.get_skill_count()
                snapshot["skill_growth"] = {
                    "total_skills": skill_count,
                    "source": "count_fallback"
                }
        except Exception as e:
            snapshot["skill_growth"] = {"error": f"Skillgraph access error: {str(e)}"}
    
    # 5. 从 health 提取健康指标
    if snapshot["modules_available"]["health"]:
        try:
            health = importlib.import_module("health")
            if hasattr(health, "get_health_status"):
                health_status = health.get_health_status()
                snapshot["health_indicators"] = health_status
        except Exception as e:
            snapshot["health_indicators"] = {"error": f"Health access error: {str(e)}"}
    
    # 6. 从 milestone 提取里程碑（如果存在）
    if snapshot["modules_available"].get("milestone", False):
        try:
            milestone = importlib.import_module("milestone")
            if hasattr(milestone, "get_recent_milestones"):
                milestones = milestone.get_recent_milestones(limit=3)
                snapshot["milestones"] = milestones
        except Exception as e:
            snapshot["milestones"] = [{"error": f"Milestone access error: {str(e)}"}]
    
    # 7. 标记数据准备就绪
    snapshot["display_ready"] = bool(
        snapshot["recent_activities"] or 
        snapshot["evidence_state"] or 
        snapshot["skill_growth"] or 
        snapshot["milestones"]
    )
    
    return snapshot

def generate_html_mirror(snapshot: Dict[str, Any]) -> str:
    """生成 HTML 格式的进化动态板块"""
    if not snapshot.get("display_ready"):
        return '<div class="evolution-mirror error">进化数据获取中...</div>'
    
    html_parts = []
    html_parts.append('<div class="evolution-mirror">')
    html_parts.append(f'<h3>🦐 实时进化动态 <small>更新于 {snapshot["human_time"]}</small></h3>')
    
    # 最近活动部分
    if snapshot["recent_activities"]:
        html_parts.append('<div class="mirror-section">')
        html_parts.append('<h4>🚀 最近活动</h4>')
        html_parts.append('<ul class="activity-list">')
        for activity in snapshot["recent_activities"][:3]:  # 只显示前3条
            if isinstance(activity, dict):
                time_str = activity.get("time", activity.get("timestamp", "未知时间"))
                desc = activity.get("description", activity.get("event", "未知活动"))
                html_parts.append(f'<li><span class="time">{time_str}</span> {desc}</li>')
        html_parts.append('</ul>')
        html_parts.append('</div>')
    
    # 证据状态部分
    if snapshot["evidence_state"] and not snapshot["evidence_state"].get("error"):
        html_parts.append('<div class="mirror-section">')
        html_parts.append('<h4>🔍 证据状态</h4>')
        evidence = snapshot["evidence_state"]
        if "total_evidence" in evidence:
            html_parts.append(f'<p>累计证据: <strong>{evidence["total_evidence"]}</strong> 项</p>')
        if "quality_score" in evidence:
            html_parts.append(f'<p>证据质量: <strong>{evidence["quality_score"]}</strong></p>')
        if "latest_source" in evidence:
            html_parts.append(f'<p>最新来源: <em>{evidence["latest_source"]}</em></p>')
        html_parts.append('</div>')
    
    # 技能增长部分
    if snapshot["skill_growth"] and not snapshot["skill_growth"].get("error"):
        html_parts.append('<div class="mirror-section">')
        html_parts.append('<h4>📈 技能增长</h4>')
        skills = snapshot["skill_growth"]
        if "total_skills" in skills:
            html_parts.append(f'<p>掌握技能: <strong>{skills["total_skills"]}</strong> 项</p>')
        if "new_this_week" in skills:
            html_parts.append(f'<p>本周新增: <strong>+{skills["new_this_week"]}</strong></p>')
        if "top_skills" in skills:
            html_parts.append('<p>热门技能: ')
            html_parts.append(", ".join(skills["top_skills"][:3]))
            html_parts.append('</p>')
        html_parts.append('</div>')
    
    # 健康指标部分
    if snapshot["health_indicators"] and not snapshot["health_indicators"].get("error"):
        html_parts.append('<div class="mirror-section">')
        html_parts.append('<h4>💓 系统健康</h4>')
        health = snapshot["health_indicators"]
        if "overall_score" in health:
            score = health["overall_score"]
            color = "#2ecc71" if score > 0.7 else "#f39c12" if score > 0.4 else "#e74c3c"
            html_parts.append(f'<p>整体健康: <strong style="color:{color}">{score:.2f}</strong></p>')
        if "active_modules" in health:
            html_parts.append(f'<p>活跃模块: {health["active_modules"]}</p>')
        html_parts.append('</div>')
    
    # 里程碑部分
    if snapshot["milestones"]:
        html_parts.append('<div class="mirror-section">')
        html_parts.append('<h4>🏆 近期里程碑</h4>')
        html_parts.append('<ul class="milestone-list">')
        for milestone in snapshot["milestones"][:2]:  # 只显示最近2个
            if isinstance(milestone, dict):
                name = milestone.get("name", milestone.get("title", "未知里程碑"))
                date = milestone.get("date", "")
                html_parts.append(f'<li><strong>{name}</strong> {f"<small>({date})</small>" if date else ""}</li>')
        html_parts.append('</ul>')
        html_parts.append('</div>')
    
    # 底部信息
    modules_available = [mod for mod, available in snapshot["modules_available"].items() if available]
    html_parts.append(f'<div class="mirror-footer">')
    html_parts.append(f'<small>数据来源: {", ".join(modules_available) if modules_available else "本地缓存"}</small>')
    html_parts.append('</div>')
    
    html_parts.append('</div>')
    
    return "\n".join(html_parts)

def generate_text_mirror(snapshot: Dict[str, Any]) -> str:
    """生成纯文本格式的进化动态板块"""
    if not snapshot.get("display_ready"):
        return "进化数据获取中..."
    
    text_parts = []
    text_parts.append(f"🦐 实时进化动态 ({snapshot['human_time']})")
    text_parts.append("=" * 50)
    
    # 最近活动
    if snapshot["recent_activities"]:
        text_parts.append("\n🚀 最近活动:")
        for activity in snapshot["recent_activities"][:3]:
            if isinstance(activity, dict):
                time_str = activity.get("time", activity.get("timestamp", "?"))
                desc = activity.get("description", activity.get("event", "?"))
                text_parts.append(f"  • [{time_str}] {desc}")
    
    # 证据状态
    if snapshot["evidence_state"] and not snapshot["evidence_state"].get("error"):
        evidence = snapshot["evidence_state"]
        text_parts.append("\n🔍 证据状态:")
        if "total_evidence" in evidence:
            text_parts.append(f"  • 累计证据: {evidence['total_evidence']} 项")
        if "quality_score" in evidence:
            text_parts.append(f"  • 证据质量: {evidence['quality_score']:.2f}")
        if "latest_source" in evidence:
            text_parts.append(f"  • 最新来源: {evidence['latest_source']}")
    
    # 技能增长
    if snapshot["skill_growth"] and not snapshot["skill_growth"].get("error"):
        skills = snapshot["skill_growth"]
        text_parts.append("\n📈 技能增长:")
        if "total_skills" in skills:
            text_parts.append(f"  • 掌握技能: {skills['total_skills']} 项")
        if "new_this_week" in skills:
            text_parts.append(f"  • 本周新增: +{skills['new_this_week']}")
        if "top_skills" in skills:
            text_parts.append(f"  • 热门技能: {', '.join(skills['top_skills'][:3])}")
    
    # 健康指标
    if snapshot["health_indicators"] and not snapshot["health_indicators"].get("error"):
        health = snapshot["health_indicators"]
        text_parts.append("\n💓 系统健康:")
        if "overall_score" in health:
            score = health["overall_score"]
            status = "良好" if score > 0.7 else "一般" if score > 0.4 else "需关注"
            text_parts.append(f"  • 整体健康: {score:.2f} ({status})")
        if "active_modules" in health:
            text_parts.append(f"  • 活跃模块: {health['active_modules']}")
    
    # 里程碑
    if snapshot["milestones"]:
        text_parts.append("\n🏆 近期里程碑:")
        for milestone in snapshot["milestones"][:2]:
            if isinstance(milestone, dict):
                name = milestone.get("name", milestone.get("title", "?"))
                date = milestone.get("date", "")
                text_parts.append(f"  • {name} {f'({date})' if date else ''}")
    
    text_parts.append("\n" + "=" * 50)
    modules_available = [mod for mod, available in snapshot["modules_available"].items() if available]
    text_parts.append(f"数据来源: {', '.join(modules_available) if modules_available else '本地缓存'}")
    
    return "\n".join(text_parts)

def refresh_and_display(format: str = "html") -> str:
    """
    刷新并返回进化动态板块
    
    Args:
        format: 输出格式，"html" 或 "text"
    
    Returns:
        格式化的进化动态板块字符串
    """
    snapshot = get_evolution_snapshot()
    
    if format.lower() == "html":
        return generate_html_mirror(snapshot)
    else:
        return generate_text_mirror(snapshot)

# 为展示页提供的简单接口
def get_mirror_for_display() -> Dict[str, Any]:
    """获取用于展示页的镜面数据包"""
    snapshot = get_evolution_snapshot()
    return {
        "snapshot": snapshot,
        "html": generate_html_mirror(snapshot),
        "text": generate_text_mirror(snapshot),
        "last_updated": snapshot["human_time"],
        "is_ready": snapshot["display_ready"]
    }

if __name__ == "__main__":
    # 测试运行
    print("进化镜面模块测试...")
    snapshot = get_evolution_snapshot()
    print("快照数据:")
    print(json.dumps(snapshot, indent=2, ensure_ascii=False, default=str))
    print("\nHTML输出:")
    print(generate_html_mirror(snapshot))
    print("\n文本输出:")
    print(generate_text_mirror(snapshot))
