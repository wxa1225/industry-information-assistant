# Copyright © 2026  版权所有

"""
Token 用量追踪器

以 trace_id 为维度，记录每次 LLM 调用的 token 消耗。
提供聚合查询能力，支持按 trace / agent / model 维度统计。
"""

import os
import json
import threading
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from datetime import datetime


# 持久化存储目录（项目根目录下的 data/traces）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
_TOKEN_STORAGE_DIR = os.path.join(_PROJECT_ROOT, "data", "traces")


def _ensure_storage_dir():
    """确保存储目录存在"""
    os.makedirs(_TOKEN_STORAGE_DIR, exist_ok=True)


def _token_file_path(trace_id: str) -> str:
    """获取 token 统计文件路径"""
    safe_id = trace_id.replace("/", "_").replace("\\", "_")
    return os.path.join(_TOKEN_STORAGE_DIR, f"{safe_id}_tokens.json")


@dataclass
class TokenStats:
    """单次 LLM 调用的 token 统计"""
    trace_id: str
    agent_name: str
    model: str
    input_tokens: int
    output_tokens: int
    duration_ms: int
    success: bool = True
    error: str = ""
    timestamp: str = ""
    prompt_type: str = ""  # 用于标识这次调用是什么类型的 prompt

    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> Dict:
        return {
            "trace_id": self.trace_id,
            "agent_name": self.agent_name,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens(),
            "duration_ms": self.duration_ms,
            "success": self.success,
            "error": self.error,
            "timestamp": self.timestamp,
            "prompt_type": self.prompt_type,
        }


class _TokenRegistry:
    """线程安全的 Token 统计注册表（支持 JSON 文件持久化）"""

    def __init__(self, persist: bool = True):
        self._lock = threading.Lock()
        # trace_id -> [TokenStats, ...]
        self._traces: Dict[str, List[TokenStats]] = {}
        self._persist = persist
        self._loaded_from_disk = False

        if self._persist:
            _ensure_storage_dir()
            self._load_all_from_disk()

    def _load_all_from_disk(self):
        """从磁盘加载所有 token 统计"""
        if self._loaded_from_disk:
            return
        self._loaded_from_disk = True
        if not os.path.exists(_TOKEN_STORAGE_DIR):
            return
        for filename in os.listdir(_TOKEN_STORAGE_DIR):
            if not filename.endswith("_tokens.json"):
                continue
            filepath = os.path.join(_TOKEN_STORAGE_DIR, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    stats_list = json.load(f)
                trace_id = filename.replace("_tokens.json", "")
                self._traces[trace_id] = [TokenStats(**s) for s in stats_list]
            except Exception:
                pass

    def _persist_trace(self, trace_id: str):
        """将 token 统计写入磁盘"""
        if not self._persist:
            return
        try:
            filepath = _token_file_path(trace_id)
            with self._lock:
                stats_list = [s.to_dict() for s in self._traces.get(trace_id, [])]
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(stats_list, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def record(self, stats: TokenStats) -> None:
        """记录一次 LLM 调用的 token 统计"""
        if not stats.timestamp:
            stats.timestamp = datetime.now().isoformat()
        with self._lock:
            if stats.trace_id not in self._traces:
                self._traces[stats.trace_id] = []
            self._traces[stats.trace_id].append(stats)
        # 持久化（在锁外执行）
        self._persist_trace(stats.trace_id)

    def get_stats(self, trace_id: str) -> List[TokenStats]:
        """获取指定 trace 的所有 token 统计"""
        with self._lock:
            return list(self._traces.get(trace_id, []))

    def get_all(self) -> Dict[str, List[TokenStats]]:
        """获取所有 trace 的 token 统计"""
        with self._lock:
            return {k: list(v) for k, v in self._traces.items()}

    def summary(self, trace_id: str) -> Dict:
        """获取指定 trace 的聚合统计摘要"""
        stats_list = self.get_stats(trace_id)
        if not stats_list:
            return {
                "trace_id": trace_id,
                "total_calls": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_tokens": 0,
                "avg_duration_ms": 0,
                "total_duration_ms": 0,
                "successful_calls": 0,
                "failed_calls": 0,
                "by_agent": {},
                "by_model": {},
            }

        total_input = sum(s.input_tokens for s in stats_list)
        total_output = sum(s.output_tokens for s in stats_list)
        total_duration = sum(s.duration_ms for s in stats_list)
        successful = sum(1 for s in stats_list if s.success)
        failed = len(stats_list) - successful

        # 按 agent 聚合
        by_agent: Dict[str, Dict] = {}
        for s in stats_list:
            if s.agent_name not in by_agent:
                by_agent[s.agent_name] = {
                    "calls": 0, "input_tokens": 0, "output_tokens": 0,
                    "total_tokens": 0, "duration_ms": 0,
                }
            by_agent[s.agent_name]["calls"] += 1
            by_agent[s.agent_name]["input_tokens"] += s.input_tokens
            by_agent[s.agent_name]["output_tokens"] += s.output_tokens
            by_agent[s.agent_name]["total_tokens"] += s.total_tokens()
            by_agent[s.agent_name]["duration_ms"] += s.duration_ms

        # 按 model 聚合
        by_model: Dict[str, Dict] = {}
        for s in stats_list:
            if s.model not in by_model:
                by_model[s.model] = {
                    "calls": 0, "input_tokens": 0, "output_tokens": 0,
                    "total_tokens": 0, "duration_ms": 0,
                }
            by_model[s.model]["calls"] += 1
            by_model[s.model]["input_tokens"] += s.input_tokens
            by_model[s.model]["output_tokens"] += s.output_tokens
            by_model[s.model]["total_tokens"] += s.total_tokens()
            by_model[s.model]["duration_ms"] += s.duration_ms

        return {
            "trace_id": trace_id,
            "total_calls": len(stats_list),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "avg_duration_ms": total_duration // max(len(stats_list), 1),
            "total_duration_ms": total_duration,
            "successful_calls": successful,
            "failed_calls": failed,
            "by_agent": by_agent,
            "by_model": by_model,
        }


# 全局单例
_registry = _TokenRegistry()


def record_call(
    trace_id: str,
    agent_name: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    duration_ms: int,
    success: bool = True,
    error: str = "",
    prompt_type: str = "",
) -> TokenStats:
    """
    记录一次 LLM 调用的 token 统计。

    Args:
        trace_id: 研究追踪 ID
        agent_name: Agent 名称（如 "DeepScout"）
        model: 使用的模型名称
        input_tokens: 输入 token 数
        output_tokens: 输出 token 数
        duration_ms: 耗时（毫秒）
        success: 是否成功
        error: 错误信息（如果失败）
        prompt_type: prompt 类型标识

    Returns:
        TokenStats 实例
    """
    stats = TokenStats(
        trace_id=trace_id,
        agent_name=agent_name,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=duration_ms,
        success=success,
        error=error,
        prompt_type=prompt_type,
    )
    _registry.record(stats)
    return stats


def get_trace_stats(trace_id: str) -> List[TokenStats]:
    """获取指定 trace 的所有 token 统计"""
    return _registry.get_stats(trace_id)


def get_all_traces() -> Dict[str, List[TokenStats]]:
    """获取所有 trace 的 token 统计"""
    return _registry.get_all()


def get_trace_summary(trace_id: str) -> Dict:
    """获取指定 trace 的聚合统计摘要"""
    return _registry.summary(trace_id)
