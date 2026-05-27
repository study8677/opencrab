class AntiPatternCard:
    """反模式卡：记录反复出现的失败模式"""
    
    def __init__(self, pattern, frequency, description="", tags=None):
        self.pattern = pattern
        self.frequency = frequency
        self.description = description
        self.tags = tags or []
    
    @classmethod
    def from_dict(cls, data):
        """从字典创建反模式卡"""
        return cls(
            pattern=data.get('pattern', ''),
            frequency=data.get('frequency', 0),
            description=data.get('description', ''),
            tags=data.get('tags', [])
        )
    
    def to_dict(self):
        """转换为字典"""
        return {
            'pattern': self.pattern,
            'frequency': self.frequency,
            'description': self.description,
            'tags': self.tags
        }
    
    def matches(self, error_type):
        """检查是否匹配给定的错误类型"""
        return self.pattern == error_type
    
    def increase_frequency(self, increment=1):
        """增加频率计数"""
        self.frequency += increment
        return self.frequency
