# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有

"""
置信度评分器

基于多维度指标计算每个事实的最终置信度：
1. 来源权威性（政府 > 学术 > 权威媒体 > 自媒体）
2. 交叉验证结果（多源佐证 > 单源 > 无佐证）
3. 信息时效性（近 1 年 > 近 2 年 > 2 年以上）
4. 信息具体程度（具体数据 > 模糊描述）

最终置信度 = w1*来源分 + w2*验证分 + w3*时效分 + w4*具体分
"""

from dataclasses import dataclass
from typing import Dict, Any, List, Optional
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

# 来源类型基础评分
SOURCE_TYPE_SCORES = {
    "official": 0.95,       # 政府/官方机构
    "academic": 0.85,       # 学术论文/研究机构
    "report": 0.75,         # 行业报告/咨询报告
    "news": 0.65,           # 权威新闻媒体
    "self_media": 0.30,     # 自媒体/博客
}

# 来源域名加分规则（静态来源评分）
DOMAIN_SCORES = {
    ".gov.cn": 0.10,
    ".edu.cn": 0.08,
    ".ac.cn": 0.06,
    ".org.cn": 0.03,
}

# 权重
WEIGHTS = {
    "source": 0.35,
    "validation": 0.30,
    "recency": 0.20,
    "specificity": 0.15,
}


@dataclass
class ConfidenceResult:
    """置信度评分结果"""
    fact_id: str
    overall_score: float             # 0-1 综合置信度
    source_score: float              # 来源权威性分
    validation_score: float          # 交叉验证分
    recency_score: float             # 时效性分
    specificity_score: float         # 信息具体分
    score_breakdown: Dict[str, Any]  # 详细拆解

    def to_dict(self) -> Dict:
        return {
            "fact_id": self.fact_id,
            "overall_score": round(self.overall_score, 3),
            "source_score": round(self.source_score, 3),
            "validation_score": round(self.validation_score, 3),
            "recency_score": round(self.recency_score, 3),
            "specificity_score": round(self.specificity_score, 3),
            "score_breakdown": self.score_breakdown,
        }


class ConfidenceScorer:
    """
    置信度评分器

    对每个事实计算多维度的置信度评分。
    """

    # 当前年份（用于时效性计算）
    CURRENT_YEAR = datetime.now().year

    def score(
        self,
        fact: Dict[str, Any],
        validation_result: Optional[Dict] = None,
        conflict_pair: Optional[Any] = None,
    ) -> ConfidenceResult:
        """
        计算事实的置信度。

        Args:
            fact: 事实字典（来自 ResearchState["facts"]）
            validation_result: 交叉验证结果（如果有）
            conflict_pair: 冲突对信息（如果有）

        Returns:
            ConfidenceResult
        """
        source_score = self._score_source(fact)
        validation_score = self._score_validation(fact, validation_result)
        recency_score = self._score_recency(fact)
        specificity_score = self._score_specificity(fact)

        # 加权综合
        overall = (
            WEIGHTS["source"] * source_score
            + WEIGHTS["validation"] * validation_score
            + WEIGHTS["recency"] * recency_score
            + WEIGHTS["specificity"] * specificity_score
        )

        # 如果存在未解决的冲突，降低置信度
        if conflict_pair and not conflict_pair.resolved:
            penalty = {"critical": 0.3, "major": 0.15, "minor": 0.05}
            overall *= (1 - penalty.get(conflict_pair.severity, 0.1))

        breakdown = {
            "weights": WEIGHTS,
            "source_type": fact.get("source_type", "unknown"),
            "source_name": fact.get("source_name", ""),
            "source_url": fact.get("source_url", ""),
        }

        return ConfidenceResult(
            fact_id=fact.get("id", ""),
            overall_score=max(0.0, min(1.0, overall)),
            source_score=source_score,
            validation_score=validation_score,
            recency_score=recency_score,
            specificity_score=specificity_score,
            score_breakdown=breakdown,
        )

    def score_all(
        self,
        facts: List[Dict[str, Any]],
        validation_results: Optional[Dict[str, Dict]] = None,
        conflict_pairs: Optional[List] = None,
    ) -> Dict[str, ConfidenceResult]:
        """
        批量计算所有事实的置信度。

        Returns:
            {fact_id: ConfidenceResult}
        """
        results = {}

        # 构建冲突映射
        conflict_map: Dict[str, Any] = {}
        if conflict_pairs:
            for cp in conflict_pairs:
                fact_a_id = cp.fact_a.get("id", "")
                fact_b_id = cp.fact_b.get("id", "")
                conflict_map[fact_a_id] = cp
                conflict_map[fact_b_id] = cp

        for fact in facts:
            fid = fact.get("id", "")
            val_result = validation_results.get(fid) if validation_results else None
            cp = conflict_map.get(fid)
            results[fid] = self.score(fact, val_result, cp)

        return results

    def _score_source(self, fact: Dict[str, Any]) -> float:
        """
        来源权威性评分。

        基础分由来源类型决定，额外考虑域名质量和历史可信度。
        """
        source_type = fact.get("source_type", "news")
        base_score = SOURCE_TYPE_SCORES.get(source_type, 0.5)

        # 域名加分
        source_url = fact.get("source_url", "")
        domain_bonus = 0.0
        for domain, bonus in DOMAIN_SCORES.items():
            if domain in source_url:
                domain_bonus = max(domain_bonus, bonus)
                break

        return min(1.0, base_score + domain_bonus)

    def _score_validation(
        self,
        fact: Dict[str, Any],
        validation_result: Optional[Dict] = None,
    ) -> float:
        """
        交叉验证评分。

        - 被其他来源佐证：+分
        - 无验证信息：中性分
        - 被其他来源矛盾：-分
        """
        if validation_result:
            status = validation_result.get("status", "")
            if status == "corroborated":
                return 0.9
            elif status == "contradicted":
                return 0.2
            elif status == "inconclusive":
                return 0.5

        # 没有验证结果时，根据来源数量给一个基础分
        credibility = fact.get("credibility_score", 0.5)
        return credibility * 0.6  # 无验证时打六折

    def _score_recency(self, fact: Dict[str, Any]) -> float:
        """
        时效性评分。

        根据事实中提取的年份判断数据的新鲜度。
        """
        content = fact.get("content", "")
        extracted_at = fact.get("extracted_at", "")

        # 尝试从内容中提取年份
        year_matches = re.findall(r'(20\d{2})年', content)
        if year_matches:
            latest_year = max(int(y) for y in year_matches)
            age = self.CURRENT_YEAR - latest_year
            if age <= 0:
                return 1.0      # 当年数据
            elif age <= 1:
                return 0.9      # 近 1 年
            elif age <= 2:
                return 0.7      # 近 2 年
            elif age <= 3:
                return 0.5      # 近 3 年
            else:
                return 0.3      # 3 年以上

        # 无法提取年份时，根据提取时间判断
        if extracted_at:
            try:
                from datetime import datetime
                if isinstance(extracted_at, str):
                    dt = datetime.fromisoformat(extracted_at)
                else:
                    dt = extracted_at
                age_days = (datetime.now() - dt).days
                if age_days <= 30:
                    return 0.8
                elif age_days <= 365:
                    return 0.6
                else:
                    return 0.4
            except Exception:
                pass

        return 0.5  # 默认中性分

    def _score_specificity(self, fact: Dict[str, Any]) -> float:
        """
        信息具体程度评分。

        基于内容长度、是否包含具体数值、是否有来源链接等维度。
        """
        content = fact.get("content", "")
        source_url = fact.get("source_url", "")

        score = 0.0

        # 内容长度
        if len(content) > 100:
            score += 0.4
        elif len(content) > 50:
            score += 0.3
        elif len(content) > 20:
            score += 0.2
        else:
            score += 0.1

        # 是否包含具体数值
        numbers = re.findall(r'\d+(?:\.\d+)?', content)
        if len(numbers) >= 3:
            score += 0.3
        elif len(numbers) >= 1:
            score += 0.2
        else:
            score += 0.1

        # 是否有来源链接
        if source_url:
            score += 0.3
        else:
            score += 0.1

        return min(1.0, score)
