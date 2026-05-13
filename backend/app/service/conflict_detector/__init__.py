# Copyright © 2026  版权所有

"""
冲突检测与交叉验证模块

解决多源情报场景的核心问题：
1. 自动检测来自不同来源的矛盾事实
2. 对矛盾事实发起补充搜索进行交叉验证
3. 基于多源证据计算每个事实的最终置信度

设计思路：
- 规则提取数值事实 + LLM 语义分组 + LLM 矛盾分析
- 避免过度依赖 LLM，数值提取和初步筛选用规则
"""

from .detector import ConflictDetector, ConflictPair
from .validator import CrossValidator, ValidationResult
from .scorer import ConfidenceScorer, ConfidenceResult

__all__ = [
    "ConflictDetector", "ConflictPair",
    "CrossValidator", "ValidationResult",
    "ConfidenceScorer", "ConfidenceResult",
]
