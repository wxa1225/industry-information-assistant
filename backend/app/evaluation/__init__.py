# Copyright © 2026  版权所有

"""
自动化评估体系 - 行业研究报告质量评估

提供可量化的评估指标，替代 CriticMaster 的主观打分。
核心指标：
1. source_diversity_index - 来源多样性
2. citation_density - 引用密度
3. recency_score - 时效性
4. section_completeness - 章节完整度
5. hallucination_rate - 幻觉率（无来源事实比例）
6. data_richness - 数据丰富度
"""

from .metrics import (
    ResearchMetrics, MetricResult, compute_metrics
)
from .llm_judge import LLMJudge, JudgeResult
from .benchmark import BenchmarkRunner, BenchmarkResult
from .report import EvaluationReport, generate_report

__all__ = [
    "ResearchMetrics", "MetricResult", "compute_metrics",
    "LLMJudge", "JudgeResult",
    "BenchmarkRunner", "BenchmarkResult",
    "EvaluationReport", "generate_report",
]
