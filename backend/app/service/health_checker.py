# Copyright © 2026  版权所有

"""
系统健康检查模块

定期探测 LLM API、搜索 API、Milvus、PostgreSQL 等依赖服务的健康状态。
提供 /health 端点返回整体健康视图。

优化 #2: LLM API 健康检查 + 告警
"""

import os
import time
import asyncio
import logging
import threading
from typing import Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class ServiceHealth:
    """单个服务的健康状态"""
    name: str
    status: str = "unknown"  # healthy / degraded / unhealthy / unknown
    latency_ms: int = 0
    last_check: str = ""
    error: str = ""
    consecutive_failures: int = 0
    total_checks: int = 0
    total_failures: int = 0


class HealthChecker:
    """
    系统健康检查器

    定时探测各依赖服务，维护健康状态。
    """

    def __init__(self, check_interval_sec: int = 60):
        self._interval = check_interval_sec
        self._services: Dict[str, ServiceHealth] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._lock = threading.Lock()

        # 注册默认服务
        self._register_default_services()

    def _register_default_services(self):
        """注册默认要检查的服务"""
        self._services["llm_api"] = ServiceHealth(name="llm_api")
        self._services["search_api"] = ServiceHealth(name="search_api")
        self._services["milvus"] = ServiceHealth(name="milvus")

    def register_service(self, name: str):
        """注册一个新服务"""
        with self._lock:
            if name not in self._services:
                self._services[name] = ServiceHealth(name=name)

    def get_health(self) -> Dict[str, ServiceHealth]:
        """获取所有服务的健康状态"""
        with self._lock:
            return {k: ServiceHealth(**asdict(v)) for k, v in self._services.items()}

    def get_overall_status(self) -> str:
        """获取整体健康状态"""
        with self._lock:
            statuses = [s.status for s in self._services.values()]
            if any(s == "unhealthy" for s in statuses):
                return "unhealthy"
            if any(s == "degraded" for s in statuses):
                return "degraded"
            if all(s == "healthy" for s in statuses):
                return "healthy"
            return "unknown"

    async def _check_llm_api(self) -> ServiceHealth:
        """检查 LLM API 健康状态"""
        health = self._services["llm_api"]
        health.last_check = datetime.now().isoformat()
        health.total_checks += 1

        api_key = os.getenv("DASHSCOPE_API_KEY", "")
        base_url = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        model = os.getenv("DASHSCOPE_MODEL", "qwen-plus")

        if not api_key:
            health.status = "unhealthy"
            health.error = "DASHSCOPE_API_KEY not configured"
            return health

        start = time.time()
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=base_url)

            # 发一个极简请求测试连通性
            resp = await asyncio.to_thread(
                client.chat.completions.create,
                model=model,
                messages=[{"role": "user", "content": "ok"}],
                max_tokens=5,
                temperature=0,
            )

            latency = int((time.time() - start) * 1000)
            health.latency_ms = latency
            health.consecutive_failures = 0

            if latency > 5000:
                health.status = "degraded"
                health.error = f"响应延迟 {latency}ms"
            else:
                health.status = "healthy"
                health.error = ""

        except Exception as e:
            latency = int((time.time() - start) * 1000)
            health.latency_ms = latency
            health.consecutive_failures += 1
            health.total_failures += 1
            health.error = str(e)[:200]

            if health.consecutive_failures >= 3:
                health.status = "unhealthy"
            else:
                health.status = "degraded"

        return health

    async def _check_search_api(self) -> ServiceHealth:
        """检查搜索 API 健康状态"""
        health = self._services["search_api"]
        health.last_check = datetime.now().isoformat()
        health.total_checks += 1

        api_key = os.getenv("BOCHA_AI_API_KEY", "")
        if not api_key:
            health.status = "unhealthy"
            health.error = "BOCHA_AI_API_KEY not configured"
            return health

        start = time.time()
        try:
            import requests
            resp = await asyncio.to_thread(
                requests.post,
                "https://api.bocha.cn/v1/web-search",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"query": "test", "summary": True, "count": 1, "freshness": "noLimit"},
                timeout=10,
            )

            latency = int((time.time() - start) * 1000)
            health.latency_ms = latency

            if resp.status_code == 200:
                health.consecutive_failures = 0
                health.status = "healthy"
                health.error = ""
            else:
                health.consecutive_failures += 1
                health.total_failures += 1
                health.status = "degraded"
                health.error = f"HTTP {resp.status_code}"

        except Exception as e:
            latency = int((time.time() - start) * 1000)
            health.latency_ms = latency
            health.consecutive_failures += 1
            health.total_failures += 1
            health.error = str(e)[:200]

            if health.consecutive_failures >= 3:
                health.status = "unhealthy"
            else:
                health.status = "degraded"

        return health

    async def _check_milvus(self) -> ServiceHealth:
        """检查 Milvus 健康状态"""
        health = self._services["milvus"]
        health.last_check = datetime.now().isoformat()
        health.total_checks += 1

        start = time.time()
        try:
            try:
                from service.milvus_service import get_milvus_service
            except ImportError:
                from app.service.milvus_service import get_milvus_service

            milvus = get_milvus_service()
            if milvus:
                # 尝试连接（has_collection 是个轻量级检查）
                from pymilvus import utility
                utility.has_collection("health_check")
                latency = int((time.time() - start) * 1000)
                health.latency_ms = latency
                health.consecutive_failures = 0
                health.status = "healthy"
                health.error = ""
            else:
                health.status = "unhealthy"
                health.error = "Milvus service not available"

        except ImportError:
            health.status = "unhealthy"
            health.error = "Milvus SDK not installed"
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            health.latency_ms = latency
            health.consecutive_failures += 1
            health.total_failures += 1
            health.error = str(e)[:200]

            if health.consecutive_failures >= 3:
                health.status = "unhealthy"
            else:
                health.status = "degraded"

        return health

    async def check_all(self) -> Dict[str, ServiceHealth]:
        """检查所有服务"""
        checks = [
            self._check_llm_api(),
            self._check_search_api(),
            self._check_milvus(),
        ]

        results = await asyncio.gather(*checks, return_exceptions=True)

        with self._lock:
            for i, result in enumerate(results):
                key = list(self._services.keys())[i]
                if isinstance(result, Exception):
                    self._services[key].status = "unhealthy"
                    self._services[key].error = str(result)[:200]
                else:
                    self._services[key] = result

        return self.get_health()

    async def start(self):
        """启动定时健康检查"""
        if self._running:
            return
        self._running = True
        logger.info(f"Health checker started (interval={self._interval}s)")

        while self._running:
            try:
                await self.check_all()
                overall = self.get_overall_status()
                if overall != "healthy":
                    logger.warning(f"[HealthCheck] Overall status: {overall}")
                else:
                    logger.debug("[HealthCheck] All services healthy")
            except Exception as e:
                logger.error(f"[HealthCheck] Check failed: {e}")

            await asyncio.sleep(self._interval)

    def stop(self):
        """停止健康检查"""
        self._running = False
        logger.info("Health checker stopped")


# 全局单例
_health_checker: Optional[HealthChecker] = None


def get_health_checker(interval_sec: int = 60) -> HealthChecker:
    """获取健康检查器单例"""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker(check_interval_sec=interval_sec)
    return _health_checker
