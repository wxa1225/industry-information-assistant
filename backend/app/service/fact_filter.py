# Copyright © 2026  版权所有

"""
事实过滤器 - Fact Filtering Module

在 Scout 收集事实入库前进行三层过滤：
1. Hash 去重：字面重复检测（快速）
2. 语义去重：向量相似度检测（覆盖同义不同表述）
3. 信息增益评估：新事实是否带来新数值/新实体

解决面试问题："如何区分是真的需要保存的 memory，还是干扰噪音？"
"""

import hashlib
import re
import math
import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class FactFilterResult:
    """过滤结果"""
    accepted: bool                    # 是否接受
    reason: str                       # 拒绝/接受原因
    duplicate_of: Optional[str] = None  # 如果是重复，指向原事实 ID
    info_gain_score: float = 0.0      # 信息增益评分 0-1


class FactFilter:
    """
    事实过滤器

    三层过滤 pipeline：
    1. Hash 去重（字面重复）
    2. 语义去重（向量相似度）
    3. 信息增益（新内容评估）
    """

    # 语义相似度阈值（余弦相似度 > 此值判定为重复）
    SEMANTIC_SIMILARITY_THRESHOLD = 0.85

    # 信息增益最低分数（< 此值标记为低信息量）
    MIN_INFO_GAIN = 0.15

    def __init__(self, use_vector: bool = True):
        """
        Args:
            use_vector: 是否启用向量语义去重（依赖 embedding_service）
        """
        self.use_vector = use_vector
        self._existing_embeddings: Dict[str, List[float]] = {}  # fact_id -> embedding

    def _compute_fact_fingerprint(self, content: str) -> str:
        """计算事实的语义指纹（用于 hash 去重）"""
        numbers = re.findall(r'\d+\.?\d*', content)
        keywords = re.findall(r'[一-龥]{2,4}', content)[:5]
        fingerprint = f"{','.join(numbers[:3])}|{','.join(keywords)}"
        return hashlib.md5(fingerprint.encode()).hexdigest()[:16]

    def _extract_numbers(self, content: str) -> List[str]:
        """提取内容中的数值"""
        return re.findall(r'\d+(?:\.\d+)?(?:亿|万|百|千|兆|%|亿元|万元)?', content)

    def _extract_entities(self, content: str) -> set:
        """提取内容中的关键实体（2-6 字中文词）"""
        return set(re.findall(r'[一-龥]{2,6}', content))

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        """计算余弦相似度"""
        if not v1 or not v2:
            return 0.0
        dot = sum(a * b for a, b in zip(v1, v2))
        norm1 = math.sqrt(sum(a * a for a in v1))
        norm2 = math.sqrt(sum(b * b for b in v2))
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot / (norm1 * norm2)

    def filter(
        self,
        candidate: Dict[str, Any],
        existing_facts: List[Dict[str, Any]],
    ) -> FactFilterResult:
        """
        对候选事实执行三层过滤。

        Args:
            candidate: 待入库的事实
            existing_facts: 已入库的事实列表

        Returns:
            FactFilterResult
        """
        content = candidate.get("content", "")
        source_url = candidate.get("source_url", "")

        # === 第 1 层：Hash 去重 ===
        fingerprint = self._compute_fact_fingerprint(content)
        for fact in existing_facts:
            existing_fp = self._compute_fact_fingerprint(fact.get("content", ""))
            if fingerprint == existing_fp:
                # 同一个来源的相似内容可能是补充信息，保留
                if fact.get("source_url") == source_url:
                    break
                return FactFilterResult(
                    accepted=False,
                    reason=f"字面重复（hash 匹配）",
                    duplicate_of=fact.get("id"),
                )

        # === 第 2 层：语义去重 ===
        if self.use_vector:
            sem_dup = self._check_semantic_duplicate(candidate, existing_facts)
            if sem_dup:
                return sem_dup

        # === 第 3 层：信息增益评估 ===
        info_gain = self._assess_info_gain(candidate, existing_facts)
        if info_gain < self.MIN_INFO_GAIN:
            return FactFilterResult(
                accepted=False,
                reason=f"信息增益过低（{info_gain:.3f}），未带来新数值或新实体",
                info_gain_score=info_gain,
            )

        return FactFilterResult(
            accepted=True,
            reason="通过三层过滤",
            info_gain_score=info_gain,
        )

    def _check_semantic_duplicate(
        self,
        candidate: Dict[str, Any],
        existing_facts: List[Dict[str, Any]],
    ) -> Optional[FactFilterResult]:
        """
        向量语义去重：用 embedding 计算余弦相似度。

        策略：
        1. 对候选事实和已有事实都计算 embedding
        2. 余弦相似度 > 0.85 且来源不同 → 判定为语义重复
        """
        try:
            from service.embedding_service import generate_embedding
        except ImportError:
            try:
                from app.service.embedding_service import generate_embedding
            except ImportError:
                return None  # embedding 不可用，跳过此层

        content = candidate.get("content", "")
        candidate_vector = generate_embedding(content)
        if not candidate_vector:
            return None

        # 缓存候选向量
        cand_id = candidate.get("id", "")
        if cand_id:
            self._existing_embeddings[cand_id] = candidate_vector

        # 与已有事实逐一比对
        for fact in existing_facts:
            fact_id = fact.get("id", "")
            fact_url = fact.get("source_url", "")

            # 同一来源不判定为重复
            if fact_url == candidate.get("source_url", ""):
                continue

            # 获取已有事实的向量（有缓存用缓存，没有就重新计算）
            if fact_id in self._existing_embeddings:
                fact_vector = self._existing_embeddings[fact_id]
            else:
                fact_vector = generate_embedding(fact.get("content", ""))
                if fact_vector:
                    self._existing_embeddings[fact_id] = fact_vector

            if not fact_vector:
                continue

            similarity = self._cosine_similarity(candidate_vector, fact_vector)
            if similarity > self.SEMANTIC_SIMILARITY_THRESHOLD:
                return FactFilterResult(
                    accepted=False,
                    reason=f"语义重复（余弦相似度 {similarity:.3f} > {self.SEMANTIC_SIMILARITY_THRESHOLD}）",
                    duplicate_of=fact_id,
                )

        return None

    def _assess_info_gain(
        self,
        candidate: Dict[str, Any],
        existing_facts: List[Dict[str, Any]],
    ) -> float:
        """
        信息增益评估：新事实相比已有事实带来了多少新信息。

        评估维度：
        1. 新数值（权重 40%）：是否包含已有事实中没有的数值
        2. 新实体（权重 35%）：是否包含已有事实中没有的实体
        3. 来源独特性（权重 25%）：是否来自新的来源

        Returns:
            0-1 的信息增益分数
        """
        content = candidate.get("content", "")
        source_url = candidate.get("source_url", "")
        source_name = candidate.get("source_name", "")

        # 提取候选事实的数值和实体
        cand_numbers = set(self._extract_numbers(content))
        cand_entities = self._extract_entities(content)

        if not cand_numbers and not cand_entities:
            return 0.0  # 纯虚词，无信息量

        # 提取所有已有事实的数值和实体
        existing_numbers = set()
        existing_entities = set()
        existing_sources = set()
        for fact in existing_facts:
            existing_content = fact.get("content", "")
            existing_numbers.update(self._extract_numbers(existing_content))
            existing_entities.update(self._extract_entities(existing_content))
            existing_sources.add(fact.get("source_name", ""))

        # 计算新数值比例
        new_numbers = cand_numbers - existing_numbers
        number_gain = len(new_numbers) / max(len(cand_numbers), 1)

        # 计算新实体比例
        new_entities = cand_entities - existing_entities
        entity_gain = len(new_entities) / max(len(cand_entities), 1)

        # 来源独特性
        source_gain = 1.0 if source_name not in existing_sources else 0.3

        # 加权综合
        total_gain = 0.4 * number_gain + 0.35 * entity_gain + 0.25 * source_gain

        return min(1.0, total_gain)

    def batch_filter(
        self,
        candidates: List[Dict[str, Any]],
        existing_facts: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[FactFilterResult]]:
        """
        批量过滤候选事实。

        Args:
            candidates: 待过滤的事实列表
            existing_facts: 已入库的事实列表

        Returns:
            (接受的事实列表, 所有过滤结果)
        """
        accepted = []
        all_results = []

        # 动态扩展 existing_facts（接受的事实也加入已入库集合，防止候选内部重复）
        current_existing = list(existing_facts)

        for candidate in candidates:
            result = self.filter(candidate, current_existing)
            all_results.append(result)

            if result.accepted:
                accepted.append(candidate)
                current_existing.append(candidate)
            else:
                logger.debug(
                    f"事实过滤: {candidate.get('content', '')[:50]}... "
                    f"→ {result.reason}"
                )

        return accepted, all_results
