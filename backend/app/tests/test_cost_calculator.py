"""成本计算器测试"""
import pytest

from service.observability.cost_calculator import calculate_cost, get_model_tier, format_cost


class TestCostCalculator:
    """成本计算逻辑测试"""

    def test_qwen_plus_cost(self):
        """qwen-plus 成本计算"""
        cost = calculate_cost("qwen-plus", 1000, 500)
        # input: 0.0008, output: 0.0016 (per 1000 tokens)
        expected = 1000/1000 * 0.0008 + 500/1000 * 0.0016
        assert abs(cost - expected) < 1e-6

    def test_qwen_max_cost(self):
        """qwen-max 成本应高于 qwen-plus"""
        cost_turbo = calculate_cost("qwen-turbo", 1000, 1000)
        cost_max = calculate_cost("qwen-max", 1000, 1000)
        assert cost_max > cost_turbo

    def test_cache_hit_cheaper(self):
        """缓存命中应降低成本"""
        cost_no_cache = calculate_cost("qwen-plus", 2000, 500, cache_hit_tokens=0)
        cost_with_cache = calculate_cost("qwen-plus", 2000, 500, cache_hit_tokens=1000)
        assert cost_with_cache < cost_no_cache

    def test_unknown_model_returns_zero(self):
        """未知模型应返回0"""
        cost = calculate_cost("unknown-model-xyz", 1000, 500)
        assert cost == 0.0

    def test_zero_tokens_zero_cost(self):
        """0 token 应0成本"""
        cost = calculate_cost("qwen-plus", 0, 0)
        assert cost == 0.0

    def test_deepseek_v3_cost(self):
        """deepseek-v3 是低成本模型"""
        cost = calculate_cost("deepseek-v3", 1000, 500)
        assert cost < 0.01

    def test_gpt4o_expensive(self):
        """gpt-4o 是昂贵模型"""
        cost = calculate_cost("gpt-4o", 1000, 500)
        assert cost > 0.01  # 比 qwen 贵很多

    def test_cost_rounded(self):
        """成本应被舍入"""
        cost = calculate_cost("qwen-plus", 1234, 567)
        assert len(str(cost).split(".")[-1]) <= 6

    def test_model_tier_classification(self):
        """模型分级正确"""
        assert get_model_tier("qwen-turbo") == "budget"
        assert get_model_tier("qwen-plus") == "standard"
        assert get_model_tier("qwen-max") == "premium"
        assert get_model_tier("gpt-4o") == "premium"
        assert get_model_tier("unknown-xyz") == "unknown"

    def test_format_cost_subcent(self):
        """小于1分的显示为分"""
        s = format_cost(0.005)
        assert "分" in s

    def test_format_cost_yuan(self):
        """大于1分的显示为元"""
        s = format_cost(0.05)
        assert "¥" in s

    def test_large_call_cost(self):
        """大规模调用成本计算"""
        # 10万输入 + 5万输出
        cost = calculate_cost("qwen-max", 100000, 50000)
        expected = 100 * 0.004 + 50 * 0.012
        assert abs(cost - expected) < 0.001
