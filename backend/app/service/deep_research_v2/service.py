# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""
DeepResearch V2.0 - 服务入口

提供与现有路由兼容的接口，支持 SSE 流式输出。
"""

import os
import json
import uuid
import asyncio
import logging
from typing import AsyncGenerator, Dict, Any, Optional
from datetime import datetime

from .graph import DeepResearchGraph

# 导入配置
try:
    from config.llm_config import get_config
except ImportError:
    from app.config.llm_config import get_config

# 优化 #6: 多租户隔离
try:
    from service.tenant_isolation import get_tenant_registry
    TENANT_AVAILABLE = True
except ImportError:
    try:
        from app.service.tenant_isolation import get_tenant_registry
        TENANT_AVAILABLE = True
    except ImportError:
        TENANT_AVAILABLE = False

# 优化 #3 (增强): Prometheus 指标
try:
    from service.metrics import get_metrics
    METRICS_AVAILABLE = True
except ImportError:
    try:
        from app.service.metrics import get_metrics
        METRICS_AVAILABLE = True
    except ImportError:
        METRICS_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("DeepResearchV2Service")


# ============================================================
# 优化 #1: 并发限流 — 全局 Semaphore 控制同时运行的研究数
# ============================================================
_MAX_CONCURRENT_RESEARCH = int(os.getenv("MAX_CONCURRENT_RESEARCH", "3"))
_research_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_RESEARCH)
_queue_stats = {"total_queued": 0, "total_completed": 0, "total_rejected": 0}


# ============================================================
# 优化 #3: 成本熔断 — 单次研究成本上限
# ============================================================
_COST_LIMIT_YUAN = float(os.getenv("RESEARCH_COST_LIMIT_YUAN", "5.0"))


def _get_current_cost(trace_id: str) -> float:
    """获取当前 trace 的累计成本（元）"""
    try:
        from service.observability import calculate_cost, get_trace_stats
        total = 0.0
        for s in get_trace_stats(trace_id):
            total += calculate_cost(s.model, s.input_tokens, s.output_tokens)
        return total
    except Exception:
        return 0.0


class CostLimitExceeded(Exception):
    """成本超限异常"""
    def __init__(self, current_cost: float, limit: float):
        self.current_cost = current_cost
        self.limit = limit
        super().__init__(f"研究成本已达上限: ¥{current_cost:.4f} / ¥{limit:.2f}")


class DeepResearchV2Service:
    """
    DeepResearch V2.0 服务

    特点：
    - 多智能体协作
    - 对抗式质检
    - 代码解释器
    - 流式输出
    """

    def __init__(
        self,
        llm_api_key: Optional[str] = None,
        llm_base_url: Optional[str] = None,
        search_api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_iterations: Optional[int] = None
    ):
        """
        初始化服务

        所有参数都是可选的，会从配置文件读取默认值

        Args:
            llm_api_key: LLM API 密钥（可选，默认从配置读取）
            llm_base_url: LLM API 基础 URL（可选，默认从配置读取）
            search_api_key: 搜索 API 密钥（可选，默认从配置读取）
            model: 默认模型名称（可选，默认从配置读取）
            max_iterations: 最大迭代次数（可选，默认从配置读取）
        """
        # 获取配置
        config = get_config()

        self.llm_api_key = llm_api_key or config.api_key
        self.llm_base_url = llm_base_url or config.base_url
        self.search_api_key = search_api_key or config.search_api_key
        self.model = model or config.default_model
        self.max_iterations = max_iterations or config.research.max_iterations

        # 创建工作流图（使用配置）
        self.graph = DeepResearchGraph(
            llm_api_key=self.llm_api_key,
            llm_base_url=self.llm_base_url,
            search_api_key=self.search_api_key,
            model=self.model,
            max_iterations=self.max_iterations
        )

        logger.info(f"DeepResearch V2 Service initialized with default model: {self.model}")

    async def research(
        self,
        query: str,
        session_id: Optional[str] = None,
        kb_name: Optional[str] = None,
        resume: bool = False,
        user_id: Optional[str] = None,
        search_web: bool = True,
        search_local: bool = False
    ) -> AsyncGenerator[str, None]:
        """
        执行深度研究（SSE 流式输出）

        内置并发限流：超过最大并发数的请求排队等待。
        内置成本熔断：单次研究成本超过上限自动终止。
        多租户隔离：按用户 ID 检查每日限额。
        """
        if not session_id:
            session_id = str(uuid.uuid4())

        # 默认用户 ID
        if not user_id:
            from service.tenant_isolation import _default_user_id
            try:
                user_id = _default_user_id()
            except ImportError:
                from app.service.tenant_isolation import _default_user_id
                user_id = _default_user_id()

        # --- 优化 #6: 多租户限额检查 ---
        if TENANT_AVAILABLE:
            registry = get_tenant_registry()
            config = registry.get_or_create_config(user_id)
            today = datetime.now().strftime("%Y-%m-%d")
            limit_reason = registry.check_daily_limit(user_id, today)
            if limit_reason:
                logger.warning(f"[Tenant] Research rejected for {user_id}: {limit_reason}")
                yield self._format_sse({
                    "type": "error",
                    "content": f"研究限额: {limit_reason}",
                    "user_id": user_id,
                })
                yield "data: [DONE]\n\n"
                return

        if resume:
            logger.info(f"Resuming research for session {session_id}")
        else:
            logger.info(f"Starting research for session {session_id}: {query[:50]}... (user: {user_id})")
            logger.info(f"Search modes - web: {search_web}, local: {search_local}")

        # --- 优化 #3 (增强): 记录研究开始指标 ---
        if METRICS_AVAILABLE:
            try:
                get_metrics().record_research_start()
            except Exception:
                pass

        import time
        research_start_time = time.time()
        research_cost = 0.0
        research_success = False

        # --- 优化 #1: 并发限流 ---
        acquired = False
        try:
            _queue_stats["total_queued"] += 1
            acquired = _research_semaphore.locked() is False
            if acquired:
                _research_semaphore.release()

            await _research_semaphore.acquire()
            _queue_stats["total_completed"] += 1
        except Exception:
            _queue_stats["total_rejected"] += 1
            if METRICS_AVAILABLE:
                try:
                    get_metrics().record_research_failed()
                except Exception:
                    pass
            yield self._format_sse({
                "type": "error",
                "content": "系统繁忙，当前研究任务过多，请稍后重试"
            })
            yield "data: [DONE]\n\n"
            return

        try:
            async for event in self.graph.run(
                query, session_id,
                resume=resume,
                user_id=user_id,
                search_web=search_web,
                search_local=search_local
            ):
                # 转换为 SSE 格式
                yield self._format_sse(event)

                # 研究完成后提取成本
                if event.get("type") == "research_complete":
                    cost_report = event.get("cost_report", {})
                    research_cost = cost_report.get("total_cost", 0)
                    research_success = True

        except CostLimitExceeded as e:
            logger.warning(f"[CostCircuit] {e}")
            yield self._format_sse({
                "type": "cost_limit_exceeded",
                "content": str(e),
                "current_cost": e.current_cost,
                "limit": e.limit,
            })
            if METRICS_AVAILABLE:
                try:
                    get_metrics().record_research_failed()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Research error: {e}")
            yield self._format_sse({
                "type": "error",
                "content": str(e)
            })
            if METRICS_AVAILABLE:
                try:
                    get_metrics().record_research_failed()
                except Exception:
                    pass
        finally:
            _research_semaphore.release()

            # --- 优化 #3 (增强): 记录研究完成指标 ---
            duration = time.time() - research_start_time
            if METRICS_AVAILABLE:
                try:
                    m = get_metrics()
                    if research_success:
                        m.record_research_complete(duration, research_cost)
                    # else: already recorded failed above
                except Exception:
                    pass

            # --- 优化 #6: 记录用量 ---
            if TENANT_AVAILABLE and research_success:
                try:
                    registry = get_tenant_registry()
                    today = datetime.now().strftime("%Y-%m-%d")
                    # 从 cost_report 估算 token 用量
                    registry.record_usage(user_id, today, tokens=0, cost=research_cost)
                except Exception:
                    pass

        # 发送结束标记
        yield "data: [DONE]\n\n"

    def _format_sse(self, event: Dict[str, Any]) -> str:
        """格式化为 SSE 事件"""
        return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    async def research_sync(
        self,
        query: str,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        同步执行研究（返回完整结果）

        Args:
            query: 用户问题
            session_id: 会话ID

        Returns:
            完整的研究结果（含 trace_id 和 cost_report）
        """
        if not session_id:
            session_id = str(uuid.uuid4())

        state = await self.graph.run_sync(query, session_id)

        result = {
            "session_id": session_id,
            "query": query,
            "final_report": state.get("final_report", ""),
            "quality_score": state.get("quality_score", 0.0),
            "outline": state.get("outline", []),
            "facts": state.get("facts", []),
            "data_points": state.get("data_points", []),
            "charts": state.get("charts", []),
            "references": state.get("references", []),
            "insights": state.get("insights", []),
            "iterations": state.get("iteration", 0),
            "phase": state.get("phase", ""),
            "logs": state.get("logs", []),
        }

        # 附加可观测性数据
        trace_id = state.get("trace_id", "")
        if trace_id:
            result["trace_id"] = trace_id
            try:
                from service.observability import get_trace_summary, calculate_cost, get_trace_stats, format_cost
                summary = get_trace_summary(trace_id)
                total_cost = 0.0
                for s in get_trace_stats(trace_id):
                    total_cost += calculate_cost(s.model, s.input_tokens, s.output_tokens)
                result["cost_report"] = {
                    **summary,
                    "total_cost": round(total_cost, 6),
                    "total_cost_formatted": format_cost(total_cost),
                }
            except Exception:
                pass

        return result


def create_service(
    llm_api_key: Optional[str] = None,
    llm_base_url: Optional[str] = None,
    search_api_key: Optional[str] = None,
    model: Optional[str] = None
) -> DeepResearchV2Service:
    """
    工厂函数：创建 DeepResearch V2 服务

    所有参数都是可选的，会从配置文件读取默认值

    Args:
        llm_api_key: LLM API 密钥（可选）
        llm_base_url: LLM API 基础 URL（可选）
        search_api_key: 搜索 API 密钥（可选）
        model: 默认模型名称（可选）

    Returns:
        DeepResearchV2Service 实例
    """
    return DeepResearchV2Service(
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        search_api_key=search_api_key,
        model=model
    )
