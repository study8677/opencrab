"""
navlog_index.py
将航海日志压缩成“反复卡点→下一步建议”索引，并提供召回接口。
"""

import json
from typing import List, Dict, Any
from . import jsonlstore


class NavlogIndex:
    def __init__(self, store_key: str = "navlog"):
        self.store_key = store_key
        self.index: Dict[str, List[str]] = {}  # 卡点 -> 建议列表
        self._load()
    
    def _load(self):
        """从jsonl存储加载日志并建立索引"""
        try:
            records = jsonlstore.get_all(self.store_key)
            for record in records:
                bottleneck = record.get("bottleneck", "")
                suggestion = record.get("suggestion", "")
                if bottleneck and suggestion:
                    # 简单的关键词匹配索引
                    normalized = bottleneck.strip().lower()
                    if normalized not in self.index:
                        self.index[normalized] = []
                    self.index[normalized].append(suggestion)
        except Exception:
            # 如果加载失败，使用空索引
            self.index = {}
    
    def recall(self, bottleneck_desc: str, k: int = 3) -> List[Dict[str, str]]:
        """
        根据卡点描述召回相关建议。
        返回最多k条记录，每条记录包含卡点和建议。
        """
        if not bottleneck_desc:
            return []
        
        # 简单的相似度匹配：检查卡点描述是否包含已知卡点关键词
        normalized_desc = bottleneck_desc.strip().lower()
        matched_suggestions = []
        
        for bottleneck_key, suggestions in self.index.items():
            # 如果描述中包含卡点关键词
            if bottleneck_key in normalized_desc:
                for suggestion in suggestions:
                    matched_suggestions.append({
                        "bottleneck": bottleneck_key,
                        "suggestion": suggestion
                    })
        
        # 去重并限制数量
        seen = set()
        unique_results = []
        for item in matched_suggestions:
            key = (item["bottleneck"], item["suggestion"])
            if key not in seen:
                seen.add(key)
                unique_results.append(item)
        
        return unique_results[:k]


def recall_similar_bottlenecks(bottleneck_desc: str, k: int = 3) -> List[Dict[str, str]]:
    """便捷函数：召回相似卡点的建议"""
    index = NavlogIndex()
    return index.recall(bottleneck_desc, k)
