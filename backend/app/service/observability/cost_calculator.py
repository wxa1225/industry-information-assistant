# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有

"""
成本计算器

基于 DashScope（阿里云百炼）公开定价，
将 token 用量换算为实际成本（人民币）。

定价来源：https://help.aliyun.com/zh/model-studio/developer-reference/fee
注意：价格可能随时调整，请以官方最新定价为准。
"""

from typing import Dict

# DashScope 模型定价（单位：元 / 1000 tokens）
# 2026-05 参考价格，请根据实际情况更新
MODEL_PRICING: Dict[str, Dict[str, float]] = {
    # deepseek 系列
    "deepseek-v3":    {"input": 0.001,  "output": 0.002,   "cache_hit": 0.0005},
    "deepseek-v3.2":  {"input": 0.001,  "output": 0.002,   "cache_hit": 0.0005},
    "deepseek-r1":    {"input": 0.004,  "output": 0.016,   "cache_hit": 0.002},
    # qwen 系列
    "qwen-turbo":     {"input": 0.0003, "output": 0.0006,  "cache_hit": 0.0001},
    "qwen-plus":      {"input": 0.0008, "output": 0.0016,  "cache_hit": 0.0004},
    "qwen-max":       {"input": 0.004,  "output": 0.012,   "cache_hit": 0.002},
    "qwen-plus-latest": {"input": 0.0008, "output": 0.0016, "cache_hit": 0.0004},
    # 其他
    "gpt-4o":         {"input": 0.025,  "output": 0.075,   "cache_hit": 0.0125},
    "gpt-4o-mini":    {"input": 0.0015, "output": 0.006,   "cache_hit": 0.00075},
    "claude-sonnet-4-6": {"input": 0.021, "output": 0.084, "cache_hit": 0.0105},
}

# 模型分级
_MODEL_TIERS: Dict[str, str] = {
    "deepseek-v3":   "cost-effective",
    "deepseek-v3.2": "cost-effective",
    "deepseek-r1":   "premium",
    "qwen-turbo":    "budget",
    "qwen-plus":     "standard",
    "qwen-plus-latest": "standard",
    "qwen-max":      "premium",
    "gpt-4o":        "premium",
    "gpt-4o-mini":   "standard",
    "claude-sonnet-4-6": "premium",
}


def calculate_cost(model: str, input_tokens: int, output_tokens: int, cache_hit_tokens: int = 0) -> float:
    """
    计算单次 LLM 调用的成本（人民币）。

    计算公式：
        成本 = (input_tokens - cache_hit_tokens) * input_price
             + cache_hit_tokens * cache_hit_price
             + output_tokens * output_price

    Args:
        model: 模型名称
        input_tokens: 输入 token 数
        output_tokens: 输出 token 数
        cache_hit_tokens: 缓存命中的 token 数

    Returns:
        成本（元）
    """
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        # 未知模型，返回 0 并在日志中警告
        return 0.0

    cache_miss_tokens = max(0, input_tokens - cache_hit_tokens)
    cost = (
        cache_miss_tokens / 1000.0 * pricing["input"]
        + cache_hit_tokens / 1000.0 * pricing["cache_hit"]
        + output_tokens / 1000.0 * pricing["output"]
    )
    return round(cost, 6)


def get_model_tier(model: str) -> str:
    """
    获取模型分级。

    Returns:
        "budget" | "standard" | "premium" | "cost-effective" | "unknown"
    """
    return _MODEL_TIERS.get(model, "unknown")


def format_cost(yuan: float) -> str:
    """格式化成本显示"""
    if yuan < 0.01:
        return f"{yuan * 100:.2f}分"
    return f"¥{yuan:.4f}"
