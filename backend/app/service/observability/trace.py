# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有

"""
Trace 追踪器

为每次研究生成唯一的 trace_id，记录全链路事件。
支持通过 trace_id 查询一次研究的完整执行轨迹。
"""

import uuid
import json
import os
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime


# 持久化存储目录（项目根目录下的 data/traces）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
_TRACE_STORAGE_DIR = os.path.join(_PROJECT_ROOT, "data", "traces")


def _ensure_storage_dir():
    """确保存储目录存在"""
    os.makedirs(_TRACE_STORAGE_DIR, exist_ok=True)


def _trace_file_path(trace_id: str) -> str:
    """获取 trace 文件路径"""
    safe_id = trace_id.replace("/", "_").replace("\\", "_")
    return os.path.join(_TRACE_STORAGE_DIR, f"{safe_id}.json")


@dataclass
class TraceEvent:
    """Trace 中的单个事件"""
    timestamp: str
    event_type: str       # "phase_start" | "llm_call" | "tool_call" | "error" | "phase_end" | "checkpoint"
    agent: str            # Agent 名称
    summary: str          # 简短摘要
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "agent": self.agent,
            "summary": self.summary,
            "metadata": self.metadata,
        }


@dataclass
class TraceRecord:
    """一次研究的完整 Trace 记录"""
    trace_id: str
    query: str
    session_id: str
    start_time: str
    end_time: Optional[str] = None
    status: str = "running"  # "running" | "completed" | "failed" | "cancelled"
    events: List[TraceEvent] = field(default_factory=list)
    final_report: str = ""
    quality_score: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "trace_id": self.trace_id,
            "query": self.query,
            "session_id": self.session_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "status": self.status,
            "events": [e.to_dict() for e in self.events],
            "event_count": len(self.events),
            "quality_score": self.quality_score,
        }

    def to_summary(self) -> Dict:
        return {
            "trace_id": self.trace_id,
            "query": self.query,
            "session_id": self.session_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "status": self.status,
            "event_count": len(self.events),
            "quality_score": self.quality_score,
        }


class _TraceRegistry:
    """线程安全的 Trace 注册表（支持 JSON 文件持久化）"""

    def __init__(self, persist: bool = True):
        self._lock = threading.Lock()
        self._traces: Dict[str, TraceRecord] = {}
        self._persist = persist
        self._loaded_from_disk = False

        if self._persist:
            _ensure_storage_dir()
            self._load_all_from_disk()

    def _load_all_from_disk(self):
        """从磁盘加载所有已完成的 trace"""
        if self._loaded_from_disk:
            return
        self._loaded_from_disk = True
        if not os.path.exists(_TRACE_STORAGE_DIR):
            return
        for filename in os.listdir(_TRACE_STORAGE_DIR):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(_TRACE_STORAGE_DIR, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                record = TraceRecord(
                    trace_id=data["trace_id"],
                    query=data["query"],
                    session_id=data["session_id"],
                    start_time=data["start_time"],
                    end_time=data.get("end_time"),
                    status=data.get("status", "completed"),
                    events=[TraceEvent(**e) for e in data.get("events", [])],
                    final_report=data.get("final_report", ""),
                    quality_score=data.get("quality_score", 0.0),
                )
                self._traces[record.trace_id] = record
            except Exception:
                pass  # 跳过损坏的文件

    def _persist_record(self, record: TraceRecord):
        """将 trace 写入磁盘"""
        if not self._persist:
            return
        try:
            filepath = _trace_file_path(record.trace_id)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(record.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception:
            pass  # 持久化失败不影响内存操作

    def create(self, trace_id: str, query: str, session_id: str) -> TraceRecord:
        """创建新的 Trace 记录"""
        record = TraceRecord(
            trace_id=trace_id,
            query=query,
            session_id=session_id,
            start_time=datetime.now().isoformat(),
        )
        with self._lock:
            self._traces[trace_id] = record
        return record

    def add_event(self, trace_id: str, event: TraceEvent) -> None:
        """添加事件到 Trace"""
        with self._lock:
            if trace_id in self._traces:
                self._traces[trace_id].events.append(event)

    def complete(self, trace_id: str, status: str = "completed", final_report: str = "", quality_score: float = 0.0) -> None:
        """标记 Trace 完成并持久化到磁盘"""
        with self._lock:
            if trace_id in self._traces:
                self._traces[trace_id].status = status
                self._traces[trace_id].end_time = datetime.now().isoformat()
                self._traces[trace_id].final_report = final_report
                self._traces[trace_id].quality_score = quality_score
                record = self._traces[trace_id]
        # 持久化（在锁外执行，避免阻塞）
        self._persist_record(record)

    def get(self, trace_id: str) -> Optional[TraceRecord]:
        """获取 Trace 记录"""
        with self._lock:
            return self._traces.get(trace_id)

    def get_all(self) -> Dict[str, TraceRecord]:
        """获取所有 Trace 记录"""
        with self._lock:
            return dict(self._traces)

    def get_summaries(self) -> List[Dict]:
        """获取所有 Trace 的摘要列表"""
        with self._lock:
            return [r.to_summary() for r in self._traces.values()]


# 全局单例
_registry = _TraceRegistry()


def generate_trace_id() -> str:
    """生成唯一的 trace_id"""
    return f"trace-{uuid.uuid4().hex[:12]}"


# 为了向后兼容，也暴露为别名
TraceID = generate_trace_id


def create_trace(trace_id: str, query: str, session_id: str) -> TraceRecord:
    """创建新的 Trace 记录"""
    return _registry.create(trace_id, query, session_id)


def add_trace_event(trace_id: str, event_type: str, agent: str, summary: str, metadata: Optional[Dict] = None) -> None:
    """添加事件到 Trace"""
    event = TraceEvent(
        timestamp=datetime.now().isoformat(),
        event_type=event_type,
        agent=agent,
        summary=summary,
        metadata=metadata or {},
    )
    _registry.add_event(trace_id, event)


def complete_trace(trace_id: str, status: str = "completed", final_report: str = "", quality_score: float = 0.0) -> None:
    """标记 Trace 完成"""
    _registry.complete(trace_id, status, final_report, quality_score)


def get_trace(trace_id: str) -> Optional[TraceRecord]:
    """获取 Trace 记录"""
    return _registry.get(trace_id)


def get_all_traces_info() -> List[Dict]:
    """获取所有 Trace 的摘要列表"""
    return _registry.get_summaries()
