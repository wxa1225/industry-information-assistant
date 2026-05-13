# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有

"""
结构化日志中间件

为整个应用提供：
1. JSON 格式日志输出（便于 ELK/Loki 采集）
2. 请求级别 trace_id 自动生成与传播
3. 请求日志自动记录（方法、路径、耗时、状态码）
4. 全局异常捕获与结构化输出
"""

import os
import json
import uuid
import time
import logging
import traceback
from contextvars import ContextVar
from typing import Callable, Optional, List

try:
    from fastapi import FastAPI
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    FastAPI = None  # type: ignore

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


# ============================================================
# trace_id 上下文变量（线程/协程安全）
# ============================================================
_current_trace_id: ContextVar[str] = ContextVar("trace_id", default="")


def get_current_trace_id() -> str:
    """获取当前请求的 trace_id"""
    return _current_trace_id.get()


# ============================================================
# JSON Formatter
# ============================================================
class JsonFormatter(logging.Formatter):
    """
    JSON 格式日志 formatter。

    输出示例：
    {"timestamp": "2026-05-12T10:30:00", "level": "INFO", "logger": "app",
     "message": "请求处理完成", "trace_id": "abc123",
     "extra": {"method": "GET", "path": "/research/stream", "status": 200, "duration_ms": 150}}
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": get_current_trace_id(),
        }

        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": self.formatException(record.exc_info),
            }

        if hasattr(record, "extra"):
            log_entry["extra"] = record.extra

        # 处理传入的 dict 作为 extra
        if hasattr(record, "kwargs"):
            log_entry["extra"] = record.kwargs

        return json.dumps(log_entry, ensure_ascii=False)


# ============================================================
# 请求日志中间件
# ============================================================
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    为每个 HTTP 请求：
    1. 生成/传播 trace_id
    2. 记录请求开始和结束日志
    3. 统计耗时
    """

    def __init__(self, app, exclude_paths: Optional[List[str]] = None):
        super().__init__(app)
        self.exclude_paths = exclude_paths or ["/metrics", "/docs", "/openapi.json", "/favicon.ico"]

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # 跳过静态路径
        if any(request.url.path.startswith(p) for p in self.exclude_paths):
            return await call_next(request)

        # trace_id 传播：优先使用请求头中的 X-Trace-ID，否则生成新的
        trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4())[:12])
        _current_trace_id.set(trace_id)

        start_time = time.time()

        # 请求开始日志
        logger = logging.getLogger("app.request")
        logger.info(
            "请求开始",
            extra={
                "kwargs": {
                    "method": request.method,
                    "path": request.url.path,
                    "trace_id": trace_id,
                }
            },
        )

        # 执行请求
        try:
            response = await call_next(request)
        except Exception:
            # 异常会在全局异常中间件处理，这里记录耗时
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "请求异常",
                extra={
                    "kwargs": {
                        "method": request.method,
                        "path": request.url.path,
                        "trace_id": trace_id,
                        "duration_ms": duration_ms,
                    }
                },
            )
            raise

        duration_ms = int((time.time() - start_time) * 1000)

        # 响应头注入 trace_id（方便前端/网关追踪）
        response.headers["X-Trace-ID"] = trace_id

        # 请求完成日志
        log_level = logging.WARNING if response.status_code >= 400 else logging.INFO
        logger.log(
            log_level,
            "请求完成",
            extra={
                "kwargs": {
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                    "trace_id": trace_id,
                }
            },
        )

        return response


# ============================================================
# 全局异常处理器
# ============================================================
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    全局异常捕获：统一返回 JSON 格式错误，避免暴露内部细节。
    """
    trace_id = get_current_trace_id()
    logger = logging.getLogger("app.exception")

    if isinstance(exc, StarletteHTTPException):
        # HTTP 异常（4xx/5xx）
        logger.warning(
            f"HTTP {exc.status_code}: {exc.detail}",
            extra={"kwargs": {"trace_id": trace_id, "path": request.url.path}},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.detail,
                "status": exc.status_code,
                "trace_id": trace_id,
            },
        )

    # 未捕获的异常
    logger.error(
        f"未捕获异常: {exc}",
        extra={"kwargs": {"trace_id": trace_id, "path": request.url.path}},
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "服务器内部错误",
            "status": 500,
            "trace_id": trace_id,
        },
    )


# ============================================================
# 初始化函数
# ============================================================
def setup_structured_logging(app: FastAPI):
    """
    为 FastAPI 应用配置结构化日志和全局异常处理。
    """

    # 添加中间件
    app.add_middleware(RequestLoggingMiddleware)

    # 注册全局异常处理器
    app.add_exception_handler(Exception, global_exception_handler)
    app.add_exception_handler(StarletteHTTPException, global_exception_handler)

    # 配置根 logger 使用 JSON formatter
    json_handler = logging.StreamHandler()
    json_handler.setFormatter(JsonFormatter())

    root_logger = logging.getLogger()
    # 移除默认 handler，替换为 JSON handler
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    root_logger.addHandler(json_handler)

    # 设置日志级别
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))

    logging.getLogger("app").info("结构化日志中间件已初始化")
