# Copyright © 2026  版权所有

"""
记忆噪声过滤器 - Memory Noise Filter

在长期记忆存储前进行三层过滤：
1. 哈希去重 — 完全相同的内容不重复存储
2. 语义相似度过滤 — 与已有记忆高度相似（>0.9）的视为噪声
3. 信息增益过滤 — 内容过于短、无实质信息、纯闲聊类内容过滤掉
4. 价值评分 — 根据信息密度、事实性、主题相关性评分，低于阈值的丢弃

这确保了长期记忆库中只保留高价值信息，避免"垃圾进、垃圾出"。
"""

import hashlib
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# 噪声过滤阈值
SEMANTIC_SIMILARITY_THRESHOLD = 0.90    # 语义相似度超过此值视为重复
INFORMATION_GAIN_THRESHOLD = 0.15       # 信息增益低于此值视为噪声
MIN_CONTENT_LENGTH = 20                 # 最小内容长度（字符）
MIN_VALUE_SCORE = 0.30                  # 最低价值评分


class MemoryNoiseFilter:
    """
    记忆噪声过滤器

    在记忆存储前过滤噪声，确保只保留有价值的信息。
    """

    def __init__(self):
        # 已存储内容的指纹集合（用于去重）
        self._content_hashes: set = set()
        # 已存储内容的摘要列表（用于相似度比较）
        self._stored_summaries: List[str] = []

    def register_existing_memories(self, summaries: List[str]):
        """
        注册已有记忆的摘要，用于后续噪声判断。

        通常在服务启动时调用，从数据库加载已有记忆摘要。
        """
        self._stored_summaries = summaries
        for summary in summaries:
            self._content_hashes.add(self._compute_hash(summary))

    def is_noise(
        self,
        content: str,
        semantic_similarity_fn=None,
    ) -> tuple[bool, str]:
        """
        判断内容是否为噪声。

        Args:
            content: 待判断的内容
            semantic_similarity_fn: 可选的语义相似度计算函数，
                接受 (new_text, existing_text) 返回 0-1 的相似度分数

        Returns:
            (is_noise, reason) — 是否为噪声及原因
        """
        # 1. 长度过滤
        if len(content.strip()) < MIN_CONTENT_LENGTH:
            return True, f"内容过短（{len(content)} < {MIN_CONTENT_LENGTH}字符）"

        # 2. 哈希去重
        content_hash = self._compute_hash(content)
        if content_hash in self._content_hashes:
            return True, "与已有记忆完全重复"

        # 3. 语义去重（需要外部提供相似度函数）
        if semantic_similarity_fn is not None:
            for existing in self._stored_summaries:
                similarity = semantic_similarity_fn(content, existing)
                if similarity >= SEMANTIC_SIMILARITY_THRESHOLD:
                    return True, f"与已有记忆语义相似度过高（{similarity:.2f} >= {SEMANTIC_SIMILARITY_THRESHOLD}）"

        # 4. 信息增益评估
        info_gain = self._estimate_information_gain(content)
        if info_gain < INFORMATION_GAIN_THRESHOLD:
            return True, f"信息增益过低（{info_gain:.3f} < {INFORMATION_GAIN_THRESHOLD}）"

        # 5. 价值评分
        value_score = self._compute_value_score(content)
        if value_score < MIN_VALUE_SCORE:
            return True, f"价值评分过低（{value_score:.2f} < {MIN_VALUE_SCORE}）"

        return False, ""

    def compute_value_score(self, content: str) -> float:
        """
        计算内容的价值评分（0-1）。

        评分维度：
        - 信息密度：单位长度的信息量
        - 事实性：包含具体数据、实体、事件的程度
        - 主题相关性：与用户关注领域的相关性
        """
        score = 0.0

        # 信息密度（0-0.4）
        density = self._compute_information_density(content)
        score += density * 0.4

        # 事实性（0-0.35）
        factuality = self._compute_factuality(content)
        score += factuality * 0.35

        # 完整性（0-0.25）
        completeness = self._compute_completeness(content)
        score += completeness * 0.25

        return min(score, 1.0)

    def _compute_hash(self, content: str) -> str:
        """计算内容哈希"""
        normalized = content.strip().lower()
        return hashlib.md5(normalized.encode("utf-8")).hexdigest()

    def _estimate_information_gain(self, content: str) -> float:
        """
        估算信息增益（0-1）。

        基于：
        - 实体密度（人名、机构名、数字等）
        - 新词比例（相对于常用停用词）
        - 句式复杂度
        """
        # 停用词列表（常见无信息量词汇）
        stopwords = {
            "的", "了", "是", "在", "我", "你", "他", "她", "它",
            "们", "这", "那", "有", "不", "也", "就", "都", "会",
            "可以", "什么", "怎么", "为什么", "啊", "呢", "吧",
            "the", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would",
            "could", "should", "may", "might", "must", "shall",
            "and", "or", "but", "if", "then", "else", "when",
            "at", "by", "for", "with", "about", "to", "from", "in", "on",
        }

        # 分词（简单按字符分割，中文不适用但可以过滤停用词）
        words = content.split()
        if not words:
            return 0.0

        # 新词比例
        meaningful_words = [w for w in words if w.lower() not in stopwords]
        new_word_ratio = len(meaningful_words) / len(words)

        # 数字密度（包含数字通常意味着具体信息）
        digit_count = sum(1 for c in content if c.isdigit())
        digit_density = min(digit_count / len(content), 0.1) / 0.1  # 归一化到 0-1

        # 实体密度（标点符号密度暗示信息密度）
        punct_count = sum(1 for c in content if c in "，。！？；：、,.!?;:")
        punct_density = min(punct_count / len(content) * 20, 1.0)

        # 综合评分
        info_gain = (
            new_word_ratio * 0.4 +
            digit_density * 0.3 +
            punct_density * 0.3
        )

        return min(info_gain, 1.0)

    def _compute_information_density(self, content: str) -> float:
        """
        计算信息密度（0-1）。

        基于唯一字符比例和句子数量。
        """
        if not content:
            return 0.0

        # 唯一字符比例
        unique_chars = len(set(content))
        char_diversity = unique_chars / len(content)

        # 句子数量（按标点分隔）
        sentences = [s.strip() for s in content.split("。") if s.strip()]
        sentence_count = len(sentences)
        sentence_density = min(sentence_count / max(len(content) / 50, 1), 1.0)

        return min((char_diversity + sentence_density) / 2, 1.0)

    def _compute_factuality(self, content: str) -> float:
        """
        计算事实性评分（0-1）。

        基于：
        - 数字/百分比出现频率
        - 专有名词密度
        - 时间和地点实体
        """
        if not content:
            return 0.0

        score = 0.0

        # 数字密度
        import re
        numbers = re.findall(r"\d+\.?\d*%?", content)
        number_density = min(len(numbers) / max(len(content) / 20, 1), 1.0)
        score += number_density * 0.4

        # 特定事实性关键词
        factual_keywords = [
            "增长", "下降", "达到", "超过", "低于", "约", "同比", "环比",
            "占", "贡献", "突破", "创", "历史", "首次", "发布", "数据",
            "亿", "万", "美元", "元", "倍", "率",
        ]
        keyword_count = sum(1 for kw in factual_keywords if kw in content)
        keyword_density = min(keyword_count / 3, 1.0)
        score += keyword_density * 0.35

        # 专有名词（大写字母开头的英文词或中文引号内容）
        proper_nouns = re.findall(r'[A-Z][a-zA-Z]+|".*?"', content)
        proper_noun_density = min(len(proper_nouns) / max(len(content) / 30, 1), 1.0)
        score += proper_noun_density * 0.25

        return min(score, 1.0)

    def _compute_completeness(self, content: str) -> float:
        """
        计算完整性评分（0-1）。

        评估内容是否表达了一个完整的观点或信息。
        """
        if not content:
            return 0.0

        score = 0.0

        # 是否有完整的句子结构（有句号结尾）
        if content.rstrip().endswith(("。", "！", "？", ".", "!", "?")):
            score += 0.3

        # 是否包含因果/条件关系
        import re
        relations = re.findall(r"因为|所以|由于|因此|因而|导致|使得|从而|如果|那么|则", content)
        relation_density = min(len(relations) / 2, 1.0)
        score += relation_density * 0.35

        # 长度适当（不是太短也不是过长）
        length_score = min(len(content) / 500, 1.0)  # 500字以内给满分
        score += length_score * 0.35

        return min(score, 1.0)

    def add_to_registry(self, content: str):
        """将内容注册到已存储集合（在成功存储后调用）"""
        self._content_hashes.add(self._compute_hash(content))
        self._stored_summaries.append(content)
