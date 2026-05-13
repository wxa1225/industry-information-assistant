"""多租户隔离测试"""
import pytest

from service.tenant_isolation import TenantConfig, TenantRegistry


class TestTenantConfig:
    """租户配置测试"""

    def test_default_config(self):
        """默认配置值正确"""
        config = TenantConfig(user_id="user1")
        assert config.max_concurrent == 3
        assert config.cost_limit_yuan == 5.0
        assert config.daily_cost_limit_yuan == 20.0
        assert config.max_researches_per_day == 50
        assert config.memory_enabled is True

    def test_custom_config(self):
        """自定义配置"""
        config = TenantConfig(
            user_id="user2",
            max_concurrent=5,
            cost_limit_yuan=10.0,
            daily_cost_limit_yuan=50.0,
        )
        assert config.max_concurrent == 5
        assert config.cost_limit_yuan == 10.0


class TestTenantRegistry:
    """租户注册表测试"""

    def setup_method(self):
        self.registry = TenantRegistry()

    def test_register_tenant(self):
        """注册租户"""
        config = TenantConfig(user_id="user1", max_concurrent=5)
        self.registry.register_tenant(config)
        retrieved = self.registry.get_config("user1")
        assert retrieved is not None
        assert retrieved.max_concurrent == 5

    def test_get_unknown_tenant(self):
        """获取不存在的租户应返回 None"""
        assert self.registry.get_config("unknown") is None

    def test_get_or_create_tenant(self):
        """get_or_create 应创建新租户"""
        config = self.registry.get_or_create_config("new_user")
        assert config is not None
        assert config.user_id == "new_user"
        # 再次获取应返回同一个
        config2 = self.registry.get_or_create_config("new_user")
        assert config2 is config

    def test_record_usage(self):
        """记录用量"""
        self.registry.register_tenant(TenantConfig(user_id="user1"))
        self.registry.record_usage("user1", "2026-05-12", tokens=5000, cost=0.5)
        usage = self.registry.get_usage_summary("user1", "2026-05-12")
        assert usage["total_tokens"] == 5000
        assert usage["total_cost"] == 0.5
        assert usage["research_count"] == 1

    def test_accumulate_usage(self):
        """用量累加"""
        self.registry.register_tenant(TenantConfig(user_id="user1"))
        self.registry.record_usage("user1", "2026-05-12", tokens=1000, cost=0.1)
        self.registry.record_usage("user1", "2026-05-12", tokens=2000, cost=0.2)
        usage = self.registry.get_usage_summary("user1", "2026-05-12")
        assert usage["total_tokens"] == 3000
        assert abs(usage["total_cost"] - 0.3) < 1e-6
        assert usage["research_count"] == 2

    def test_check_daily_limit_not_exceeded(self):
        """未超限应返回 None"""
        self.registry.register_tenant(
            TenantConfig(user_id="user1", daily_cost_limit_yuan=20.0, max_researches_per_day=50)
        )
        self.registry.record_usage("user1", "2026-05-12", tokens=1000, cost=1.0)
        result = self.registry.check_daily_limit("user1", "2026-05-12")
        assert result is None

    def test_check_daily_cost_limit_exceeded(self):
        """成本超限应返回拒绝原因"""
        self.registry.register_tenant(
            TenantConfig(user_id="user1", daily_cost_limit_yuan=2.0)
        )
        self.registry.record_usage("user1", "2026-05-12", tokens=1000, cost=2.5)
        result = self.registry.check_daily_limit("user1", "2026-05-12")
        assert result is not None
        assert "成本已达上限" in result

    def test_check_daily_count_limit_exceeded(self):
        """次数超限应返回拒绝原因"""
        self.registry.register_tenant(
            TenantConfig(user_id="user1", max_researches_per_day=2)
        )
        self.registry.record_usage("user1", "2026-05-12", tokens=100, cost=0.01)
        self.registry.record_usage("user1", "2026-05-12", tokens=100, cost=0.01)
        result = self.registry.check_daily_limit("user1", "2026-05-12")
        assert result is not None
        assert "次数已达上限" in result

    def test_different_days_independent(self):
        """不同天的用量独立"""
        self.registry.register_tenant(TenantConfig(user_id="user1"))
        self.registry.record_usage("user1", "2026-05-12", tokens=5000, cost=5.0)
        usage_day1 = self.registry.get_usage_summary("user1", "2026-05-12")
        usage_day2 = self.registry.get_usage_summary("user1", "2026-05-13")
        assert usage_day1["total_cost"] == 5.0
        assert usage_day2["total_cost"] == 0.0

    def test_tenant_isolation(self):
        """不同租户的用量隔离"""
        self.registry.register_tenant(TenantConfig(user_id="userA"))
        self.registry.register_tenant(TenantConfig(user_id="userB"))
        self.registry.record_usage("userA", "2026-05-12", tokens=5000, cost=3.0)
        self.registry.record_usage("userB", "2026-05-12", tokens=2000, cost=1.0)
        usage_a = self.registry.get_usage_summary("userA", "2026-05-12")
        usage_b = self.registry.get_usage_summary("userB", "2026-05-12")
        assert usage_a["total_cost"] == 3.0
        assert usage_b["total_cost"] == 1.0
