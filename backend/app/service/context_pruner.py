# Copyright © 2026  版权所有

"""
上下文裁剪器 - Context Pruner

在多步研究流程中，中间结果（工具调用返回、临时事实）会不断堆积，
导致 LLM prompt 越来越长，token 消耗线性增长。

本模块在每轮研究循环后自动裁剪冗余上下文，保留核心信息。

面试回答要点：
- 不是简单地截断，而是按信息价值分级保留
- 工具调用结果只保留摘要，不保留完整原始返回
- 事实列表只保留高置信度的，低置信度的中间结论丢弃
- 对话历史只保留最近 N 轮，旧的压缩为摘要
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# 裁剪配置
PRUNE_CONFIG = {
    "max_facts": 30,              # 最多保留的事实数量
    "min_fact_credibility": 0.4,  # 最低事实置信度，低于此值的被裁剪
    "max_tool_results": 5,        # 最多保留的工具调用结果数量
    "max_messages": 20,           # 最多保留的消息数量
    "summarize_old_messages": True,  # 是否将旧消息压缩为摘要
    "keep_recent_messages": 10,   # 保留完整显示的最近消息数量
}


def prune_research_context(state: Dict[str, Any], config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    裁剪研究上下文，防止 token 膨胀。

    在每轮研究循环后调用，清理冗余数据。

    Args:
        state: 研究状态
        config: 可选的裁剪配置（覆盖默认配置）

    Returns:
        裁剪后的状态
    """
    cfg = {**PRUNE_CONFIG, **(config or {})}

    # 1. 裁剪事实列表 — 只保留高置信度的
    facts = state.get("facts", [])
    if len(facts) > cfg["max_facts"]:
        # 按置信度排序，保留最高的
        facts.sort(key=lambda f: f.get("credibility_score", 0), reverse=True)
        pruned_facts = facts[:cfg["max_facts"]]
        removed_count = len(facts) - cfg["max_facts"]
        state["facts"] = pruned_facts
        state["_pruned_facts_count"] = removed_count
        logger.info(f"[ContextPruner] 裁剪了 {removed_count} 条低置信度事实")

    # 进一步过滤低于最低置信度的事实
    state["facts"] = [
        f for f in state.get("facts", [])
        if f.get("credibility_score", 0) >= cfg["min_fact_credibility"]
    ]

    # 2. 裁剪数据点 — 只保留最关键的
    data_points = state.get("data_points", [])
    max_data_points = cfg["max_facts"] * 2  # 数据点可以多一些
    if len(data_points) > max_data_points:
        state["data_points"] = data_points[:max_data_points]
        logger.info(f"[ContextPruner] 裁剪了 {len(data_points) - max_data_points} 个数据点")

    # 3. 裁剪消息列表 — 压缩旧消息
    messages = state.get("messages", [])
    if len(messages) > cfg["max_messages"]:
        keep_count = cfg["keep_recent_messages"]
        old_messages = messages[:-keep_count]
        recent_messages = messages[-keep_count:]

        if cfg["summarize_old_messages"]:
            # 将旧消息压缩为一条摘要
            summary = _summarize_messages(old_messages)
            state["messages"] = [{"type": "system_summary", "content": summary, "compressed": True}] + recent_messages
        else:
            state["messages"] = recent_messages

        logger.info(f"[ContextPruner] 裁剪了 {len(old_messages)} 条旧消息")

    # 4. 清理临时字段（不以 _ 开头的内部状态字段）
    _clean_temporary_fields(state)

    return state


def _summarize_messages(messages: List[Dict]) -> str:
    """将一组旧消息压缩为一条摘要"""
    type_counts = {}
    for msg in messages:
        msg_type = msg.get("type", "unknown")
        type_counts[msg_type] = type_counts.get(msg_type, 0) + 1

    parts = []
    for msg_type, count in type_counts.items():
        parts.append(f"{msg_type}: {count} 条")

    summary = f"[压缩的旧消息] 共 {len(messages)} 条，包括: {', '.join(parts)}。"
    summary += "详细信息已裁剪，仅保留关键结论。"
    return summary


def _clean_temporary_fields(state: Dict[str, Any]) -> None:
    """清理临时状态字段"""
    # 这些字段是 Agent 执行过程中的中间状态，不需要传递给下一轮
    temporary_fields = [
        "_current_tool_result",
        "_current_tool_output",
        "_partial_response",
        "_buffer",
    ]
    for field in temporary_fields:
        if field in state:
            del state[field]


def estimate_context_size(state: Dict[str, Any]) -> Dict[str, int]:
    """
    估算当前上下文的 token 大小（粗略估算）。

    Returns:
        各部分的 token 估算
    """
    facts = state.get("facts", [])
    messages = state.get("messages", [])
    data_points = state.get("data_points", [])
    outline = state.get("outline", [])

    # 粗略估算：每个中文字符 ≈ 1 token，每个英文单词 ≈ 1.3 token
    def estimate_text_tokens(text: str) -> int:
        if not text:
            return 0
        chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
        english_words = len(text.split())
        return chinese_chars + int(english_words * 1.3)

    facts_tokens = sum(
        estimate_text_tokens(f.get("content", ""))
        for f in facts
    )
    messages_tokens = sum(
        estimate_text_chunks(msg.get("content", {}))
        for msg in messages
    )
    data_points_tokens = sum(
        estimate_text_tokens(dp.get("value", ""))
        for dp in data_points
    )
    outline_tokens = estimate_text_tokens(str(outline))

    total = facts_tokens + messages_tokens + data_points_tokens + outline_tokens

    return {
        "facts_tokens": facts_tokens,
        "messages_tokens": messages_tokens,
        "data_points_tokens": data_points_tokens,
        "outline_tokens": outline_tokens,
        "total_tokens": total,
        "facts_count": len(facts),
        "messages_count": len(messages),
        "data_points_count": len(data_points),
    }


def estimate_text_chunks(content: Any) -> int:
    """估算任意内容块的 token 数"""
    if isinstance(content, str):
        return len(content) // 2  # 粗略估算
    elif isinstance(content, dict):
        return len(str(content)) // 2
    elif isinstance(content, list):
        return len(str(content)) // 2
    return 0
