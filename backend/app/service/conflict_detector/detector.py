# Copyright © 2026  版权所有

"""
冲突检测器

从事实列表中自动检测矛盾事实对。

检测策略：
1. 数值提取：从每个事实中提取关键数值
2. 语义分组：基于关键词重叠将相似主题的事实分组
3. 矛盾判断：同组内数值差异超过阈值则标记为冲突
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Tuple, Optional

logger = logging.getLogger(__name__)


@dataclass
class ConflictPair:
    """一对冲突的事实"""
    fact_a: Dict[str, Any]
    fact_b: Dict[str, Any]
    conflict_type: str           # "numerical" | "qualitative" | "temporal"
    field_name: str              # 冲突的字段名（如 "market_size"）
    value_a: str                 # 事实 A 的冲突值
    value_b: str                 # 事实 B 的冲突值
    description: str             # 冲突描述
    severity: str = "major"      # "critical" | "major" | "minor"
    resolved: bool = False
    resolution: str = ""         # 解决结果描述
    verification_search_done: bool = False

    def to_dict(self) -> Dict:
        return {
            "fact_a_id": self.fact_a.get("id", ""),
            "fact_b_id": self.fact_b.get("id", ""),
            "conflict_type": self.conflict_type,
            "field_name": self.field_name,
            "value_a": self.value_a,
            "value_b": self.value_b,
            "description": self.description,
            "severity": self.severity,
            "resolved": self.resolved,
            "resolution": self.resolution,
            "verification_search_done": self.verification_search_done,
        }


class ConflictDetector:
    """
    冲突检测器

    核心方法 detect() 从事实列表中找出矛盾对。
    """

    # 数值提取正则：匹配常见中文数字表达
    # 支持：1000亿、5.2%、3000万、12.5万亿元、500亿元 等
    NUMBER_PATTERN = re.compile(
        r'(\d+(?:\.\d+)?)\s*(亿|万|百万|千万|百亿|千亿|兆|'
        r'%|亿元|万亿元|百万元|千万|亿元|个|家|款|台|万辆)?',
        re.IGNORECASE
    )

    # 用于分组的关键词提取（排除常见虚词）
    STOP_WORDS = {
        '的', '了', '是', '在', '和', '与', '及', '或', '等', '也', '都',
        '这', '那', '其', '被', '将', '对', '为', '于', '从', '到', '中',
        '年', '月', '日',
        # 常见泛化词（这些词在所有事实中都会出现，无区分度）
        '达到', '约为', '增长', '预计', '同比', '较', '去年', '今年',
        '达到', '超过', '低于', '高于', '之间', '左右',
        '提供', '支持', '推动', '促进', '发展', '建设',
    }

    # 关键指标词（高权重）
    KEY_INDICATORS = {
        '市场规模', '营收', '利润', '增长率', '渗透率', '用户数',
        '出货量', '份额', '市值', '投资', '融资', '估值',
        '芯片', 'GPU', 'CPU', 'AI', '算力', '数据中心',
    }

    # 定性结论关键词（用于检测方向性矛盾）
    # 格式：{方向标签: [关键词列表]}
    CONCLUSION_KEYWORDS = {
        'up': ['增长', '上升', '扩大', '攀升', '加速', '利好', '繁荣', '爆发', '回暖', '复苏', '扩张'],
        'down': ['下降', '萎缩', '缩减', '回落', '减速', '利空', '低迷', '下滑', '收缩', '萧条', '衰退', '放缓'],
        'positive': ['看好', '乐观', '领先', '优势', '突破', '成功', '达成', '落地', '超额'],
        'negative': ['看空', '悲观', '落后', '风险', '受阻', '失败', '不及预期', '暴雷', '亏损'],
    }

    def __init__(self, conflict_threshold: float = 0.3):
        """
        Args:
            conflict_threshold: 数值差异阈值。两组数值相对差异超过此比例才标记为冲突。
        """
        self.conflict_threshold = conflict_threshold

    def detect(self, facts: List[Dict[str, Any]]) -> List[ConflictPair]:
        """
        从事实列表中检测冲突对。

        Args:
            facts: 事实列表（来自 ResearchState["facts"]）

        Returns:
            冲突对列表
        """
        if len(facts) < 2:
            return []

        logger.info(f"[ConflictDetector] 开始检测 {len(facts)} 条事实中的冲突")

        # 1. 对每条事实提取数值和关键词
        extracted = []
        for fact in facts:
            content = fact.get("content", "")
            numbers = self._extract_numbers(content)
            keywords = self._extract_keywords(content)
            # 至少有一个数值才考虑纳入冲突检测
            if numbers:
                extracted.append({
                    "fact": fact,
                    "numbers": numbers,
                    "keywords": keywords,
                    "content": content,
                })

        # 2. 语义分组：找出主题相似的事实对
        candidate_pairs = []
        for i in range(len(extracted)):
            for j in range(i + 1, len(extracted)):
                similarity = self._compute_similarity(extracted[i], extracted[j])
                if similarity > 0.15:  # 低门槛，宁可多判不可漏
                    candidate_pairs.append((extracted[i], extracted[j], similarity))

        logger.info(f"[ConflictDetector] 找到 {len(candidate_pairs)} 对候选相似事实")

        # 3. 在同主题事实对中检测数值矛盾
        conflicts = []
        seen_pairs = set()  # 防止重复

        for a, b, sim in candidate_pairs:
            fact_a = a["fact"]
            fact_b = b["fact"]

            # 同一事实跳过
            if fact_a.get("id") == fact_b.get("id"):
                continue
            pair_key = tuple(sorted([fact_a.get("id", ""), fact_b.get("id", "")]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            # 检查数值冲突
            numerical_conflicts = self._check_numerical_conflict(a, b)
            conflicts.extend(numerical_conflicts)

            # 检查定性结论矛盾（仅当数值冲突未检测到且关键词重叠足够高时）
            if not numerical_conflicts and sim > 0.25:
                qual_conflict = self._check_qualitative_conflict(a, b)
                if qual_conflict:
                    conflicts.append(qual_conflict)

        # 4. 定性矛盾检测（独立于数值检测，对所有事实执行）
        all_facts_extracted = []
        for fact in facts:
            content = fact.get("content", "")
            direction = self._extract_conclusion_direction(content)
            all_facts_extracted.append({
                "fact": fact,
                "content": content,
                "direction": direction,
            })

        for i in range(len(all_facts_extracted)):
            for j in range(i + 1, len(all_facts_extracted)):
                a = all_facts_extracted[i]
                b = all_facts_extracted[j]
                pair_key = tuple(sorted([a["fact"].get("id", ""), b["fact"].get("id", "")]))
                if pair_key in seen_pairs:
                    continue

                qual = self._check_qualitative_conflict(a, b)
                if qual:
                    conflicts.append(qual)
                    seen_pairs.add(pair_key)

        logger.info(f"[ConflictDetector] 检测到 {len(conflicts)} 个冲突")
        return conflicts

    def _extract_conclusion_direction(self, text: str) -> Dict[str, float]:
        """
        从文本中提取结论方向性得分。

        Returns:
            {direction_label: score} 如 {'up': 0.8, 'down': 0.2}
        """
        direction_scores = {}
        for direction, keywords in self.CONCLUSION_KEYWORDS.items():
            count = sum(1 for kw in keywords if kw in text)
            direction_scores[direction] = count / max(len(keywords), 1)
        return direction_scores

    def _check_qualitative_conflict(
        self, a: Dict, b: Dict
    ) -> Optional[ConflictPair]:
        """
        检测定性结论矛盾。

        策略：
        1. 两个事实有足够高的关键词重叠（谈论同一话题）
        2. 但结论方向相反（一个说增长，一个说萎缩）

        Args:
            a, b: 可以是 {'fact': ..., 'content': ..., 'direction': ...}
                  也可以是 {'fact': ..., 'content': ..., 'keywords': ..., 'numbers': ...}

        Returns:
            ConflictPair 或 None
        """
        content_a = a.get("content", "")
        content_b = b.get("content", "")

        # 提取方向性得分（优先使用预计算的 direction，否则现场提取）
        dir_a = a.get("direction") or self._extract_conclusion_direction(content_a)
        dir_b = b.get("direction") or self._extract_conclusion_direction(content_b)

        # 检查是否有方向性冲突
        # up vs down 矛盾
        a_up, a_down = dir_a.get('up', 0), dir_a.get('down', 0)
        b_up, b_down = dir_b.get('up', 0), dir_b.get('down', 0)

        # 正向 vs 负向矛盾
        a_pos, a_neg = dir_a.get('positive', 0), dir_a.get('negative', 0)
        b_pos, b_neg = dir_b.get('positive', 0), dir_b.get('negative', 0)

        conflict_detected = False
        conflict_label = ""

        # 增长 vs 萎缩
        if (a_up >= 0.15 and b_down >= 0.15) or (a_down >= 0.15 and b_up >= 0.15):
            conflict_detected = True
            conflict_label = "方向矛盾"

        # 看好 vs 看空
        if (a_pos >= 0.15 and b_neg >= 0.15) or (a_neg >= 0.15 and b_pos >= 0.15):
            conflict_detected = True
            conflict_label = "判断矛盾"

        if not conflict_detected:
            return None

        fact_a = a.get("fact", {})
        fact_b = b.get("fact", {})

        # 严重程度：基于方向得分差异
        max_diff = max(
            abs(a_up - b_up) + abs(a_down - b_down),
            abs(a_pos - b_pos) + abs(a_neg - b_neg),
        )
        severity = "critical" if max_diff > 0.5 else "major" if max_diff > 0.3 else "minor"

        desc = (
            f"事实 [{fact_a.get('id', '?')}]（来源: {fact_a.get('source_name', '?')}）"
            f"与事实 [{fact_b.get('id', '?')}]（来源: {fact_b.get('source_name', '?')}）"
            f"存在{conflict_label}："
            f"'{content_a[:60]}...' vs '{content_b[:60]}...'"
        )

        return ConflictPair(
            fact_a=fact_a,
            fact_b=fact_b,
            conflict_type="qualitative",
            field_name=conflict_label,
            value_a=content_a[:80],
            value_b=content_b[:80],
            description=desc,
            severity=severity,
        )

    def _extract_numbers(self, text: str) -> List[Tuple[float, str]]:
        """
        从文本中提取数值。

        Returns:
            [(数值, 原始文本), ...]
        """
        results = []
        for match in self.NUMBER_PATTERN.finditer(text):
            num_str = match.group(1)
            unit = match.group(2) or ""
            num = float(num_str)

            # 过滤年份（如 2024 不带单位时不是数据值）
            if not unit and 1900 <= num <= 2100:
                continue

            # 转换为统一单位（基础值）
            if unit in ("亿", "亿元"):
                num *= 1e8
            elif unit in ("万", "万元"):
                num *= 1e4
            elif unit == "百万":
                num *= 1e6
            elif unit == "千万":
                num *= 1e7
            elif unit in ("百亿"):
                num *= 1e10
            elif unit in ("千亿"):
                num *= 1e11
            elif unit == "兆":
                num *= 1e12
            elif unit == "万亿元":
                num *= 1e12
            elif unit == "百万元":
                num *= 1e6
            elif unit == "%":
                # 百分比保持不变
                pass
            results.append((num, match.group(0)))
        return results

    def _extract_keywords(self, text: str) -> set:
        """
        提取关键词。

        策略：使用正则提取有意义的中文名词短语（2-6 字符），排除停用词。
        同时提取关键指标词。
        """
        keywords = set()

        # 提取关键指标（高权重，直接匹配）
        for indicator in self.KEY_INDICATORS:
            if indicator in text:
                keywords.add(indicator)

        # 提取 2-6 字符的中文连续词（排除纯数字和停用词）
        phrases = re.findall(r'[一-龥]{2,6}', text)
        for phrase in phrases:
            if phrase not in self.STOP_WORDS and not phrase.isdigit():
                keywords.add(phrase)

        return keywords

    def _compute_similarity(self, a: Dict, b: Dict) -> float:
        """计算两个事实的语义相似度（Jaccard 重叠度）"""
        keywords_a = a["keywords"]
        keywords_b = b["keywords"]
        if not keywords_a or not keywords_b:
            return 0.0
        intersection = keywords_a & keywords_b
        union = keywords_a | keywords_b
        return len(intersection) / len(union)

    def _check_numerical_conflict(
        self, a: Dict, b: Dict
    ) -> List[ConflictPair]:
        """
        检查两个事实之间的数值矛盾。

        策略：
        - 如果两个事实有超过 2 个数值，检查是否有共同范围的数值差异过大
        - 如果两个事实都在谈论同一指标（如市场规模），但数值差异超过阈值
        """
        nums_a = a["numbers"]
        nums_b = b["numbers"]
        conflicts = []

        # 简单策略：比较最大的数值
        # 如果两者的最大数值差异超过阈值，则标记为冲突
        if nums_a and nums_b:
            max_a_val, max_a_raw = max(nums_a, key=lambda x: x[0])
            max_b_val, max_b_raw = max(nums_b, key=lambda x: x[0])

            # 避免比较百分比和绝对数值
            # 只比较同一数量级内的数值（差 3 个数量级以内）
            if max_a_val > 0 and max_b_val > 0:
                ratio = max(max_a_val, max_b_val) / min(max_a_val, max_b_val)
                # 差异超过阈值才标记为冲突
                # conflict_threshold=0.3 时，ratio > 1.3 即判定为冲突
                if ratio > (1 + self.conflict_threshold):
                    fact_a = a["fact"]
                    fact_b = b["fact"]

                    # 判断严重程度
                    if ratio > 10:
                        severity = "critical"
                    elif ratio > 3:
                        severity = "major"
                    else:
                        severity = "minor"

                    desc = (
                        f"事实 [{fact_a.get('id', '?')}] 提到 '{max_a_raw}' "
                        f"（来源: {fact_a.get('source_name', '?')}）"
                        f"，与事实 [{fact_b.get('id', '?')}] 提到 '{max_b_raw}' "
                        f"（来源: {fact_b.get('source_name', '?')}）"
                        f"存在矛盾（相差约 {ratio:.1f} 倍）"
                    )

                    conflicts.append(ConflictPair(
                        fact_a=fact_a,
                        fact_b=fact_b,
                        conflict_type="numerical",
                        field_name="数值",
                        value_a=max_a_raw,
                        value_b=max_b_raw,
                        description=desc,
                        severity=severity,
                    ))

        return conflicts

    def detect_llm_assisted(
        self, facts: List[Dict[str, Any]], llm_call_fn
    ) -> List[ConflictPair]:
        """
        LLM 辅助冲突检测

        当规则检测不够用时，用 LLM 做一轮矛盾分析。
        作为规则检测的补充，不是替代。

        Args:
            facts: 事实列表
            llm_call_fn: 异步 LLM 调用函数（接受 system_prompt, user_prompt, 返回 JSON）

        Returns:
            补充检测到的冲突对
        """
        if len(facts) < 3:
            return []

        # 只取前 15 条事实，避免 prompt 太长
        facts_subset = facts[:15]
        facts_text = "\n".join([
            f"[{f.get('id', '?')}] {f.get('content', '')[:200]} (来源: {f.get('source_name', '?')})"
            for f in facts_subset
        ])

        system_prompt = "你是一个事实一致性分析专家。你的任务是找出事实之间的矛盾。"
        user_prompt = f"""以下是从不同来源收集到的事实列表。请找出其中互相矛盾的事实对。

## 事实列表
{facts_text}

## 任务
找出所有互相矛盾的事实对。矛盾可以是：
1. 数值矛盾（同一指标但数据差异很大）
2. 结论矛盾（对同一事物给出相反的判断）
3. 时间矛盾（不同时间点的描述互相矛盾）

输出JSON格式：
```json
{{
    "conflicts": [
        {{
            "fact_a_id": "矛盾事实A的ID",
            "fact_b_id": "矛盾事实B的ID",
            "conflict_type": "numerical/qualitative/temporal",
            "description": "矛盾描述",
            "severity": "critical/major/minor"
        }}
    ]
}}
```

如果没有发现矛盾，输出 {{"conflicts": []}}。"""

        try:
            # 这里需要外部传入的 LLM 调用函数
            # 因为此模块不直接依赖 BaseAgent
            response = llm_call_fn(system_prompt, user_prompt)
            # 返回结果会被上层转换为 ConflictPair 对象
            return response
        except Exception as e:
            logger.warning(f"[ConflictDetector] LLM 辅助冲突检测失败: {e}")
            return []
