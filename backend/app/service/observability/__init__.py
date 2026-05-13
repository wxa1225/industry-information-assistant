# Copyright © 2026  版权所有

"""
可观测性模块 - Token 追踪与成本计算

为每次 LLM 调用记录 token 用量、耗时、模型信息，
并基于 DashScope 定价表估算成本。
"""

from .token_tracker import (
    TokenStats, record_call, get_trace_stats, get_all_traces, get_trace_summary
)
from .cost_calculator import calculate_cost, get_model_tier, MODEL_PRICING, format_cost
from .trace import (
    TraceEvent, TraceRecord, generate_trace_id, create_trace, add_trace_event,
    complete_trace, get_trace, get_all_traces_info,
)

__all__ = [
    "TokenStats", "record_call", "get_trace_stats", "get_all_traces", "get_trace_summary",
    "calculate_cost", "get_model_tier", "MODEL_PRICING", "format_cost",
    "TraceEvent", "TraceRecord", "generate_trace_id", "create_trace", "add_trace_event",
    "complete_trace", "get_trace", "get_all_traces_info",
]
