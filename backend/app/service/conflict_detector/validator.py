# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有

"""
交叉验证器

对检测到的冲突事实发起补充搜索，寻找第三方证据来解决矛盾。

策略：
1. 从冲突对中提取关键实体和指标，生成验证搜索词
2. 调用搜索 API 获取第三方来源
3. 用 LLM 分析搜索结果，判断哪方更可信
4. 返回验证结果
"""

import logging
import asyncio
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Callable, Awaitable

from .detector import ConflictPair

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """交叉验证结果"""
    conflict_pair: ConflictPair
    status: str                   # "corroborated" | "contradicted" | "inconclusive"
    evidence_summary: str         # 证据摘要
    supporting_sources: List[str] # 支持的事实来源
    contradicting_sources: List[str]  # 矛盾的事实来源
    verdict: str                  # 最终判定描述
    confidence: float = 0.5       # 验证结果的置信度 0-1
    search_queries_used: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "fact_a_id": self.conflict_pair.fact_a.get("id", ""),
            "fact_b_id": self.conflict_pair.fact_b.get("id", ""),
            "status": self.status,
            "evidence_summary": self.evidence_summary,
            "supporting_sources": self.supporting_sources,
            "contradicting_sources": self.contradicting_sources,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "search_queries_used": self.search_queries_used,
        }


class CrossValidator:
    """
    交叉验证器

    对冲突事实对执行补充搜索和第三方验证。
    """

    # 验证搜索 prompt
    VERIFICATION_PROMPT = """你是一位事实核查专家。现在有两条来自不同来源的信息互相矛盾。
请分析以下信息，并判断哪条更可信。

## 矛盾信息 A
来源: {source_a_name}
内容: {content_a}

## 矛盾信息 B
来源: {source_b_name}
内容: {content_b}

## 矛盾描述
{conflict_description}

## 第三方验证结果（补充搜索得到的信息）
{search_results}

## 任务
基于以上第三方验证信息，判断：
1. 信息 A 还是信息 B 更可信？还是都无法确认？
2. 理由是什么？

输出JSON：
```json
{{
    "status": "corroborated_a/corroborated_b/inconclusive",
    "evidence_summary": "证据摘要",
    "verdict": "判定描述",
    "confidence": 0.0-1.0
}}
```"""

    def __init__(
        self,
        llm_call_fn: Callable,
        search_fn: Optional[Callable] = None,
    ):
        """
        Args:
            llm_call_fn: 异步 LLM 调用函数，签名: async fn(system_prompt, user_prompt) -> str
            search_fn: 异步搜索函数，签名: async fn(query: str) -> List[Dict]。
                       如果为 None，则跳过实际搜索，仅做 LLM 分析。
        """
        self.llm_call_fn = llm_call_fn
        self.search_fn = search_fn

    async def validate(
        self,
        conflict: ConflictPair,
        max_search_results: int = 5,
    ) -> ValidationResult:
        """
        对单个冲突对执行交叉验证。

        Args:
            conflict: 冲突对
            max_search_results: 最大搜索结果数

        Returns:
            ValidationResult
        """
        logger.info(
            f"[CrossValidator] 开始验证冲突: "
            f"事实 [{conflict.fact_a.get('id', '?')}] vs [{conflict.fact_b.get('id', '?')}]"
        )

        # 1. 生成验证搜索词
        search_queries = self._generate_search_queries(conflict)

        # 2. 执行补充搜索
        search_results_text = "（未执行补充搜索）"
        all_results = []
        if self.search_fn and search_queries:
            all_results = await self._execute_searches(search_queries, max_search_results)
            if all_results:
                search_results_text = self._format_search_results(all_results)

        # 3. 调用 LLM 分析验证结果
        verdict = await self._analyze_with_llm(
            conflict, search_results_text, all_results
        )

        # 4. 标记冲突对为已验证
        conflict.verification_search_done = True
        conflict.resolved = verdict["status"] != "inconclusive"
        conflict.resolution = verdict.get("verdict", "")

        result = ValidationResult(
            conflict_pair=conflict,
            status=verdict.get("status", "inconclusive"),
            evidence_summary=verdict.get("evidence_summary", ""),
            supporting_sources=self._extract_supporting_sources(verdict, all_results),
            contradicting_sources=[],
            verdict=verdict.get("verdict", ""),
            confidence=verdict.get("confidence", 0.5),
            search_queries_used=search_queries,
        )

        logger.info(
            f"[CrossValidator] 验证完成: {result.status}, 置信度: {result.confidence}"
        )
        return result

    async def validate_all(
        self,
        conflicts: List[ConflictPair],
        max_per_conflict: int = 5,
    ) -> List[ValidationResult]:
        """批量验证所有冲突（并行执行）。"""
        if not conflicts:
            return []

        async def _validate_one(conflict: ConflictPair) -> ValidationResult:
            try:
                return await self.validate(conflict, max_per_conflict)
            except Exception as e:
                logger.error(f"[CrossValidator] 验证失败: {e}")
                return ValidationResult(
                    conflict_pair=conflict,
                    status="inconclusive",
                    evidence_summary=f"验证失败: {e}",
                    supporting_sources=[],
                    contradicting_sources=[],
                    verdict="验证失败",
                    confidence=0.0,
                )

        tasks = [_validate_one(c) for c in conflicts]
        results = await asyncio.gather(*tasks)
        return list(results)

    def _generate_search_queries(self, conflict: ConflictPair) -> List[str]:
        """从冲突对中提取关键实体，生成验证搜索词。"""
        content_a = conflict.fact_a.get("content", "")
        content_b = conflict.fact_b.get("content", "")

        # 简单策略：从两个事实中提取公共关键词 + 差异数值
        import re
        # 提取可能的关键实体（长度 2-8 的中文字符串）
        entities_a = re.findall(r'[一-龥]{2,8}', content_a)
        entities_b = re.findall(r'[一-龥]{2,8}', content_b)

        # 找公共实体
        common = set(entities_a) & set(entities_b)
        # 过滤掉常见虚词
        stopwords = {'的', '了', '是', '在', '和', '与', '及', '或', '等', '也', '都', '中国', '市场', '行业'}
        common = [e for e in common if e not in stopwords and len(e) > 1]

        queries = []
        if common:
            # 用公共实体 + "数据" / "最新" 组合
            key_term = common[0] if common else ""
            queries.append(f"{key_term} 最新数据")
            queries.append(f"{key_term} 市场规模")

        # 如果冲突描述中有明确的指标名称，加上
        if conflict.field_name:
            queries.append(f"{conflict.description[:50]}")

        # 去重，最多 3 个搜索词
        return list(dict.fromkeys(queries))[:3]

    async def _execute_searches(
        self, queries: List[str], max_results: int
    ) -> List[Dict]:
        """执行补充搜索。"""
        all_results = []
        for query in queries:
            try:
                results = await self.search_fn(query)
                if isinstance(results, list):
                    all_results.extend(results[:max_results])
            except Exception as e:
                logger.warning(f"[CrossValidator] 搜索失败: {query}, 错误: {e}")
        return all_results[:max_results]

    def _format_search_results(self, results: List[Dict]) -> str:
        """格式化搜索结果为文本。"""
        lines = []
        for i, r in enumerate(results):
            title = r.get("title", r.get("source_name", ""))
            snippet = r.get("snippet", r.get("content", ""))[:200]
            url = r.get("url", r.get("source_url", ""))
            lines.append(f"[{i+1}] {title}\n    {snippet}\n    来源: {url}")
        return "\n".join(lines) if lines else "（无搜索结果）"

    async def _analyze_with_llm(
        self,
        conflict: ConflictPair,
        search_results_text: str,
        raw_results: List[Dict],
    ) -> Dict[str, Any]:
        """调用 LLM 分析验证结果。"""
        user_prompt = self.VERIFICATION_PROMPT.format(
            source_a_name=conflict.fact_a.get("source_name", "?"),
            content_a=conflict.fact_a.get("content", ""),
            source_b_name=conflict.fact_b.get("source_name", "?"),
            content_b=conflict.fact_b.get("content", ""),
            conflict_description=conflict.description,
            search_results=search_results_text,
        )

        try:
            response = await self.llm_call_fn(
                "你是一个事实核查专家，专门分析矛盾信息并判断哪方更可信。",
                user_prompt
            )

            # 解析 JSON
            import json, re
            match = re.search(r'\{[\s\S]*\}', response)
            if match:
                return json.loads(match.group(0))
        except Exception as e:
            logger.warning(f"[CrossValidator] LLM 分析失败: {e}")

        return {
            "status": "inconclusive",
            "evidence_summary": "无法得出结论",
            "verdict": "证据不足，无法判断",
            "confidence": 0.3,
        }

    def _extract_supporting_sources(
        self, verdict: Dict, raw_results: List[Dict]
    ) -> List[str]:
        """从验证结果中提取支持性来源。"""
        sources = []
        for r in raw_results:
            name = r.get("source_name", r.get("title", ""))
            if name:
                sources.append(name)
        return sources[:3]
