# Copyright © 2026  版权所有
# 未经授权，禁止转售或仿制。

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import logging
import os

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from router import document_router, search_router, chat_router, research_router
from router.auth_router import router as auth_router
from router.session_router import router as session_router
from router.knowledge_router import router as knowledge_router
from router.attachment_router import router as attachment_router
from router.memory_router import router as memory_router
from router.database_router import router as database_router
from router.news_router import router as news_router
from core.database import engine, Base, SessionLocal
# 导入所有模型以确保它们被注册
from models import (
    User, ChatSession, ChatMessage, ChatAttachment, LongTermMemory,
    KnowledgeBase, Document, IndustryStats, CompanyData, PolicyData,
    ResearchCheckpoint, IndustryNews, BiddingInfo, NewsCollectionTask
)

# 数据库表初始化：开发环境使用 create_all，生产环境应使用 Alembic 迁移
# 通过 AUTO_MIGRATE 环境变量控制
AUTO_MIGRATE = os.getenv("AUTO_MIGRATE", "false").lower() == "true"
if AUTO_MIGRATE:
    Base.metadata.create_all(bind=engine)
    logger.info("数据库表已自动创建（开发模式）")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    logger.info("应用启动中...")

    # 初始化定时任务调度器并检查数据
    try:
        from service.scheduler_service import init_scheduler_and_check_data
        await init_scheduler_and_check_data()
        logger.info("定时任务调度器启动成功")
    except Exception as e:
        logger.error(f"定时任务调度器启动失败: {e}")

    yield

    # 关闭时执行
    logger.info("应用关闭中...")
    try:
        from service.scheduler_service import get_scheduler_service
        scheduler = get_scheduler_service()
        scheduler.stop()
    except Exception as e:
        logger.error(f"定时任务调度器关闭失败: {e}")


app = FastAPI(
    title="行业信息助手 API",
    description="基于 AI Agent 的行业信息助手系统",
    version="2.0.0",
    lifespan=lifespan
)

# 添加 CORS 中间件
# 生产环境通过 CORS_ORIGINS 环境变量配置允许的来源，逗号分隔
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8080")
ALLOWED_ORIGINS = [origin.strip() for origin in CORS_ORIGINS.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 添加结构化日志中间件（含全局异常处理）
try:
    from service.logging_middleware import setup_structured_logging
    setup_structured_logging(app)
    logger.info("结构化日志中间件已加载")
except Exception as e:
    logger.warning(f"结构化日志中间件加载失败: {e}")

# 添加审计日志中间件
try:
    from service.audit_middleware import AuditLogMiddleware
    app.add_middleware(AuditLogMiddleware)
    logger.info("审计日志中间件已加载")
except Exception as e:
    logger.warning(f"审计日志中间件加载失败: {e}")

# 注册路由
app.include_router(auth_router)
app.include_router(session_router)
app.include_router(knowledge_router)
app.include_router(attachment_router)
app.include_router(memory_router)
app.include_router(database_router)
app.include_router(document_router)
app.include_router(search_router)
app.include_router(chat_router)
app.include_router(research_router)
app.include_router(news_router)

@app.get("/hello")
async def hello_world():
    """
    Simple hello world endpoint for network verification
    """
    return {
        "status": "success",
        "message": "Hello World! The API is working correctly."
    }


@app.get("/health/live")
async def liveness_probe():
    """
    Kubernetes liveness probe: 应用进程是否存活。
    只要应用能响应此请求，即认为存活。
    """
    return {"status": "ok"}


@app.get("/health/ready")
async def readiness_probe():
    """
    Kubernetes readiness probe: 应用是否准备好接收流量。
    检查关键依赖（数据库、Redis）是否可用。
    """
    checks = {}
    ready = True

    # 数据库检查
    try:
        db = SessionLocal()
        db.execute("SELECT 1")
        db.close()
        checks["database"] = {"status": "ok"}
    except Exception as e:
        checks["database"] = {"status": "error", "error": str(e)}
        ready = False

    # Redis 检查（非阻塞失败，Redis 不可用时仍然允许读请求）
    try:
        from core.redis_client import get_redis_client
        r = get_redis_client()
        r.ping()
        checks["redis"] = {"status": "ok"}
    except Exception as e:
        checks["redis"] = {"status": "degraded", "error": str(e)}
        # Redis 不可用不阻止 readiness，但标记为 degraded

    return {
        "status": "ready" if ready else "not_ready",
        "checks": checks,
    }

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
