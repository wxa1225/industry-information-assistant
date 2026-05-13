# Copyright © 2026  版权所有

"""
评估报告生成器

将评估结果格式化为 Markdown 报告，包含：
- 雷达图描述（各维度得分）
- 趋势对比（不同配置的效果变化）
- 问题分布
"""

from typing import Dict, Any, List
from datetime import datetime

from .metrics import MetricResult, ResearchMetrics

# 延迟导入 benchmark，避免循环依赖
# from .benchmark import BenchmarkResult  # only used in type hints


class EvaluationReport:
    """评估报告"""

    def __init__(self, title: str = "研究质量评估报告"):
        self.title = title
        self.sections: List[str] = []

    def add_metrics_summary(
        self,
        metrics: Dict[str, MetricResult],
        total_score: float,
    ) -> None:
        """添加指标汇总"""
        lines = [
            "## 指标概览\n",
            f"**综合评分: {total_score:.3f}** (0-1)\n",
            "| 指标 | 得分 | 权重 | 说明 |",
            "|------|------|------|------|",
        ]

        for name, result in metrics.items():
            name_cn = {
                "source_diversity": "来源多样性",
                "citation_density": "引用密度",
                "recency": "时效性",
                "section_completeness": "章节完整度",
                "hallucination_rate": "幻觉率",
                "data_richness": "数据丰富度",
                "conflict_resolution": "冲突解决率",
            }.get(name, name)

            score_bar = "█" * int(result.score * 5) + "░" * (5 - int(result.score * 5))
            lines.append(
                f"| {name_cn} | {score_bar} {result.score:.2f} | "
                f"{result.weight:.0%} | {result.explanation} |"
            )

        self.sections.append("\n".join(lines))

    def add_benchmark_comparison(
        self,
        comparison: Dict[str, Any],
    ) -> None:
        """添加基准测试对比"""
        lines = ["\n## 基准测试对比\n"]
        lines.append("| 配置 | 平均分 | 平均耗时 | 平均成本 | 成功率 |")
        lines.append("|------|--------|---------|---------|--------|")

        for config_name, stats in comparison["configs"].items():
            lines.append(
                f"| {config_name} "
                f"| {stats['avg_score']:.3f} "
                f"| {stats['avg_duration']:.1f}s "
                f"| ¥{stats['avg_cost']:.4f} "
                f"| {stats['success_rate']:.0%} |"
            )

        lines.append(f"\n**最优配置**: {comparison['best_config']}")
        self.sections.append("\n".join(lines))

    def add_cost_report(self, cost_report: Dict[str, Any]) -> None:
        """添加成本报告"""
        lines = ["\n## 成本分析\n"]
        lines.append(f"- **总调用次数**: {cost_report.get('total_calls', 0)}")
        lines.append(f"- **总 token 数**: {cost_report.get('total_tokens', 0):,}")
        lines.append(f"- **总成本**: {cost_report.get('total_cost_formatted', 'N/A')}")
        lines.append(f"- **成功调用**: {cost_report.get('successful_calls', 0)}")
        lines.append(f"- **失败调用**: {cost_report.get('failed_calls', 0)}")

        cost_by_agent = cost_report.get("cost_by_agent", {})
        if cost_by_agent:
            lines.append("\n### 各 Agent 成本分布\n")
            lines.append("| Agent | 成本 |")
            lines.append("|-------|------|")
            for agent, cost in cost_by_agent.items():
                lines.append(f"| {agent} | ¥{cost:.4f} |")

        self.sections.append("\n".join(lines))

    def add_conflict_report(self, conflict_report: Dict[str, Any]) -> None:
        """添加交叉验证报告"""
        lines = ["\n## 交叉验证结果\n"]

        conflicts = conflict_report.get("conflicts", [])
        lines.append(f"检测到 **{conflict_report.get('conflicts_detected', 0)}** 个事实冲突\n")

        if conflicts:
            for i, c in enumerate(conflicts):
                status = "✅ 已解决" if c.get("resolved") else "❌ 未解决"
                lines.append(f"### 冲突 {i+1} [{c.get('severity', 'unknown')}] {status}\n")
                lines.append(f"- **描述**: {c.get('description', '')}")
                if c.get("resolution"):
                    lines.append(f"- **解决**: {c['resolution']}")
                lines.append("")

        confidence_scores = conflict_report.get("confidence_scores", {})
        if confidence_scores:
            lines.append("### 事实置信度分布\n")
            scores = [v.get("overall_score", 0) for v in confidence_scores.values()]
            if scores:
                avg = sum(scores) / len(scores)
                lines.append(f"- **平均置信度**: {avg:.3f}")
                lines.append(f"- **最高**: {max(scores):.3f}")
                lines.append(f"- **最低**: {min(scores):.3f}")

        self.sections.append("\n".join(lines))

    def render(self) -> str:
        """渲染完整的 Markdown 报告"""
        parts = [
            f"# {self.title}\n",
            f"*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n",
        ]
        parts.extend(self.sections)
        return "\n".join(parts)


def generate_report(
    metrics: Dict[str, MetricResult],
    total_score: float,
    cost_report: Dict = None,
    conflict_report: Dict = None,
    title: str = "研究质量评估报告",
) -> str:
    """
    生成评估报告的便捷函数。

    Args:
        metrics: 评估指标
        total_score: 综合评分
        cost_report: 成本报告
        conflict_report: 交叉验证报告
        title: 报告标题

    Returns:
        Markdown 格式的评估报告
    """
    report = EvaluationReport(title=title)
    report.add_metrics_summary(metrics, total_score)

    if cost_report:
        report.add_cost_report(cost_report)

    if conflict_report:
        report.add_conflict_report(conflict_report)

    return report.render()
