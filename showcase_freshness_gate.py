import re
import os
from pathlib import Path

def get_actual_module_count():
    """统计 src/crab/ 目录下的 .py 模块数量（排除 __init__.py 和测试文件）"""
    crab_dir = Path(__file__).parent
    modules = [f for f in crab_dir.glob("*.py") 
               if f.name != "__init__.py" and not f.name.startswith("test_")]
    return len(modules)

def get_docs_index_html_path():
    """获取 docs/index.html 的路径"""
    return Path(__file__).parent / "docs" / "index.html"

def extract_module_count_from_html():
    """从 docs/index.html 中提取当前显示的数字"""
    html_path = get_docs_index_html_path()
    if not html_path.exists():
        return None
    
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 尝试多种模式匹配数字
    patterns = [
        r'<span[^>]*id="module-count"[^>]*>(\d+)</span>',
        r'(\d+)\s*modules',
        r'模块数[^>]*>(\d+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            return int(match.group(1))
    
    return None

def update_docs_index_html(actual_count):
    """更新 docs/index.html 中的数字"""
    html_path = get_docs_index_html_path()
    if not html_path.exists():
        return False
    
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 尝试替换数字
    patterns = [
        (r'(<span[^>]*id="module-count"[^>]*>)\d+(</span>)', f'\\g<1>{actual_count}\\g<2>'),
        (r'(\d+)(\s*modules)', f'{actual_count}\\g<2>'),
    ]
    
    new_content = content
    replaced = False
    
    for pattern, replacement in patterns:
        new_content, count = re.subn(pattern, replacement, new_content, flags=re.IGNORECASE)
        if count > 0:
            replaced = True
            break
    
    if replaced:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True
    
    return False

def check_showcase_freshness():
    """检查橱窗保鲜状态，返回 (is_fresh, actual_count, docs_count)"""
    actual_count = get_actual_module_count()
    docs_count = extract_module_count_from_html()
    
    if docs_count is None:
        # 无法从 HTML 中提取数字，视为不新鲜
        return False, actual_count, docs_count
    
    return actual_count == docs_count, actual_count, docs_count

def refresh_if_needed():
    """如果需要刷新则执行刷新，返回是否执行了刷新"""
    is_fresh, actual_count, docs_count = check_showcase_freshness()
    
    if not is_fresh:
        print(f"[SHOWCASE_FRESHNESS_GATE] 检测到数字不同步: 实际={actual_count}, 文档={docs_count}")
        success = update_docs_index_html(actual_count)
        if success:
            print(f"[SHOWCASE_FRESHNESS_GATE] 已刷新文档数字为 {actual_count}")
            return True
        else:
            print("[SHOWCASE_FRESHNESS_GATE] 刷新失败")
    
    return False
