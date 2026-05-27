"""
航海日志压缩索引：从日志中抽取失败/成功招式卡，供 planner 前召回。
"""
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
import re

DEFAULT_LOG_DIR = Path("logs")
DEFAULT_INDEX_FILE = Path("navlog_index.json")


class NavlogCard:
    """招式卡数据结构"""
    def __init__(self, card_id: str, context: str, problem: str,
                 action: str, result: str, tags: List[str],
                 source_log: str, timestamp: str):
        self.card_id = card_id
        self.context = context
        self.problem = problem
        self.action = action
        self.result = result
        self.tags = tags
        self.source_log = source_log
        self.timestamp = timestamp

    def to_dict(self) -> Dict[str, Any]:
        return {
            "card_id": self.card_id,
            "context": self.context,
            "problem": self.problem,
            "action": self.action,
            "result": self.result,
            "tags": self.tags,
            "source_log": self.source_log,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'NavlogCard':
        return cls(**data)


class NavlogCompressor:
    """日志压缩器：抽取招式卡并建立索引"""
    def __init__(self, log_dir: Path = DEFAULT_LOG_DIR,
                 index_file: Path = DEFAULT_INDEX_FILE):
        self.log_dir = Path(log_dir)
        self.index_file = Path(index_file)
        self.cards: List[NavlogCard] = []
        self._tag_index: Dict[str, List[str]] = {}  # tag -> card_ids
        self._keyword_index: Dict[str, List[str]] = {}  # keyword -> card_ids
        if self.index_file.exists():
            self.load_index()

    def load_index(self) -> None:
        """加载已有索引"""
        try:
            with open(self.index_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.cards = [NavlogCard.from_dict(card) for card in data.get('cards', [])]
                self._rebuild_indices()
        except (json.JSONDecodeError, KeyError):
            self.cards = []
            self._tag_index = {}
            self._keyword_index = {}

    def save_index(self) -> None:
        """保存索引到文件"""
        data = {
            'cards': [card.to_dict() for card in self.cards],
            'tags': self._tag_index,
            'keywords': self._keyword_index,
        }
        with open(self.index_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _rebuild_indices(self) -> None:
        """重建标签和关键词索引"""
        self._tag_index.clear()
        self._keyword_index.clear()
        for card in self.cards:
            self._index_card(card)

    def _index_card(self, card: NavlogCard) -> None:
        """为单张卡片建立索引"""
        # 标签索引
        for tag in card.tags:
            if tag not in self._tag_index:
                self._tag_index[tag] = []
            if card.card_id not in self._tag_index[tag]:
                self._tag_index[tag].append(card.card_id)

        # 关键词索引（简单分词：英文单词和中文字符）
        keywords = self._extract_keywords(f"{card.context} {card.problem} {card.action} {card.result}")
        for keyword in keywords:
            if keyword not in self._keyword_index:
                self._keyword_index[keyword] = []
            if card.card_id not in self._keyword_index[keyword]:
                self._keyword_index[keyword].append(card.card_id)

    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词（简单实现：英文单词和中文字符）"""
        # 移除标点符号和数字
        cleaned = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', text)
        # 分割英文单词和中文字符
        tokens = re.findall(r'[a-zA-Z]+|[\u4e00-\u9fff]', cleaned)
        # 转换为小写并去重
        unique_tokens = list(set(token.lower() for token in tokens if len(token) > 1))
        return unique_tokens

    def extract_card_from_log(self, log_content: str, log_file: str) -> Optional[NavlogCard]:
        """从单条日志内容中提取招式卡（示例实现，需根据实际日志格式调整）"""
        # 这里是一个非常简单的示例，实际实现需要根据日志格式解析
        # 假设日志格式为JSON，包含这些字段
        try:
            data = json.loads(log_content)
            card_id = f"card_{len(self.cards) + 1:06d}"
            card = NavlogCard(
                card_id=card_id,
                context=data.get('context', ''),
                problem=data.get('problem', ''),
                action=data.get('action', ''),
                result=data.get('result', ''),
                tags=data.get('tags', []),
                source_log=log_file,
                timestamp=data.get('timestamp', ''),
            )
            return card
        except (json.JSONDecodeError, KeyError):
            return None

    def compress_logs(self) -> int:
        """压缩日志目录中的所有日志文件，返回新增卡片数"""
        if not self.log_dir.exists():
            return 0

        new_cards = []
        for log_file in self.log_dir.glob("*.jsonl"):
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        card = self.extract_card_from_log(line, str(log_file))
                        if card:
                            new_cards.append(card)
            except Exception as e:
                print(f"Error processing {log_file}: {e}")
                continue

        # 添加新卡片并建立索引
        for card in new_cards:
            self.cards.append(card)
            self._index_card(card)

        # 保存索引
        if new_cards:
            self.save_index()

        return len(new_cards)

    def recall(self, query: str, tags: Optional[List[str]] = None,
               top_k: int = 5) -> List[NavlogCard]:
        """召回与查询相关的招式卡"""
        if not self.cards:
            return []

        # 提取查询关键词
        query_keywords = self._extract_keywords(query)

        # 计算每张卡片的相关性分数
        scores = []
        for card in self.cards:
            score = 0.0

            # 关键词匹配分数（简单：包含关键词数）
            card_keywords = set(self._extract_keywords(
                f"{card.context} {card.problem} {card.action} {card.result}"
            ))
            matched_keywords = set(query_keywords) & card_keywords
            if query_keywords:
                score += len(matched_keywords) / len(query_keywords)

            # 标签匹配分数
            if tags:
                matched_tags = set(tags) & set(card.tags)
                if tags:
                    score += len(matched_tags) / len(tags) * 2.0  # 标签权重更高

            scores.append((score, card))

        # 按分数排序并返回前top_k个
        scores.sort(key=lambda x: x[0], reverse=True)
        return [card for _, card in scores[:top_k]]


# 全局实例，方便调用
_compressor = None


def get_compressor() -> NavlogCompressor:
    """获取全局压缩器实例"""
    global _compressor
    if _compressor is None:
        _compressor = NavlogCompressor()
    return _compressor


def compress_all_logs() -> int:
    """压缩所有日志，返回新增卡片数"""
    return get_compressor().compress_logs()


def recall_cards(query: str, tags: Optional[List[str]] = None,
                 top_k: int = 5) -> List[NavlogCard]:
    """召回相关招式卡"""
    return get_compressor().recall(query, tags, top_k)
