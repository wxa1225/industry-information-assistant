# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有

"""
LLM-as-a-Judge 评估器

对无法用规则计算的维度使用 LLM 进行评估：
- 逻辑连贯性
- 论点支撑度
- 专业深度
- 可读性

使用 rubric-based 评估，避免长度偏见和位置偏见。
"""

import json
import re
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class JudgeResult:
    """LLM 评估结果"""
    dimension: str
    score: float              # 1-5 分
    reasoning: str            # 评分理由
    strengths: List[str]      # 优点
    weaknesses: List[str]     # 不足

    def to_dict(self) -> Dict:
        return {
            "dimension": self.dimension,
            "score": self.score,
            "reasoning": self.reasoning,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
        }


class LLMJudge:
    """
    LLM-as-a-Judge 评估器

    使用 rubric-based 评分，对报告的多个质量维度进行评估。
    """

    # 各维度的评分 rubric
    RUBRICS = {
        "logical_coherence": """评估报告的逻辑连贯性。

评分标准：
5分：论点之间逻辑清晰，论证链条完整，无逻辑跳跃或矛盾
4分：主要论点逻辑清晰，个别地方有轻微跳跃
3分：基本逻辑成立，但部分论证不够充分
2分：存在明显的逻辑漏洞或矛盾
1分：逻辑混乱，论点之间缺乏关联

## 待评估内容
{report_excerpt}""",

        "argument_support": """评估报告的论点是否有充分的论据支撑。

评分标准：
5分：每个重要论点都有数据和来源支撑，论据充分
4分：主要论点有支撑，个别论点论据稍弱
3分：部分论点缺乏足够论据
2分：多数论点缺乏支撑
1分：论点基本无支撑，像主观臆断

## 待评估内容
{report_excerpt}

## 引用的事实
{facts_summary}""",

        "professional_depth": """评估报告的专业深度。

评分标准：
5分：包含行业深层洞察，非表面描述，有独到分析
4分：有一定的专业深度，超出常识
3分：停留在表面描述，缺乏深入分析
2分：内容浅显，缺乏专业性
1分：内容空洞，无实质内容

## 待评估内容
{report_excerpt}

## 数据洞察
{insights_summary}""",

        "readability": """评估报告的可读性。

评分标准：
5分：结构清晰，语言流畅，专业术语使用恰当
4分：整体可读，偶有表述不佳
3分：结构尚可，语言有些生硬
2分：结构混乱，阅读困难
1分：难以阅读，语言混乱

## 待评估内容
{report_excerpt}""",
    }

    def __init__(self, llm_call_fn):
        """
        Args:
            llm_call_fn: 异步 LLM 调用函数
        """
        self.llm_call_fn = llm_call_fn

    async def evaluate(
        self,
        report: str,
        facts: List[Dict] = None,
        insights: List[str] = None,
        dimensions: List[str] = None,
    ) -> List[JudgeResult]:
        """
        对报告进行多维度评估。

        Args:
            report: 报告全文
            facts: 引用的事实列表
            insights: 数据洞察列表
            dimensions: 要评估的维度（默认评估全部）

        Returns:
            各维度的评估结果
        """
        dims = dimensions or list(self.RUBRICS.keys())
        results = []

        # 取报告前 5000 字作为评估样本
        report_excerpt = report[:5000] if report else "（无内容）"

        # 事实摘要
        facts_summary = ""
        if facts:
            fact_lines = []
            for f in facts[:10]:
                fact_lines.append(
                    f"- [{f.get('source_name', '?')}] {f.get('content', '')[:100]}"
                )
            facts_summary = "\n".join(fact_lines)

        # 洞察摘要
        insights_summary = ""
        if insights:
            insights_summary = "\n".join(f"- {ins}" for ins in insights[:5])

        for dim in dims:
            rubric = self.RUBRICS.get(dim)
            if not rubric:
                continue

            user_prompt = rubric.format(
                report_excerpt=report_excerpt,
                facts_summary=facts_summary or "（无引用事实）",
                insights_summary=insights_summary or "（无数据洞察）",
            )

            try:
                response = await self.llm_call_fn(
                    "你是一位专业的行业研究报告评审专家。请根据评分标准对报告进行客观评估。",
                    user_prompt,
                )
                result = self._parse_judge_response(response, dim)
                results.append(result)
            except Exception as e:
                logger.warning(f"[LLMJudge] 维度 {dim} 评估失败: {e}")
                results.append(JudgeResult(
                    dimension=dim, score=0.0,
                    reasoning=f"评估失败: {e}",
                    strengths=[], weaknesses=[],
                ))

        return results

    def _parse_judge_response(self, response: str, dimension: str) -> JudgeResult:
        """解析 LLM 的评估响应"""
        # 尝试解析 JSON
        match = re.search(r'\{[\s\S]*\}', response)
        if match:
            try:
                data = json.loads(match.group(0))
                return JudgeResult(
                    dimension=dimension,
                    score=float(data.get("score", 0)),
                    reasoning=data.get("reasoning", ""),
                    strengths=data.get("strengths", []),
                    weaknesses=data.get("weaknesses", []),
                )
            except json.JSONDecodeError:
                pass

        # 解析失败时，用规则方式估算
        # 从文本中提取分数
        score_match = re.search(r'([1-5])\s*分', response)
        score = float(score_match.group(1)) if score_match else 2.5

        return JudgeResult(
            dimension=dimension,
            score=score,
            reasoning=response[:500],
            strengths=[],
            weaknesses=[],
        )

    def to_normalized_score(self, results: List[JudgeResult]) -> float:
        """将 LLM 打分（1-5）归一化到 0-1"""
        if not results:
            return 0.0
        avg = sum(r.score for r in results) / len(results)
        return avg / 5.0
