# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有

"""
审计日志中间件

记录所有关键操作的审计轨迹：
- 用户登录/注册
- 数据创建/修改/删除
- 权限变更
- 研究操作

输出 JSON 格式日志，便于 SIEM/SOC 采集。
"""

import json
import time
import logging
from typing import Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger("app.audit")


class AuditLogMiddleware(BaseHTTPMiddleware):
    """
    审计日志中间件。

    为所有写操作（POST/PUT/DELETE/PATCH）记录审计轨迹。
    读操作（GET/HEAD/OPTIONS）不记录。
    """

    EXCLUDED_PATHS = {
        "/health", "/health/live", "/health/ready",
        "/docs", "/openapi.json", "/favicon.ico",
        "/metrics", "/hello",
    }

    EXCLUDED_METHODS = {"GET", "HEAD", "OPTIONS"}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # 跳过不需要审计的路径和方法
        if request.method in self.EXCLUDED_METHODS:
            return await call_next(request)

        if any(request.url.path.startswith(p) for p in self.EXCLUDED_PATHS):
            return await call_next(request)

        start_time = time.time()
        response = await call_next(request)
        duration_ms = int((time.time() - start_time) * 1000)

        # 获取用户信息（从 JWT 中提取）
        user_id = self._extract_user_id(request)
        client_ip = self._get_client_ip(request)

        audit_entry = {
            "event": "audit",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "user_id": user_id,
            "client_ip": client_ip,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        }

        # 记录审计日志（JSON 格式，便于 SIEM 采集）
        log_level = logging.WARNING if response.status_code >= 400 else logging.INFO
        logger.log(log_level, json.dumps(audit_entry, ensure_ascii=False))

        return response

    def _extract_user_id(self, request: Request) -> Optional[str]:
        """从 Authorization header 中提取 user_id。

        解码 JWT Token 的 sub 字段作为用户 ID。
        如果解码失败（过期、签名错误等），降级为 "authenticated"。
        """
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return "anonymous"

        try:
            import os
            from jose import jwt
            token = auth_header[7:]  # 去掉 "Bearer "
            # 使用与安全中间件相同的密钥和算法
            secret = os.getenv("JWT_SECRET_KEY", "")
            payload = jwt.decode(token, secret, algorithms=["HS256"])
            user_id = payload.get("sub") or payload.get("user_id")
            return user_id or "authenticated"
        except Exception:
            # Token 解码失败时仍然记录为已认证，但不暴露具体用户
            return "authenticated"

    def _get_client_ip(self, request: Request) -> str:
        """获取客户端真实 IP（支持 X-Forwarded-For）"""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.headers.get("X-Real-IP") or request.client.host if request.client else "unknown"
