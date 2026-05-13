"""Prometheus 指标导出测试"""
import pytest

from service.metrics import PrometheusMetrics


class TestPrometheusMetrics:
    """Prometheus 指标系统测试"""

    def setup_method(self):
        self.metrics = PrometheusMetrics()

    def test_init_default_metrics(self):
        """初始化后默认指标存在"""
        output = self.metrics.format_prometheus()
        assert "research_total" in output
        assert "research_active" in output
        assert "llm_calls_total" in output
        assert "cost_total_yuan" in output

    def test_increment_counter(self):
        """增加计数器"""
        self.metrics.inc("research_total")
        self.metrics.inc("research_total")
        # 直接检查内部值（Prometheus 格式中 counter 以 _total 结尾）
        assert self.metrics._counters["research_total"] == 2

    def test_increment_with_value(self):
        """带值增加"""
        self.metrics.inc("research_total", 5.0)
        assert self.metrics._counters["research_total"] == 5.0

    def test_set_gauge(self):
        """设置仪表盘"""
        self.metrics.set_gauge("research_active", 3)
        assert self.metrics._gauges["research_active"] == 3
        self.metrics.set_gauge("research_active", 1)
        assert self.metrics._gauges["research_active"] == 1

    def test_observe_histogram(self):
        """观察直方图"""
        self.metrics.observe("test_histogram", 0.5)
        self.metrics.observe("test_histogram", 2.0)
        h = self.metrics._histograms["test_histogram"]
        assert h["count"] == 2
        assert abs(h["sum"] - 2.5) < 1e-6

    def test_research_start_complete(self):
        """研究开始/完成流程"""
        self.metrics.record_research_start()
        assert self.metrics._counters["research_total"] == 1
        assert self.metrics._gauges["research_active"] >= 1

        self.metrics.record_research_complete(duration_sec=30.0, cost_yuan=0.5)
        assert self.metrics._counters["research_success"] == 1
        assert abs(self.metrics._counters["cost_total_yuan"] - 0.5) < 1e-6

    def test_research_failed(self):
        """研究失败"""
        self.metrics.record_research_start()
        self.metrics.record_research_failed()
        assert self.metrics._counters["research_failed"] == 1

    def test_llm_call_recording(self):
        """LLM 调用记录"""
        self.metrics.record_llm_call(
            duration_sec=1.5, input_tokens=1000, output_tokens=500
        )
        assert self.metrics._counters["llm_calls_total"] == 1
        assert self.metrics._counters["llm_tokens_input_total"] == 1000
        assert self.metrics._counters["llm_tokens_output_total"] == 500

    def test_llm_failure(self):
        """LLM 失败记录"""
        self.metrics.record_llm_failure()
        assert self.metrics._counters["llm_calls_failed"] == 1

    def test_health_update(self):
        """健康状态更新"""
        self.metrics.update_health("llm_api", True)
        assert self.metrics._gauges["health_llm_api"] == 1.0
        self.metrics.update_health("llm_api", False)
        assert self.metrics._gauges["health_llm_api"] == 0.0

    def test_prometheus_format_output(self):
        """Prometheus 格式输出包含必要元素"""
        self.metrics.inc("llm_calls_total", 5)
        self.metrics.set_gauge("research_active", 2)
        self.metrics.observe("llm_latency_seconds", 1.0)

        output = self.metrics.format_prometheus()
        assert "# TYPE llm_calls_total counter" in output
        assert "llm_calls_total 5" in output
        assert "# TYPE research_active gauge" in output
        assert "research_active 2" in output
        assert "# EOF" in output

    def test_cost_circuit_triggered(self):
        """成本熔断触发记录"""
        self.metrics.record_cost_circuit_triggered()
        assert self.metrics._counters["cost_circuit_triggered"] >= 1

    def test_gauge_does_not_go_negative(self):
        """仪表盘值不应为负（max(0, ...) 保护）"""
        self.metrics.set_gauge("research_active", 0)
        self.metrics.record_research_complete(duration_sec=1.0)
        assert self.metrics._gauges["research_active"] >= 0

    def test_thread_safety(self):
        """线程安全：并发增加不丢失"""
        import threading

        def inc_many():
            for _ in range(100):
                self.metrics.inc("research_total")

        threads = [threading.Thread(target=inc_many) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert self.metrics._counters["research_total"] == 1000
