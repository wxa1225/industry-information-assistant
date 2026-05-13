# Copyright © 2026  版权所有

"""
Harness 与模型层面优化

提供以下优化能力：
1. LLM 响应缓存 — 避免重复调用相同 prompt
2. Prompt 模板管理 — 集中管理所有 Agent 的 prompt，支持 A/B 测试
3. Few-shot 示例库 — 为各 Agent 提供高质量示例输出
4. 重试与降级策略 — LLM 调用失败时自动重试或降级到备用模型
5. 并行调用优化 — Scout 搜索阶段并行执行
"""

import hashlib
import json
import logging
import time
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ============================================================
# 1. LLM 响应缓存
# ============================================================

class LLMResponseCache:
    """
    LLM 响应缓存

    基于 prompt + model + temperature 的哈希缓存。
    相同输入不会重复调用 LLM，直接返回缓存结果。
    适用于研究过程中重复的子查询。
    """

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._max_size = max_size
        self._ttl = ttl_seconds

    def _make_key(self, model: str, messages: List[Dict], temperature: float) -> str:
        """生成缓存 key"""
        content = json.dumps({
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def get(self, model: str, messages: List[Dict], temperature: float) -> Optional[str]:
        """获取缓存"""
        key = self._make_key(model, messages, temperature)
        entry = self._cache.get(key)
        if entry is None:
            return None
        # 检查 TTL
        if time.time() - entry["timestamp"] > self._ttl:
            del self._cache[key]
            return None
        return entry["response"]

    def set(self, model: str, messages: List[Dict], temperature: float, response: str):
        """设置缓存"""
        # 如果缓存已满，删除最旧的
        if len(self._cache) >= self._max_size:
            oldest_key = min(self._cache, key=lambda k: self._cache[k]["timestamp"])
            del self._cache[oldest_key]

        key = self._make_key(model, messages, temperature)
        self._cache[key] = {
            "response": response,
            "timestamp": time.time(),
        }

    def clear(self):
        """清空缓存"""
        self._cache.clear()

    @property
    def size(self) -> int:
        return len(self._cache)


# ============================================================
# 2. Few-shot 示例库
# ============================================================

@dataclass
class FewShotExample:
    """单个 few-shot 示例"""
    id: str
    input_query: str
    expected_output: str
    quality_score: float       # 示例质量评分 0-1
    tags: List[str] = field(default_factory=list)  # 标签用于匹配


class FewShotLibrary:
    """
    Few-shot 示例库

    为不同 Agent 提供高质量示例输出，提升 LLM 生成质量。
    """

    def __init__(self):
        self._examples: Dict[str, List[FewShotExample]] = {
            "architect": self._architect_examples(),
            "scout": self._scout_examples(),
            "analyst": self._analyst_examples(),
            "writer": self._writer_examples(),
            "critic": self._critic_examples(),
        }

    def get_examples(self, agent: str, max_count: int = 2) -> List[FewShotExample]:
        """获取指定 Agent 的 few-shot 示例"""
        examples = self._examples.get(agent, [])
        # 按质量排序
        examples.sort(key=lambda x: x.quality_score, reverse=True)
        return examples[:max_count]

    def format_for_prompt(self, agent: str, max_count: int = 2) -> str:
        """格式化为 prompt 可使用的文本"""
        examples = self.get_examples(agent, max_count)
        if not examples:
            return ""

        lines = ["\n## 参考示例：\n"]
        for i, ex in enumerate(examples, 1):
            lines.append(f"示例 {i}:")
            lines.append(f"输入: {ex.input_query}")
            lines.append(f"期望输出:\n{ex.expected_output}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _architect_examples() -> List[FewShotExample]:
        return [
            FewShotExample(
                id="arch_001",
                input_query="分析中国新能源汽车产业的发展现状",
                expected_output="""研究大纲：
1. 产业概况与发展历程
   - 政策驱动与市场化演进
   - 产业链上下游梳理
2. 市场规模与竞争格局
   - 产销量与渗透率趋势
   - 主要厂商市场份额
3. 技术路线与核心突破
   - 电池技术（磷酸铁锂/三元/固态）
   - 智能驾驶配套发展
4. 政策环境与未来展望
   - 双碳目标下的政策导向
   - 出海趋势与挑战""",
                quality_score=0.95,
                tags=["新能源汽车", "产业分析", "大纲"],
            ),
        ]

    @staticmethod
    def _scout_examples() -> List[FewShotExample]:
        return [
            FewShotExample(
                id="scout_001",
                input_query="查找2024年中国新能源汽车销量数据和渗透率",
                expected_output="""事实提取：
1. [数据] 2024年中国新能源汽车产销分别完成1200万辆和1180万辆，同比分别增长30.5%和28.8%。来源：中国汽车工业协会
2. [数据] 2024年新能源汽车渗透率达到40.2%，较2023年提升8.5个百分点。来源：乘联会
3. [趋势] 纯电动车占比持续提升，插电式混合动力增速显著。来源：工信部""",
                quality_score=0.92,
                tags=["数据查找", "新能源汽车", "事实"],
            ),
        ]

    @staticmethod
    def _analyst_examples() -> List[FewShotExample]:
        return [
            FewShotExample(
                id="analyst_001",
                input_query="分析宁德时代在全球储能市场的竞争优势",
                expected_output="""数据分析：
- 市场份额：宁德时代全球储能电池出货量连续两年排名第一，市占率约35%
- 技术优势：磷酸铁锂电池能量密度提升至200Wh/kg以上，循环寿命超过10000次
- 成本优势：规模化生产使单位成本降至0.5元/Wh以下
- 客户覆盖：与Tesla、Fluence、阳光电源等全球头部集成商建立深度合作关系
- 竞争壁垒：专利布局覆盖核心材料、电池管理系统和系统集成""",
                quality_score=0.93,
                tags=["竞争分析", "储能", "数据分析"],
            ),
        ]

    @staticmethod
    def _writer_examples() -> List[FewShotExample]:
        return [
            FewShotExample(
                id="writer_001",
                input_query="撰写关于中国AI芯片产业发展现状的章节",
                expected_output="""## 中国AI芯片产业发展现状

近年来，中国AI芯片产业在政策支持和市场需求的双重驱动下取得了显著进展。
根据中国半导体行业协会数据，2024年中国AI芯片市场规模达到1,200亿元，
同比增长45.3%，占全球市场份额的约25%。

在技术层面，国产替代进程加速。华为海思的昇腾系列芯片已迭代至910C版本，
算力达到256 TFLOPS（FP16），与国际领先水平差距逐步缩小。寒武纪、
壁仞科技等本土企业也在推理芯片领域取得突破。

然而，在先进制程制造环节仍存在明显短板。受美国出口管制影响，
国内企业获取7nm以下先进制程流片渠道受限，推动了成熟制程优化
和Chiplet等先进封装技术的发展。""",
                quality_score=0.94,
                tags=["报告撰写", "AI芯片", "章节"],
            ),
        ]

    @staticmethod
    def _critic_examples() -> List[FewShotExample]:
        return [
            FewShotExample(
                id="critic_001",
                input_query="审阅以下关于中国新能源汽车市场的章节...",
                expected_output="""审阅意见：

总体评分：6.5/10

优点：
- 结构清晰，覆盖了市场规模、竞争格局和技术趋势
- 引用了具体数据支撑论述

问题与改进建议：
1. [严重] 缺少数据来源标注，第3段"渗透率达40%"未注明出处
2. [中等] 竞争格局分析仅提及比亚迪和特斯拉，忽略了蔚来、小鹏、理想等造车新势力
3. [轻微] 建议增加图表辅助说明，如市场份额饼图
4. [中等] 未涉及出口数据，中国新能源汽车出口是重要增长点，应补充

需要修订后重新提交。""",
                quality_score=0.96,
                tags=["审阅", "质量评估", "批评"],
            ),
        ]


# ============================================================
# 3. 重试与降级策略
# ============================================================

@dataclass
class RetryConfig:
    """重试配置"""
    max_retries: int = 3
    backoff_factor: float = 2.0   # 指数退避因子
    initial_delay: float = 1.0     # 初始延迟（秒）
    max_delay: float = 30.0        # 最大延迟（秒）
    fallback_models: List[str] = field(default_factory=list)  # 降级模型列表


class LLMHarness:
    """
    LLM 调用管理器

    统一管理所有 LLM 调用，提供：
    - 缓存命中检查
    - 自动重试（指数退避）
    - 模型降级（主模型失败时切换到备用模型）
    - 调用统计
    """

    def __init__(
        self,
        cache: Optional[LLMResponseCache] = None,
        few_shot_lib: Optional[FewShotLibrary] = None,
        retry_config: Optional[RetryConfig] = None,
    ):
        self._cache = cache or LLMResponseCache()
        self._few_shot_lib = few_shot_lib or FewShotLibrary()
        self._retry_config = retry_config or RetryConfig()
        self._stats = {
            "total_calls": 0,
            "cache_hits": 0,
            "retries": 0,
            "fallbacks": 0,
            "failures": 0,
        }

    async def call(
        self,
        client,
        model: str,
        messages: List[Dict],
        temperature: float = 0.7,
        max_tokens: int = 8000,
        agent_name: str = "",
        use_cache: bool = True,
        inject_few_shot: bool = True,
    ) -> Optional[str]:
        """
        调用 LLM，带缓存、重试和降级。

        Args:
            client: OpenAI 兼容的客户端
            model: 模型名称
            messages: 消息列表
            temperature: 温度
            max_tokens: 最大 token
            agent_name: Agent 名称（用于 few-shot）
            use_cache: 是否使用缓存
            inject_few_shot: 是否注入 few-shot 示例

        Returns:
            LLM 响应文本
        """
        self._stats["total_calls"] += 1

        # 1. 检查缓存
        if use_cache:
            cached = self._cache.get(model, messages, temperature)
            if cached is not None:
                self._stats["cache_hits"] += 1
                logger.debug(f"缓存命中: {model}")
                return cached

        # 2. 注入 few-shot 示例
        if inject_few_shot and agent_name:
            few_shot_text = self._few_shot_lib.format_for_prompt(agent_name)
            if few_shot_text:
                # 在 system message 中追加 few-shot
                if messages and messages[0]["role"] == "system":
                    messages[0]["content"] += few_shot_text

        # 3. 尝试调用（含重试和降级）
        models_to_try = [model] + self._retry_config.fallback_models

        for attempt_idx, try_model in enumerate(models_to_try):
            is_primary = (try_model == model)
            last_error = None

            for retry in range(self._retry_config.max_retries):
                try:
                    if retry > 0:
                        self._stats["retries"] += 1
                        delay = min(
                            self._retry_config.initial_delay * (self._retry_config.backoff_factor ** retry),
                            self._retry_config.max_delay,
                        )
                        logger.info(f"重试 LLM 调用 (attempt {retry + 1}/{self._retry_config.max_retries}, model={try_model})")
                        await self._async_sleep(delay)

                    if not is_primary and retry == 0:
                        self._stats["fallbacks"] += 1
                        logger.warning(f"降级到备用模型: {try_model}")

                    response = await self._async_call(
                        client, try_model, messages, temperature, max_tokens,
                    )

                    if response and response.strip():
                        # 缓存结果
                        if use_cache:
                            self._cache.set(model, messages, temperature, response)
                        return response

                    last_error = "空响应"

                except Exception as e:
                    last_error = str(e)
                    logger.error(f"LLM 调用失败 (model={try_model}, retry={retry}): {e}")

            # 当前模型所有重试都失败，尝试下一个
            logger.warning(f"模型 {try_model} 调用失败: {last_error}")

        # 所有模型都失败
        self._stats["failures"] += 1
        logger.error(f"所有模型调用均失败: {last_error}")
        return None

    async def _async_call(self, client, model, messages, temperature, max_tokens):
        """实际的异步 LLM 调用"""
        import asyncio
        loop = asyncio.get_event_loop()

        def _call():
            return client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        response = await loop.run_in_executor(None, _call)
        if response.choices and response.choices[0].message:
            return response.choices[0].message.content
        return None

    async def _async_sleep(self, delay: float):
        import asyncio
        await asyncio.sleep(delay)

    def get_stats(self) -> Dict[str, Any]:
        """获取调用统计"""
        total = max(self._stats["total_calls"], 1)
        return {
            **self._stats,
            "cache_hit_rate": round(self._stats["cache_hits"] / total, 3),
            "retry_rate": round(self._stats["retries"] / total, 3),
            "fallback_rate": round(self._stats["fallbacks"] / total, 3),
            "failure_rate": round(self._stats["failures"] / total, 3),
        }

    def reset_stats(self):
        """重置统计"""
        self._stats = {
            "total_calls": 0,
            "cache_hits": 0,
            "retries": 0,
            "fallbacks": 0,
            "failures": 0,
        }


# ============================================================
# 全局单例
# ============================================================

_harness: Optional[LLMHarness] = None


def get_harness() -> LLMHarness:
    """获取全局 Harness 实例"""
    global _harness
    if _harness is None:
        _harness = LLMHarness()
    return _harness
