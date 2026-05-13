# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有

"""
基准测试运行器

对一组标准测试 query 运行评估，
支持对比不同配置（V1 vs V2，不同 prompt 版本等）的效果。
"""

import json
import os
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Callable, Awaitable

from .metrics import ResearchMetrics, MetricResult

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkCase:
    """单个测试用例"""
    id: str
    query: str
    description: str
    category: str               # "market_analysis" | "trend_forecast" | "competitive_analysis" | "policy_impact"
    expected_topics: List[str]  # 期望覆盖的主题关键词
    gold_facts: List[Dict]      # 已知关键事实（用于事实覆盖度计算）

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "query": self.query,
            "description": self.description,
            "category": self.category,
            "expected_topics": self.expected_topics,
            "gold_facts_count": len(self.gold_facts),
        }


@dataclass
class BenchmarkResult:
    """单个测试用例的评估结果"""
    case_id: str
    query: str
    config_name: str            # 如 "v2_default", "v2_cross_validation"
    metrics: Dict[str, MetricResult]
    total_score: float          # 加权总分 0-1
    duration_seconds: float
    llm_calls: int
    total_tokens: int
    cost_yuan: float
    error: str = ""

    def to_dict(self) -> Dict:
        return {
            "case_id": self.case_id,
            "query": self.query,
            "config_name": self.config_name,
            "total_score": round(self.total_score, 3),
            "metrics": {k: v.to_dict() for k, v in self.metrics.items()},
            "duration_seconds": round(self.duration_seconds, 1),
            "llm_calls": self.llm_calls,
            "total_tokens": self.total_tokens,
            "cost_yuan": round(self.cost_yuan, 4),
            "error": self.error,
        }


class BenchmarkRunner:
    """
    基准测试运行器

    运行一组测试用例，收集评估结果，支持配置对比。
    """

    def __init__(self, gold_standard_path: Optional[str] = None):
        """
        Args:
            gold_standard_path: 黄金测试集 JSON 文件路径
        """
        self.cases: List[BenchmarkCase] = []
        if gold_standard_path and os.path.exists(gold_standard_path):
            self.load_gold_standard(gold_standard_path)

    def load_gold_standard(self, path: str) -> None:
        """加载黄金测试集"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.cases = [
            BenchmarkCase(
                id=case["id"],
                query=case["query"],
                description=case.get("description", ""),
                category=case.get("category", "general"),
                expected_topics=case.get("expected_topics", []),
                gold_facts=case.get("gold_facts", []),
            )
            for case in data.get("cases", [])
        ]
        logger.info(f"加载黄金测试集: {len(self.cases)} 个测试用例")

    async def run_single(
        self,
        case: BenchmarkCase,
        research_fn: Callable[[str], Awaitable[Dict]],
        config_name: str = "default",
    ) -> BenchmarkResult:
        """
        运行单个测试用例。

        Args:
            case: 测试用例
            research_fn: 研究函数，接受 query 返回 ResearchState
            config_name: 配置名称

        Returns:
            BenchmarkResult
        """
        logger.info(f"[Benchmark] 运行测试: {case.id} - {case.query[:50]}...")
        start = time.time()
        error = ""

        try:
            state = await research_fn(case.query)

            # 计算指标
            metrics_calc = ResearchMetrics()
            metrics = metrics_calc.compute_all(state)
            total_score = metrics_calc.weighted_score(metrics)

            # 提取统计信息
            logs = state.get("logs", [])
            llm_calls = len(logs)
            total_tokens = sum(log.get("tokens_used", 0) for log in logs)

            # 估算成本
            cost_yuan = 0.0
            try:
                from service.observability import calculate_cost
                for log in logs:
                    model = log.get("model", "qwen-plus")
                    tokens = log.get("tokens_used", 0)
                    # 粗略估算：一半 input 一半 output
                    cost_yuan += calculate_cost(model, tokens // 2, tokens // 2)
            except ImportError:
                pass

            duration = time.time() - start

            return BenchmarkResult(
                case_id=case.id,
                query=case.query,
                config_name=config_name,
                metrics=metrics,
                total_score=total_score,
                duration_seconds=duration,
                llm_calls=llm_calls,
                total_tokens=total_tokens,
                cost_yuan=cost_yuan,
            )

        except Exception as e:
            duration = time.time() - start
            error = str(e)
            logger.error(f"[Benchmark] 测试 {case.id} 失败: {e}")

            return BenchmarkResult(
                case_id=case.id,
                query=case.query,
                config_name=config_name,
                metrics={},
                total_score=0.0,
                duration_seconds=duration,
                llm_calls=0,
                total_tokens=0,
                cost_yuan=0.0,
                error=error,
            )

    async def run_all(
        self,
        research_fn: Callable[[str], Awaitable[Dict]],
        config_name: str = "default",
    ) -> List[BenchmarkResult]:
        """运行所有测试用例"""
        results = []
        for case in self.cases:
            result = await self.run_single(case, research_fn, config_name)
            results.append(result)
        return results

    def compare_configs(
        self,
        results_by_config: Dict[str, List[BenchmarkResult]],
    ) -> Dict[str, Any]:
        """
        对比不同配置的效果。

        Args:
            results_by_config: {配置名: [评估结果]}

        Returns:
            对比报告
        """
        comparison = {}
        for config_name, results in results_by_config.items():
            successful = [r for r in results if not r.error]
            if not successful:
                comparison[config_name] = {
                    "avg_score": 0.0,
                    "avg_duration": 0.0,
                    "avg_cost": 0.0,
                    "success_rate": 0.0,
                    "count": len(results),
                }
                continue

            avg_score = sum(r.total_score for r in successful) / len(successful)
            avg_duration = sum(r.duration_seconds for r in successful) / len(successful)
            avg_cost = sum(r.cost_yuan for r in successful) / len(successful)

            comparison[config_name] = {
                "avg_score": round(avg_score, 3),
                "avg_duration": round(avg_duration, 1),
                "avg_cost": round(avg_cost, 4),
                "success_rate": len(successful) / len(results),
                "count": len(results),
                "successful": len(successful),
            }

        return {
            "configs": comparison,
            "best_config": max(comparison.items(), key=lambda x: x[1]["avg_score"])[0],
        }

    def generate_comparison_markdown(
        self,
        comparison: Dict[str, Any],
    ) -> str:
        """生成对比 Markdown 报告"""
        lines = ["# 基准测试对比报告\n"]
        lines.append("| 配置 | 平均分 | 平均耗时 | 平均成本 | 成功率 | 测试数 |")
        lines.append("|------|--------|---------|---------|--------|--------|")

        for config_name, stats in comparison["configs"].items():
            lines.append(
                f"| {config_name} "
                f"| {stats['avg_score']:.3f} "
                f"| {stats['avg_duration']:.1f}s "
                f"| ¥{stats['avg_cost']:.4f} "
                f"| {stats['success_rate']:.0%} "
                f"| {stats['successful']}/{stats['count']} |"
            )

        lines.append(f"\n**最优配置**: {comparison['best_config']}")
        return "\n".join(lines)
