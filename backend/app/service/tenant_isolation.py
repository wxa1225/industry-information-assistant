# Copyright © 2026  版权所有

"""
多租户隔离模块

为研究系统添加用户级数据隔离：
1. 记忆隔离：用户只能检索自己的记忆
2. Trace 隔离：Trace 查询按用户过滤
3. Token 用量按用户统计
4. 成本限制按用户配置

优化 #6: 多租户隔离
"""

import os
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TenantConfig:
    """单个租户（用户）的配置"""
    user_id: str
    max_concurrent: int = 3           # 最大并发研究数
    cost_limit_yuan: float = 5.0      # 单次研究成本上限
    daily_cost_limit_yuan: float = 20.0  # 每日成本上限
    max_researches_per_day: int = 50  # 每日最大研究次数
    memory_enabled: bool = True       # 是否启用跨 session 记忆


class TenantRegistry:
    """
    租户注册表

    管理每个用户的隔离配置和用量统计。
    """

    def __init__(self):
        self._configs: Dict[str, TenantConfig] = {}
        # 用量统计: user_id -> {date -> {key: value}}
        self._usage: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def register_tenant(self, config: TenantConfig):
        """注册一个租户"""
        self._configs[config.user_id] = config
        self._usage[config.user_id] = {}
        logger.info(f"[Tenant] Registered user: {config.user_id}")

    def get_config(self, user_id: str) -> Optional[TenantConfig]:
        """获取租户配置"""
        return self._configs.get(user_id)

    def get_or_create_config(self, user_id: str) -> TenantConfig:
        """获取或创建租户配置（默认配置）"""
        if user_id not in self._configs:
            config = TenantConfig(user_id=user_id)
            self._configs[user_id] = config
            self._usage[user_id] = {}
        return self._configs[user_id]

    def record_usage(self, user_id: str, date: str, tokens: int, cost: float):
        """记录一次研究用量"""
        if user_id not in self._usage:
            self._usage[user_id] = {}
        if date not in self._usage[user_id]:
            self._usage[user_id][date] = {
                "total_tokens": 0,
                "total_cost": 0.0,
                "research_count": 0,
            }
        day_usage = self._usage[user_id][date]
        day_usage["total_tokens"] += tokens
        day_usage["total_cost"] += cost
        day_usage["research_count"] += 1

    def check_daily_limit(self, user_id: str, date: str) -> Optional[str]:
        """
        检查是否超出每日限制

        Returns:
            如果超限，返回拒绝原因；否则返回 None
        """
        config = self.get_or_create_config(user_id)
        day_usage = self._usage.get(user_id, {}).get(date, {})

        if day_usage.get("total_cost", 0) >= config.daily_cost_limit_yuan:
            return f"今日成本已达上限 ¥{config.daily_cost_limit_yuan:.2f}"

        if day_usage.get("research_count", 0) >= config.max_researches_per_day:
            return f"今日研究次数已达上限 {config.max_researches_per_day} 次"

        return None

    def get_usage_summary(self, user_id: str, date: str) -> Dict[str, Any]:
        """获取用户某天的用量摘要"""
        return self._usage.get(user_id, {}).get(date, {
            "total_tokens": 0,
            "total_cost": 0.0,
            "research_count": 0,
        })


def _default_user_id() -> str:
    """获取默认用户 ID"""
    return os.getenv("DEFAULT_USER_ID", "anonymous")


# 全局单例
_tenant_registry = TenantRegistry()


def get_tenant_registry() -> TenantRegistry:
    """获取租户注册表"""
    return _tenant_registry
