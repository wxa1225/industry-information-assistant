"""健康检查器测试"""
import pytest
import os

from service.health_checker import HealthChecker, ServiceHealth


class TestServiceHealth:
    """ServiceHealth 数据类测试"""

    def test_default_values(self):
        """默认值"""
        health = ServiceHealth(name="test")
        assert health.status == "unknown"
        assert health.latency_ms == 0
        assert health.consecutive_failures == 0
        assert health.total_checks == 0


class TestHealthChecker:
    """HealthChecker 逻辑测试"""

    def setup_method(self):
        self.checker = HealthChecker(check_interval_sec=60)

    def test_register_default_services(self):
        """默认注册了三个服务"""
        health = self.checker.get_health()
        assert "llm_api" in health
        assert "search_api" in health
        assert "milvus" in health

    def test_register_new_service(self):
        """注册新服务"""
        self.checker.register_service("redis")
        health = self.checker.get_health()
        assert "redis" in health

    def test_register_duplicate_service(self):
        """重复注册不应覆盖"""
        original = self.checker.get_health()["llm_api"]
        self.checker.register_service("llm_api")
        health = self.checker.get_health()
        # 不应覆盖已有状态
        assert "llm_api" in health

    def test_overall_status_all_healthy(self):
        """全部 healthy 返回 healthy"""
        for svc in self.checker.get_health().values():
            svc.status = "healthy"
        assert self.checker.get_overall_status() == "healthy"

    def test_overall_status_one_degraded(self):
        """一个 degraded 返回 degraded"""
        health = self.checker.get_health()
        for svc in health.values():
            svc.status = "healthy"
        health["llm_api"].status = "degraded"
        assert self.checker.get_overall_status() == "degraded"

    def test_overall_status_one_unhealthy(self):
        """一个 unhealthy 返回 unhealthy"""
        health = self.checker.get_health()
        for svc in health.values():
            svc.status = "healthy"
        health["milvus"].status = "unhealthy"
        assert self.checker.get_overall_status() == "unhealthy"

    def test_overall_status_unknown(self):
        """混合状态返回 unknown"""
        health = self.checker.get_health()
        health["llm_api"].status = "healthy"
        health["search_api"].status = "unknown"
        assert self.checker.get_overall_status() in ("unknown", "degraded")

    def test_llm_api_no_api_key(self):
        """无 API key 时标记为 unhealthy"""
        # 确保没有设置 API key
        import os
        old_key = os.environ.get("DASHSCOPE_API_KEY")
        if "DASHSCOPE_API_KEY" in os.environ:
            del os.environ["DASHSCOPE_API_KEY"]

        import asyncio
        health = asyncio.get_event_loop().run_until_complete(
            self.checker._check_llm_api()
        )
        assert health.status == "unhealthy"
        assert "not configured" in health.error

        # 恢复
        if old_key:
            os.environ["DASHSCOPE_API_KEY"] = old_key

    def test_search_api_no_api_key(self):
        """无 API key 时标记为 unhealthy"""
        import os
        old_key = os.environ.get("BOCHA_AI_API_KEY")
        if "BOCHA_AI_API_KEY" in os.environ:
            del os.environ["BOCHA_AI_API_KEY"]

        import asyncio
        health = asyncio.get_event_loop().run_until_complete(
            self.checker._check_search_api()
        )
        assert health.status == "unhealthy"
        assert "not configured" in health.error

        if old_key:
            os.environ["BOCHA_AI_API_KEY"] = old_key

    def test_total_checks_increments(self):
        """每次检查 total_checks 递增"""
        import asyncio
        loop = asyncio.get_event_loop()

        old_key = os.environ.get("DASHSCOPE_API_KEY")
        if "DASHSCOPE_API_KEY" in os.environ:
            del os.environ["DASHSCOPE_API_KEY"]

        loop.run_until_complete(self.checker._check_llm_api())
        h1 = self.checker.get_health()["llm_api"]
        assert h1.total_checks >= 1

        loop.run_until_complete(self.checker._check_llm_api())
        h2 = self.checker.get_health()["llm_api"]
        assert h2.total_checks > h1.total_checks

        if old_key:
            os.environ["DASHSCOPE_API_KEY"] = old_key

    def test_consecutive_failures_increments(self):
        """连续失败 consecutive_failures 递增"""
        import os
        import asyncio
        loop = asyncio.get_event_loop()

        old_key = os.environ.get("DASHSCOPE_API_KEY")
        if "DASHSCOPE_API_KEY" in os.environ:
            del os.environ["DASHSCOPE_API_KEY"]

        loop.run_until_complete(self.checker._check_llm_api())
        loop.run_until_complete(self.checker._check_llm_api())
        h = self.checker.get_health()["llm_api"]
        assert h.consecutive_failures >= 2

        if old_key:
            os.environ["DASHSCOPE_API_KEY"] = old_key
