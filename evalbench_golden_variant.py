"""Golden variant tasks for evalbench testing."""
import re
from typing import Dict, List, Any

def variant_1(data: Dict[str, Any]) -> Dict[str, Any]:
    """Basic retrieval task."""
    query = data.get("query", "")
    if not query:
        return {"score": 0.0, "reason": "empty query"}
    return {"score": 1.0, "result": query.upper()}

def variant_2(data: Dict[str, Any]) -> Dict[str, Any]:
    """Constraint satisfaction task."""
    constraints = data.get("constraints", [])
    items = data.get("items", [])
    if not constraints or not items:
        return {"score": 0.0, "reason": "missing data"}
    
    passed = 0
    for item in items:
        if all(eval(c, {"item": item}) for c in constraints):
            passed += 1
    
    score = passed / len(items) if items else 0.0
    return {"score": score, "passed": passed, "total": len(items)}

def variant_3(data: Dict[str, Any]) -> Dict[str, Any]:
    """Incremental refinement task."""
    initial = data.get("initial", "")
    refinements = data.get("refinements", [])
    
    result = initial
    for refinement in refinements:
        if refinement.startswith("append:"):
            result += refinement[7:]
        elif refinement.startswith("prepend:"):
            result = refinement[8:] + result
        elif refinement.startswith("replace:"):
            parts = refinement.split(":")
            if len(parts) == 3:
                result = result.replace(parts[1], parts[2])
    
    return {"score": 1.0, "result": result}

def variant_4(data: Dict[str, Any]) -> Dict[str, Any]:
    """Multi-step reasoning task."""
    steps = data.get("steps", [])
    if not steps:
        return {"score": 0.0, "reason": "no steps"}
    
    context = {}
    for i, step in enumerate(steps):
        try:
            exec(step, context)
        except Exception as e:
            return {"score": 0.0, "reason": f"step {i+1} failed: {e}"}
    
    return {"score": 1.0, "context": {k: v for k, v in context.items() if not k.startswith("__")}}

# FIX: 修复语言边界检测逻辑，避免混合语言输入误判
def _is_language_boundary(text: str, lang_pattern: str, threshold: float = 0.7) -> bool:
    """Check if text represents a language boundary with improved detection."""
    if not text:
        return False
    
    # 提高阈值，减少误判
    matches = len(re.findall(lang_pattern, text))
    total_chars = len(text.strip())
    
    if total_chars == 0:
        return False
    
    # 修复：当文本较短时使用更宽松的检测
    if total_chars < 5:
        return matches > 0
    
    ratio = matches / total_chars
    return ratio >= threshold

def variant_5(data: Dict[str, Any]) -> Dict[str, Any]:
    """Language boundary test (previously weakest)."""
    text = data.get("text", "")
    if not text:
        return {"score": 0.0, "reason": "empty text"}
    
    # 语言模式（Unicode范围）
    patterns = {
        "chinese": r'[\u4e00-\u9fff]',
        "english": r'[a-zA-Z]',
        "japanese": r'[\u3040-\u309f\u30a0-\u30ff]',
        "korean": r'[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]',
    }
    
    detected = []
    for lang, pattern in patterns.items():
        if _is_language_boundary(text, pattern):
            detected.append(lang)
    
    # 计分逻辑：检测到1种语言得0.7分，2种得0.9分，3种得1.0分
    if not detected:
        score = 0.0
    elif len(detected) == 1:
        score = 0.7
    elif len(detected) == 2:
        score = 0.9
    else:
        score = 1.0
    
    return {
        "score": score,
        "detected_languages": detected,
        "text_length": len(text)
    }

def variant_6(data: Dict[str, Any]) -> Dict[str, Any]:
    """Edge case handling task."""
    cases = data.get("cases", [])
    results = []
    
    for case in cases:
        input_data = case.get("input")
        expected = case.get("expected")
        
        if isinstance(input_data, str) and input_data.lower() == "empty":
            actual = None
        elif isinstance(input_data, str) and input_data.lower() == "error":
            try:
                result = eval(input_data)  # Intentionally risky for testing
                actual = result
            except:
                actual = "ERROR"
        else:
            actual = input_data
        
        passed = (actual == expected)
        results.append({"input": input_data, "expected": expected, "actual": actual, "passed": passed})
    
    passed_count = sum(1 for r in results if r["passed"])
    score = passed_count / len(results) if results else 0.0
    
    return {"score": score, "results": results, "passed": passed_count, "total": len(results)}

def variant_7(data: Dict[str, Any]) -> Dict[str, Any]:
    """Resource allocation task."""
    resources = data.get("resources", {})
    demands = data.get("demands", [])
    
    total_capacity = sum(resources.values())
    total_demand = sum(d["amount"] for d in demands)
    
    if total_capacity < total_demand:
        return {"score": 0.0, "reason": "insufficient capacity"}
    
    allocated = []
    remaining = resources.copy()
    
    for demand in demands:
        if demand["type"] in remaining and remaining[demand["type"]] >= demand["amount"]:
            remaining[demand["type"]] -= demand["amount"]
            allocated.append(True)
        else:
            allocated.append(False)
    
    allocated_count = sum(allocated)
    score = allocated_count / len(demands) if demands else 0.0
    
    return {
        "score": score,
        "allocated": allocated_count,
        "total_demands": len(demands),
        "remaining_resources": remaining
    }

def variant_8(data: Dict[str, Any]) -> Dict[str, Any]:
    """Temporal reasoning task."""
    events = data.get("events", [])
    queries = data.get("queries", [])
    
    if not events or not queries:
        return {"score": 0.0, "reason": "missing data"}
    
    # 简单时间线构建
    timeline = {}
    for event in events:
        time = event.get("time", 0)
        if time not in timeline:
            timeline[time] = []
        timeline[time].append(event.get("description", ""))
    
    results = []
    for query in queries:
        if query["type"] == "before":
            before_events = []
            for time in sorted(timeline.keys()):
                if time < query["time"]:
                    before_events.extend(timeline[time])
            results.append({"query": query, "answer": before_events})
        elif query["type"] == "after":
            after_events = []
            for time in sorted(timeline.keys()):
                if time > query["time"]:
                    after_events.extend(timeline[time])
            results.append({"query": query, "answer": after_events})
        else:
            results.append({"query": query, "answer": []})
    
    return {"score": 1.0, "results": results}

# Variant registry
VARIANTS = {
    "variant_1": variant_1,
    "variant_2": variant_2,
    "variant_3": variant_3,
    "variant_4": variant_4,
    "variant_5": variant_5,
    "variant_6": variant_6,
    "variant_7": variant_7,
    "variant_8": variant_8,
}

def run_variant(variant_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Run a specific variant with given data."""
    if variant_name not in VARIANTS:
        return {"score": 0.0, "reason": f"Unknown variant: {variant_name}"}
    
    try:
        return VARIANTS[variant_name](data)
    except Exception as e:
        return {"score": 0.0, "reason": f"Variant failed: {str(e)}"}
