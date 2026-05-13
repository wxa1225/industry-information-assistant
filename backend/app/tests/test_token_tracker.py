"""Token 追踪器测试"""
import pytest

from service.observability.token_tracker import TokenStats, _TokenRegistry


class TestTokenStats:
    """TokenStats 数据类测试"""

    def test_total_tokens(self):
        """total_tokens = input + output"""
        stats = TokenStats(
            trace_id="t1", agent_name="Scout", model="qwen-plus",
            input_tokens=1000, output_tokens=500, duration_ms=200,
        )
        assert stats.total_tokens() == 1500

    def test_to_dict(self):
        """to_dict 包含所有字段"""
        stats = TokenStats(
            trace_id="t1", agent_name="Scout", model="qwen-plus",
            input_tokens=1000, output_tokens=500, duration_ms=200,
            success=True, prompt_type="research",
        )
        d = stats.to_dict()
        assert d["total_tokens"] == 1500
        assert d["agent_name"] == "Scout"
        assert d["success"] is True
        assert d["prompt_type"] == "research"


class TestTokenRegistry:
    """TokenRegistry 追踪逻辑测试"""

    def setup_method(self):
        self.registry = _TokenRegistry(persist=False)

    def test_record_single_call(self):
        """记录单次调用"""
        stats = TokenStats(
            trace_id="t1", agent_name="Scout", model="qwen-plus",
            input_tokens=1000, output_tokens=500, duration_ms=200,
        )
        self.registry.record(stats)
        results = self.registry.get_stats("t1")
        assert len(results) == 1

    def test_record_multiple_calls_same_trace(self):
        """同一 trace 多次调用"""
        for i in range(3):
            self.registry.record(TokenStats(
                trace_id="t1", agent_name="Scout", model="qwen-plus",
                input_tokens=1000, output_tokens=500, duration_ms=200,
            ))
        results = self.registry.get_stats("t1")
        assert len(results) == 3

    def test_summary_aggregation(self):
        """聚合统计正确"""
        self.registry.record(TokenStats(
            trace_id="t1", agent_name="Scout", model="qwen-plus",
            input_tokens=1000, output_tokens=500, duration_ms=200,
        ))
        self.registry.record(TokenStats(
            trace_id="t1", agent_name="Writer", model="qwen-max",
            input_tokens=2000, output_tokens=1000, duration_ms=500,
        ))
        summary = self.registry.summary("t1")
        assert summary["total_calls"] == 2
        assert summary["total_input_tokens"] == 3000
        assert summary["total_output_tokens"] == 1500
        assert summary["total_duration_ms"] == 700
        assert "Scout" in summary["by_agent"]
        assert "Writer" in summary["by_agent"]

    def test_summary_empty_trace(self):
        """空 trace 的 summary"""
        summary = self.registry.summary("nonexistent")
        assert summary["total_calls"] == 0

    def test_summary_by_model(self):
        """按模型聚合"""
        self.registry.record(TokenStats(
            trace_id="t1", agent_name="Scout", model="qwen-plus",
            input_tokens=1000, output_tokens=500, duration_ms=200,
        ))
        self.registry.record(TokenStats(
            trace_id="t1", agent_name="Critic", model="qwen-max",
            input_tokens=2000, output_tokens=1000, duration_ms=500,
        ))
        summary = self.registry.summary("t1")
        assert "qwen-plus" in summary["by_model"]
        assert "qwen-max" in summary["by_model"]

    def test_success_failure_counting(self):
        """成功/失败计数"""
        self.registry.record(TokenStats(
            trace_id="t1", agent_name="Scout", model="qwen-plus",
            input_tokens=1000, output_tokens=500, duration_ms=200,
            success=True,
        ))
        self.registry.record(TokenStats(
            trace_id="t1", agent_name="Scout", model="qwen-plus",
            input_tokens=0, output_tokens=0, duration_ms=5000,
            success=False, error="timeout",
        ))
        summary = self.registry.summary("t1")
        assert summary["successful_calls"] == 1
        assert summary["failed_calls"] == 1

    def test_get_all(self):
        """获取所有 trace"""
        self.registry.record(TokenStats(
            trace_id="t1", agent_name="Scout", model="qwen-plus",
            input_tokens=100, output_tokens=50, duration_ms=100,
        ))
        self.registry.record(TokenStats(
            trace_id="t2", agent_name="Writer", model="qwen-max",
            input_tokens=200, output_tokens=100, duration_ms=200,
        ))
        all_traces = self.registry.get_all()
        assert "t1" in all_traces
        assert "t2" in all_traces
