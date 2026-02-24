"""
数据模型定义
"""
from dataclasses import dataclass, field
from typing import List


@dataclass
class SearchResult:
    """单条搜索结果"""
    title: str          # 标题
    url: str            # 来源 URL
    content: str        # 内容摘要
    language: str = "unknown"  # 语言：zh/en/unknown


@dataclass
class SearchReport:
    """搜索报告"""
    original_query: str                    # 原始用户问题
    all_results: List[SearchResult] = field(default_factory=list)    # 所有搜索结果
    valid_results: List[SearchResult] = field(default_factory=list)  # 有效结果
    summary: str = ""                                      # 格式化的参考资料
