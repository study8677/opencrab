"""
自生手错题本升级：聚类AST失败形态，生成盲练题。
"""
import json
from pathlib import Path
from typing import List, Dict, Any
from collections import defaultdict
import ast

# 假设的AST失败类型分类
AST_FAILURE_CATEGORIES = {
    "syntax": ["SyntaxError", "IndentationError", "TabError"],
    "structure": ["unexpected indent", "unexpected EOF", "unmatched"],
    "semantic": ["TypeError", "NameError", "AttributeError"],
    "other": ["UnicodeDecodeError", "RecursionError"]
}

def categorize_failure(error_msg: str) -> str:
    """根据错误信息分类AST失败形态"""
    error_lower = error_msg.lower()
    for category, keywords in AST_FAILURE_CATEGORIES.items():
        for keyword in keywords:
            if keyword.lower() in error_lower:
                return category
    return "other"

def cluster_rejected_patches(rejected_patches: List[Dict[str, Any]], max_patches: int = 30) -> Dict[str, List[Dict]]:
    """
    聚类近30次拒收补丁
    返回: {category: [patches]}
    """
    clusters = defaultdict(list)
    for patch in rejected_patches[-max_patches:]:
        error_msg = patch.get("error_message", "")
        category = categorize_failure(error_msg)
        clusters[category].append(patch)
    return dict(clusters)

def generate_blind_drill_questions(clusters: Dict[str, List[Dict]], num_questions: int = 3) -> List[Dict[str, Any]]:
    """
    从聚类结果生成盲练题
    每个题目包含: category, broken_code, expected_fix_hint
    """
    questions = []
    categories = list(clusters.keys())
    
    # 选择不同的类别以覆盖多样性
    for i in range(min(num_questions, len(categories))):
        category = categories[i]
        patches = clusters[category]
        
        # 选择该类别中最近的一个补丁作为基础
        if patches:
            selected_patch = patches[-1]
            broken_code = selected_patch.get("patch", "")
            error_msg = selected_patch.get("error_message", "")
            
            question = {
                "id": f"blind_drill_{i+1}",
                "category": category,
                "broken_code": broken_code,
                "error_message": error_msg,
                "expected_fix_hint": f"修复{category}类型的AST错误",
                "difficulty": len(error_msg.split()) // 5 + 1  # 简单难度计算
            }
            questions.append(question)
    
    return questions

def save_questions_to_file(questions: List[Dict], filename: str = "blind_drill_questions.json"):
    """将生成的题目保存到文件"""
    output_path = Path(filename)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(questions, f, ensure_ascii=False, indent=2)
    return output_path

def generate_blind_drill(rejected_patches: List[Dict], num_questions: int = 3) -> List[Dict]:
    """
    主函数：从拒收补丁生成盲练题
    """
    if not rejected_patches:
        return []
    
    # 聚类
    clusters = cluster_rejected_patches(rejected_patches)
    
    # 生成题目
    questions = generate_blind_drill_questions(clusters, num_questions)
    
    # 保存到文件
    if questions:
        save_questions_to_file(questions)
    
    return questions

def load_blind_drill_questions(filename: str = "blind_drill_questions.json") -> List[Dict]:
    """从文件加载盲练题"""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []
