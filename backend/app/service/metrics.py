# Copyright © 2026  版权所有

"""
Prometheus 指标导出

暴露系统级指标，供 Prometheus 抓取：
- 研究次数、成功/失败率
- LLM 调用次数、token 用量、延迟
- 成本累计
- 健康检查状态
- 活跃研究数

优化 #3（增强版）：外部监控/告警
"""

import os
import time
import logging
import threading
from typing import Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class PrometheusMetrics:
    """
    简易 Prometheus 指标收集器

    不依赖 prometheus_client 库，手动维护指标计数器。
    通过 /metrics 端点暴露 Prometheus 文本格式。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: Dict[str, float] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, Dict] = {}
        self._init_default_metrics()

    def _init_default_metrics(self):
        """初始化默认指标"""
        self._counters["research_total"] = 0
        self._counters["research_success"] = 0
        self._counters["research_failed"] = 0
        self._counters["research_cancelled"] = 0
        self._counters["llm_calls_total"] = 0
        self._counters["llm_calls_failed"] = 0
        self._counters["llm_tokens_input_total"] = 0
        self._counters["llm_tokens_output_total"] = 0
        self._counters["cost_total_yuan"] = 0.0
        self._counters["cost_circuit_triggered"] = 0
        self._gauges["research_active"] = 0
        self._gauges["health_llm_api"] = 1
        self._gauges["health_search_api"] = 1
        self._gauges["health_milvus"] = 1
        self._histograms["research_duration_seconds"] = {
            "count": 0, "sum": 0.0,
            "buckets": {"0.1": 0, "0.5": 0, "1.0": 0, "2.5": 0, "5.0": 0, "10.0": 0, "30.0": 0, "60.0": 0}
        }
        self._histograms["llm_latency_seconds"] = {
            "count": 0, "sum": 0.0,
            "buckets": {"0.1": 0, "0.5": 0, "1.0": 0, "2.5": 0, "5.0": 0, "10.0": 0, "30.0": 0, "60.0": 0}
        }

    # --- Counter 操作 ---

    def inc(self, name: str, value: float = 1.0):
        """增加计数器"""
        with self._lock:
            if name in self._counters:
                self._counters[name] += value
            else:
                self._counters[name] = value

    # --- Gauge 操作 ---

    def set_gauge(self, name: str, value: float):
        """设置仪表盘值"""
        with self._lock:
            self._gauges[name] = value

    # --- Histogram 操作 ---

    def observe(self, name: str, value: float, buckets=None):
        """观察一个值到直方图"""
        if buckets is None:
            buckets = [0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0]

        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = {
                    "count": 0, "sum": 0.0,
                    "buckets": {str(b): 0 for b in buckets}
                }
            h = self._histograms[name]
            h["count"] += 1
            h["sum"] += value
            for b in buckets:
                if value <= b:
                    h["buckets"][str(b)] += 1

    # --- 业务指标快捷方法 ---

    def record_research_start(self):
        self.inc("research_total")
        self.set_gauge("research_active", self._gauges.get("research_active", 0) + 1)

    def record_research_complete(self, duration_sec: float, cost_yuan: float = 0.0):
        self.inc("research_success")
        self.inc("cost_total_yuan", cost_yuan)
        self.set_gauge("research_active", max(0, self._gauges.get("research_active", 0) - 1))
        self.observe("research_duration_seconds", duration_sec)

    def record_research_failed(self):
        self.inc("research_failed")
        self.set_gauge("research_active", max(0, self._gauges.get("research_active", 0) - 1))

    def record_llm_call(self, duration_sec: float, input_tokens: int = 0, output_tokens: int = 0):
        self.inc("llm_calls_total")
        self.inc("llm_tokens_input_total", input_tokens)
        self.inc("llm_tokens_output_total", output_tokens)
        self.observe("llm_latency_seconds", duration_sec)

    def record_llm_failure(self):
        self.inc("llm_calls_failed")

    def record_cost_circuit_triggered(self):
        self.inc("cost_circuit_triggered")

    def update_health(self, service: str, healthy: bool):
        gauge_name = f"health_{service}"
        self.set_gauge(gauge_name, 1.0 if healthy else 0.0)

    # --- 导出 Prometheus 格式 ---

    def format_prometheus(self) -> str:
        """生成 Prometheus 文本格式"""
        with self._lock:
            lines = []
            lines.append("# HELP industry_assistant_metrics 多源情报交叉验证系统指标")
            lines.append("# TYPE industry_assistant_metrics gauge")
            lines.append("")

            # Counters
            for name, value in sorted(self._counters.items()):
                if "_total" in name:
                    lines.append(f"# HELP {name} Counter")
                    lines.append(f"# TYPE {name} counter")
                    lines.append(f"{name} {value}")
                    lines.append("")

            # Gauges
            for name, value in sorted(self._gauges.items()):
                lines.append(f"# HELP {name} Gauge")
                lines.append(f"# TYPE {name} gauge")
                lines.append(f"{name} {value}")
                lines.append("")

            # Histograms
            for name, h in sorted(self._histograms.items()):
                lines.append(f"# HELP {name} Histogram")
                lines.append(f"# TYPE {name} histogram")
                for bucket, count in sorted(h["buckets"].items()):
                    lines.append(f'{name}_bucket{{le="{bucket}"}} {count}')
                lines.append(f'{name}_bucket{{le="+Inf"}} {h["count"]}')
                lines.append(f"{name}_count {h['count']}")
                lines.append(f"{name}_sum {h['sum']:.3f}")
                lines.append("")

            lines.append("# EOF")
            return "\n".join(lines)


# 全局单例
_metrics = PrometheusMetrics()


def get_metrics() -> PrometheusMetrics:
    return _metrics
