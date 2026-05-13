# Copyright © 2026  版权所有

"""
自动化评估指标计算

所有指标都是可自动计算的（不依赖 LLM 打分），返回 0-1 的分数。
"""

import re
import math
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime


@dataclass
class MetricResult:
    """单个指标的评估结果"""
    name: str
    score: float              # 0-1 分数
    weight: float             # 权重
    value: Any                # 原始计算值
    max_value: Any            # 理想值/最大值
    explanation: str          # 计算过程说明

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "score": round(self.score, 3),
            "weight": self.weight,
            "value": self.value,
            "max_value": self.max_value,
            "explanation": self.explanation,
        }


class ResearchMetrics:
    """
    研究报告自动化指标计算

    从 ResearchState 中提取数据，计算各项指标。
    """

    # 指标权重
    DEFAULT_WEIGHTS = {
        "source_diversity": 0.15,
        "citation_density": 0.15,
        "recency": 0.20,
        "section_completeness": 0.15,
        "hallucination_rate": 0.15,   # 注意：这是反向指标（越低越好）
        "data_richness": 0.10,
        "conflict_resolution": 0.10,  # 冲突解决率（如果有交叉验证模块）
    }

    def compute_all(
        self,
        state: Dict[str, Any],
        weights: Optional[Dict[str, float]] = None,
    ) -> Dict[str, MetricResult]:
        """
        计算所有指标。

        Args:
            state: ResearchState 字典
            weights: 自定义权重（可选）

        Returns:
            {指标名: MetricResult}
        """
        w = weights or self.DEFAULT_WEIGHTS
        results = {}

        results["source_diversity"] = self.source_diversity_index(state)
        results["citation_density"] = self.citation_density(state)
        results["recency"] = self.recency_score(state)
        results["section_completeness"] = self.section_completeness(state)
        results["hallucination_rate"] = self.hallucination_rate(state)
        results["data_richness"] = self.data_richness(state)
        results["conflict_resolution"] = self.conflict_resolution_rate(state)

        # 应用权重
        for name, result in results.items():
            result.weight = w.get(name, 0.0)

        return results

    def weighted_score(self, results: Dict[str, MetricResult]) -> float:
        """计算加权总分"""
        total = 0.0
        total_weight = 0.0
        for name, result in results.items():
            if result.weight > 0:
                total += result.score * result.weight
                total_weight += result.weight
        return total / total_weight if total_weight > 0 else 0.0

    def source_diversity_index(self, state: Dict[str, Any]) -> MetricResult:
        """
        来源多样性指数

        使用 Shannon 多样性指数：H = -sum(pi * ln(pi))
        归一化到 0-1 范围。

        理想情况：有多个不同类型的来源，每个来源贡献均衡。
        """
        facts = state.get("facts", [])
        references = state.get("references", [])

        if not facts and not references:
            return MetricResult(
                "source_diversity", 0.0, 0.15, 0, 10,
                "无事实或引用来源"
            )

        # 统计来源类型分布
        source_types = {}
        for fact in facts:
            st = fact.get("source_type", "unknown")
            source_types[st] = source_types.get(st, 0) + 1
        # 参考文献也计入
        for ref in references:
            source = ref.get("source", "unknown")
            source_types[source] = source_types.get(source, 0) + 1

        total = sum(source_types.values())
        if total == 0:
            return MetricResult("source_diversity", 0.0, 0.15, 0, 10, "无来源数据")

        # Shannon 指数
        h = 0.0
        for count in source_types.values():
            pi = count / total
            if pi > 0:
                h -= pi * math.log(pi)

        # 归一化：最大多样性 = ln(来源类型数)
        max_h = math.log(max(len(source_types), 2))
        normalized = h / max_h if max_h > 0 else 0

        unique_sources = len(set(
            f.get("source_name", "") for f in facts if f.get("source_name")
        ))

        return MetricResult(
            "source_diversity", round(normalized, 3), 0.15,
            unique_sources, 10,
            f"来源类型: {len(source_types)} 种, 唯一来源: {unique_sources}, Shannon H={h:.3f}/H_max={max_h:.3f}"
        )

    def citation_density(self, state: Dict[str, Any]) -> MetricResult:
        """
        引用密度

        每 500 字的引用（来源）数量。
        理想值：3-5 个引用/500 字。
        """
        report = state.get("final_report", "")
        report_len = len(report)
        facts = state.get("facts", [])
        references = state.get("references", [])

        if report_len == 0:
            return MetricResult(
                "citation_density", 0.0, 0.15, 0, 3,
                "报告为空"
            )

        citation_count = len(facts) + len(references)
        per_500 = citation_count / (report_len / 500) if report_len > 0 else 0

        # 评分：3-5 个/500 字为最优，低于或高于都扣分
        if per_500 >= 3 and per_500 <= 5:
            score = 1.0
        elif per_500 < 3:
            score = per_500 / 3
        else:
            # 过多引用也轻微扣分
            score = max(0.7, 1.0 - (per_500 - 5) * 0.05)

        return MetricResult(
            "citation_density", round(score, 3), 0.15,
            round(per_500, 2), 4,
            f"每 500 字 {per_500:.1f} 个引用 (报告 {report_len} 字, {citation_count} 个来源)"
        )

    def recency_score(self, state: Dict[str, Any]) -> MetricResult:
        """
        时效性评分

        引用的数据中有多少是近 2 年的？
        """
        facts = state.get("facts", [])
        if not facts:
            return MetricResult("recency", 0.0, 0.20, 0, 1, "无事实数据")

        current_year = datetime.now().year
        recent_count = 0
        total_dated = 0

        for fact in facts:
            content = fact.get("content", "")
            year_matches = re.findall(r'(20\d{2})年', content)
            if year_matches:
                total_dated += 1
                latest_year = max(int(y) for y in year_matches)
                if current_year - latest_year <= 2:
                    recent_count += 1

        ratio = recent_count / total_dated if total_dated > 0 else 0.5

        return MetricResult(
            "recency", round(ratio, 3), 0.20,
            f"{recent_count}/{total_dated}", 1,
            f"{recent_count}/{total_dated} 条事实使用近 2 年数据"
        )

    def section_completeness(self, state: Dict[str, Any]) -> MetricResult:
        """
        章节完整度

        实际生成的章节数 vs 大纲中的章节数。
        """
        outline = state.get("outline", [])
        draft_sections = state.get("draft_sections", {})
        final_report = state.get("final_report", "")

        if not outline:
            return MetricResult(
                "section_completeness", 0.0, 0.15, 0, 0,
                "无大纲"
            )

        expected = len(outline)
        # 计算有多少章节有内容
        completed = sum(
            1 for s in outline
            if s.get("id") in draft_sections and draft_sections[s.get("id")]
        )
        # 如果最终报告不为空，也算有一定的完整度
        if not completed and final_report:
            completed = max(1, expected // 2)  # 估算

        ratio = completed / expected if expected > 0 else 0

        return MetricResult(
            "section_completeness", round(ratio, 3), 0.15,
            completed, expected,
            f"完成 {completed}/{expected} 个章节"
        )

    def hallucination_rate(self, state: Dict[str, Any]) -> MetricResult:
        """
        幻觉率

        无来源的事实占总事实的比例。越低越好。
        反向指标：分数 = 1 - 幻觉率。
        """
        facts = state.get("facts", [])
        if not facts:
            return MetricResult(
                "hallucination_rate", 0.5, 0.15, "N/A", 0,
                "无事实数据"
            )

        hallucinated = sum(
            1 for f in facts
            if not f.get("source_url") and not f.get("source_name")
        )
        rate = hallucinated / len(facts)
        score = 1 - rate  # 反向：无来源越少越好

        return MetricResult(
            "hallucination_rate", round(score, 3), 0.15,
            hallucinated, 0,
            f"{hallucinated}/{len(facts)} 条事实无来源 (幻觉率 {rate:.1%})"
        )

    def data_richness(self, state: Dict[str, Any]) -> MetricResult:
        """
        数据丰富度

        每 1000 字中的数据点数量。
        理想值：5+ 个数据点/1000 字。
        """
        report = state.get("final_report", "")
        report_len = max(len(report), 1)
        data_points = state.get("data_points", [])
        charts = state.get("charts", [])

        per_1000 = len(data_points) / (report_len / 1000)

        # 评分
        if per_1000 >= 5:
            score = 1.0
        else:
            score = per_1000 / 5

        # 图表加分
        chart_bonus = min(0.2, len(charts) * 0.05)
        score = min(1.0, score + chart_bonus)

        return MetricResult(
            "data_richness", round(score, 3), 0.10,
            round(per_1000, 2), 5,
            f"每千字 {per_1000:.1f} 个数据点, {len(charts)} 个图表"
        )

    def conflict_resolution_rate(self, state: Dict[str, Any]) -> MetricResult:
        """
        冲突解决率

        检测到的冲突中有多少被成功解决（如果有交叉验证模块）。
        """
        conflict_report = state.get("conflict_report", {})
        if not conflict_report:
            # 没有冲突检测，不评分也不扣分
            return MetricResult(
                "conflict_resolution", 0.5, 0.10,
                "N/A", "N/A",
                "未启用交叉验证模块"
            )

        conflicts = conflict_report.get("conflicts", [])
        if not conflicts:
            return MetricResult(
                "conflict_resolution", 1.0, 0.10,
                0, 0,
                "无冲突，无需解决"
            )

        resolved = sum(1 for c in conflicts if c.get("resolved"))
        rate = resolved / len(conflicts) if conflicts else 0

        return MetricResult(
            "conflict_resolution", round(rate, 3), 0.10,
            resolved, len(conflicts),
            f"解决 {resolved}/{len(conflicts)} 个冲突 ({rate:.1%})"
        )


# ============================================================
# Precision / Recall / F1 评估支持
# 面试回答要点：不只关注准确率，还要看 precision/recall/F1
# ============================================================

def compute_precision_recall_f1(
    predictions: List[str],
    ground_truth: List[str],
    tolerance: float = 0.0,
) -> Dict[str, float]:
    """
    计算分类任务的 Precision / Recall / F1。

    用于评估意图识别、工具选择、冲突检测等分类任务的质量。

    面试回答模板：
    "我覆盖了 5 类常见意图 + 3 类边界情况 + 2 类对抗样本，
    评估指标不仅看准确率，还看 precision/recall/F1。
    每次改完 prompt 会自动跑回归测试。"

    Args:
        predictions: 模型预测的标签列表
        ground_truth: 真实标注列表（顺序与 predictions 对应）
        tolerance: 数值容差（用于模糊匹配）

    Returns:
        {"precision": float, "recall": float, "f1": float,
         "tp": int, "fp": int, "fn": int, "total": int}
    """
    if not predictions and not ground_truth:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0, "tp": 0, "fp": 0, "fn": 0, "total": 0}

    tp = sum(1 for p, g in zip(predictions, ground_truth) if p == g)
    fp = sum(1 for p, g in zip(predictions, ground_truth) if p != g)
    fn = max(0, len(ground_truth) - len(predictions))  # 预测少了

    precision = tp / len(predictions) if predictions else 0.0
    recall = tp / len(ground_truth) if ground_truth else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "total": len(ground_truth),
    }


def compute_topic_coverage(
    report: str,
    expected_topics: List[str],
) -> Dict[str, Any]:
    """
    计算报告对预期主题的覆盖度。

    用于评估研究是否覆盖了所有关键主题。
    面试回答：测试集覆盖了哪些 case、分布如何、为什么选这些 case。

    Args:
        report: 研究报告内容
        expected_topics: 期望覆盖的主题列表

    Returns:
        {"covered": int, "total": int, "coverage_rate": float,
         "missing_topics": List[str]}
    """
    covered = [topic for topic in expected_topics if topic in report]
    missing = [topic for topic in expected_topics if topic not in report]

    return {
        "covered": len(covered),
        "total": len(expected_topics),
        "coverage_rate": round(len(covered) / len(expected_topics), 4) if expected_topics else 1.0,
        "covered_topics": covered,
        "missing_topics": missing,
    }


# 便捷函数
def compute_metrics(
    state: Dict[str, Any],
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, MetricResult]:
    """计算所有评估指标"""
    metrics = ResearchMetrics()
    results = metrics.compute_all(state, weights)
    return results
