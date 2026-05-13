# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""
DeepResearch V2.0 - Agent 基类

所有专家Agent的基类，提供通用的LLM调用、日志记录等功能。
"""

import json
import logging
import asyncio
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from openai import OpenAI

from ..state import ResearchState, AgentLog

# 可观测性：token 统计 & trace 追踪
try:
    from service.observability import record_call as _obs_record_call
    from service.observability import add_trace_event as _obs_add_event
except ImportError:
    try:
        from app.service.observability import record_call as _obs_record_call
        from app.service.observability import add_trace_event as _obs_add_event
    except ImportError:
        # fallback：如果 observability 模块不存在，不报错但不记录
        def _obs_record_call(*args, **kwargs):
            pass
        def _obs_add_event(*args, **kwargs):
            pass

# 优化 #3: 成本熔断
try:
    from service.deep_research_v2.service import _get_current_cost, _COST_LIMIT_YUAN, CostLimitExceeded
except ImportError:
    try:
        from app.service.deep_research_v2.service import _get_current_cost, _COST_LIMIT_YUAN, CostLimitExceeded
    except ImportError:
        def _get_current_cost(tid): return 0.0
        _COST_LIMIT_YUAN = 5.0
        class CostLimitExceeded(Exception): pass

# 优化 #3 (增强): Prometheus 指标
_metrics = None
try:
    from service.metrics import get_metrics as _get_metrics_fn
    _metrics = _get_metrics_fn()
except ImportError:
    try:
        from app.service.metrics import get_metrics as _get_metrics_fn
        _metrics = _get_metrics_fn()
    except ImportError:
        _metrics = None

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')


class BaseAgent(ABC):
    """
    Agent 基类

    所有专家Agent继承此类，实现特定的 process 方法。
    """

    # ============================================================
    # 四层上下文设计（Prefix Caching 友好）
    # 按变化频率从低到高排序：system → memory → tools → history → query
    # 面试回答要点：记忆放在 prompt 最前面不是为了注意力，是为了 prefix caching
    # ============================================================
    LAYER_SYSTEM = 0      # 角色定义（几乎不变）
    LAYER_MEMORY = 1      # 长期记忆（更新较慢）
    LAYER_TOOLS = 2       # 工具描述（中等变化）
    LAYER_HISTORY = 3     # 会话历史（每次增加）
    LAYER_QUERY = 4       # 当前查询（每次都变）

    def __init__(
        self,
        name: str,
        role: str,
        llm_api_key: str,
        llm_base_url: str,
        model: str = "qwen-max",
        fallback_model: str = "",  # 降级模型
        max_retries: int = 2,      # 最大重试次数
    ):
        self.name = name
        self.role = role
        self.model = model
        self.fallback_model = fallback_model
        self.max_retries = max_retries
        self.client = OpenAI(api_key=llm_api_key, base_url=llm_base_url)
        self.logger = logging.getLogger(f"Agent.{name}")

    @abstractmethod
    async def process(self, state: ResearchState) -> ResearchState:
        """
        处理状态并返回更新后的状态

        Args:
            state: 当前研究状态

        Returns:
            更新后的状态
        """
        pass

    async def call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        json_mode: bool = True,
        temperature: float = 0.3,
        max_tokens: int = 16000,  # 拉满到最大值
        trace_id: str = "",       # 可观测性：追踪ID
        prompt_type: str = "",    # 可观测性：prompt 类型标识
        context_layers: Optional[List[Dict[str, str]]] = None,  # Prefix Caching: 分层上下文
    ) -> str:
        """
        调用 LLM（带重试 + 降级 + Prefix Caching 优化）

        降级策略：
        1. 重试当前模型（指数退避：1s, 2s, 4s）
        2. 重试失败后降级到 fallback_model
        3. 全部失败后 raise Exception

        Prefix Caching 优化：
        将消息按「变化频率从低到高」排序，最大化前缀缓存命中率：
          layer 0: system_prompt（角色定义，几乎不变）
          layer 1: long-term memory（跨 session 记忆，变化慢）
          layer 2: tool descriptions（技能/工具说明，变化慢）
          layer 3: conversation history / research context（中等变化）
          layer 4: user_prompt（当前查询，每次都变）

        Args:
            system_prompt: 系统提示（角色定义）
            user_prompt: 用户提示（当前查询）
            json_mode: 是否强制JSON输出
            temperature: 温度参数
            max_tokens: 最大token数
            trace_id: 全链路追踪ID（用于可观测性）
            prompt_type: prompt 类型标识（用于统计各类型调用量）
            context_layers: 分层上下文，每层 {"role": "system|user", "content": "...", "layer": 0-4}

        Returns:
            LLM 响应文本
        """
        last_error = None

        # 构建 Prefix Caching 友好的消息列表
        def build_messages() -> List[Dict[str, str]]:
            """按变化频率从低到高组装消息，最大化前缀缓存命中率"""
            layers = []

            # Layer 0: 系统提示（角色定义，最稳定）
            layers.append({"role": "system", "content": system_prompt})

            # Layer 1-3: 分层上下文（如果提供）
            if context_layers:
                # 按 layer 字段排序，确保顺序正确
                sorted_layers = sorted(context_layers, key=lambda x: x.get("layer", 99))
                for layer in sorted_layers:
                    layers.append({
                        "role": layer.get("role", "system"),
                        "content": layer["content"]
                    })

            # Layer 4: 用户提示（当前查询，最易变）
            layers.append({"role": "user", "content": user_prompt})

            return layers

        # 第一轮：尝试当前模型（含重试）
        model_to_try = self.model
        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                wait_time = 2 ** (attempt - 1)  # 指数退避: 1s, 2s
                self.logger.warning(
                    f"LLM call failed, retry {attempt}/{self.max_retries} "
                    f"with model={model_to_try}, waiting {wait_time}s"
                )
                await asyncio.sleep(wait_time)

            start_time = time.time()
            try:
                kwargs = {
                    "model": model_to_try,
                    "messages": build_messages(),
                    "temperature": temperature,
                    "max_tokens": max_tokens
                }

                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}

                response = await asyncio.to_thread(
                    self.client.chat.completions.create,
                    **kwargs
                )

                content = response.choices[0].message.content
                duration = int((time.time() - start_time) * 1000)

                # --- 可观测性：提取 token 用量并记录 ---
                input_tokens = 0
                output_tokens = 0
                if hasattr(response, "usage") and response.usage:
                    input_tokens = getattr(response.usage, "prompt_tokens", 0)
                    output_tokens = getattr(response.usage, "completion_tokens", 0)

                # 记录 token 统计
                if trace_id:
                    _obs_record_call(
                        trace_id=trace_id,
                        agent_name=self.name,
                        model=model_to_try,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        duration_ms=duration,
                        success=True,
                        prompt_type=prompt_type,
                    )
                    _obs_add_event(
                        trace_id=trace_id,
                        event_type="llm_call",
                        agent=self.name,
                        summary=f"LLM 调用完成 ({input_tokens}in/{output_tokens}out, {duration}ms, model={model_to_try})",
                        metadata={
                            "model": model_to_try,
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "duration_ms": duration,
                            "prompt_type": prompt_type,
                            "retries": attempt,
                        },
                    )

                    # --- 优化 #3: 成本熔断检查 ---
                    current_cost = _get_current_cost(trace_id)
                    if current_cost > _COST_LIMIT_YUAN:
                        self.logger.warning(
                            f"[CostCircuit] {self.name} cost ¥{current_cost:.4f} "
                            f"exceeded limit ¥{_COST_LIMIT_YUAN}"
                        )
                        raise CostLimitExceeded(current_cost, _COST_LIMIT_YUAN)

                    # --- 优化 #3 (增强): Prometheus 指标 ---
                    if _metrics:
                        try:
                            _metrics.record_llm_call(
                                duration_sec=duration / 1000.0,
                                input_tokens=input_tokens,
                                output_tokens=output_tokens,
                            )
                        except Exception:
                            pass

                self.logger.info(
                    f"LLM call completed in {duration}ms, "
                    f"response length: {len(content)}, "
                    f"tokens: {input_tokens}in/{output_tokens}out"
                )

                return content

            except Exception as e:
                duration = int((time.time() - start_time) * 1000)
                last_error = e
                self.logger.error(f"LLM call failed (attempt {attempt+1}, model={model_to_try}): {e}")

                # --- 优化 #3 (增强): Prometheus 失败指标 ---
                if _metrics:
                    try:
                        _metrics.record_llm_failure()
                    except Exception:
                        pass

        # 第二轮：降级到 fallback_model
        if self.fallback_model and self.fallback_model != self.model:
            self.logger.warning(
                f"All {self.max_retries + 1} retries failed for {self.model}, "
                f"falling back to {self.fallback_model}"
            )
            start_time = time.time()
            try:
                kwargs = {
                    "model": self.fallback_model,
                    "messages": build_messages(),
                    "temperature": temperature,
                    "max_tokens": max_tokens
                }
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}

                response = await asyncio.to_thread(
                    self.client.chat.completions.create,
                    **kwargs
                )

                content = response.choices[0].message.content
                duration = int((time.time() - start_time) * 1000)

                input_tokens = 0
                output_tokens = 0
                if hasattr(response, "usage") and response.usage:
                    input_tokens = getattr(response.usage, "prompt_tokens", 0)
                    output_tokens = getattr(response.usage, "completion_tokens", 0)

                if trace_id:
                    _obs_record_call(
                        trace_id=trace_id,
                        agent_name=self.name,
                        model=self.fallback_model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        duration_ms=duration,
                        success=True,
                        prompt_type=f"{prompt_type}_fallback",
                    )

                self.logger.info(
                    f"LLM fallback call succeeded: model={self.fallback_model}, "
                    f"duration={duration}ms"
                )
                return content

            except Exception as fallback_error:
                last_error = fallback_error

        # 全部失败
        if trace_id:
            _obs_record_call(
                trace_id=trace_id,
                agent_name=self.name,
                model=model_to_try,
                input_tokens=0,
                output_tokens=0,
                duration_ms=int((time.time() - start_time) * 1000),
                success=False,
                error=str(last_error),
                prompt_type=prompt_type,
            )
        raise last_error if last_error else Exception("LLM call failed after all retries")

    def parse_json_response(self, response: str) -> Dict[str, Any]:
        """安全解析JSON响应，处理markdown代码块和格式问题"""
        import re

        def fix_escaped_newlines(s: str) -> str:
            """修复过度转义的换行符"""
            # 处理多层转义: \\\\n -> \n, \\n -> \n
            s = s.replace('\\\\\\\\n', '\n')
            s = s.replace('\\\\n', '\n')
            # 处理可能的 \\r\\n
            s = s.replace('\\\\\\\\r', '\r')
            s = s.replace('\\\\r', '\r')
            return s

        def try_parse(s: str) -> Optional[Dict]:
            """尝试解析JSON，包含修复逻辑"""
            # 清理常见问题
            s = s.strip()
            # 移除可能的BOM
            if s.startswith('\ufeff'):
                s = s[1:]

            try:
                result = json.loads(s)
                # 成功解析后，修复值中的转义字符
                return self._fix_escaped_values(result)
            except json.JSONDecodeError:
                pass

            # 尝试修复常见JSON问题
            try:
                # 修复无效的JSON转义序列 \[ \] \# 等 (LLM经常产生这种错误)
                # 需要在字符串值中修复，但避免影响已转义的反斜杠
                # \\[ 是有效的(表示 \[ 字面量)，但 \[ 不是有效的JSON转义
                s = re.sub(r'(?<!\\)\\(?!["\\/bfnrtu])', '', s)
                # 移除注释
                s = re.sub(r'//.*?$', '', s, flags=re.MULTILINE)
                s = re.sub(r'/\*.*?\*/', '', s, flags=re.DOTALL)
                # 修复尾随逗号
                s = re.sub(r',(\s*[}\]])', r'\1', s)
                # 修复缺少逗号的情况（在 } 或 ] 后面缺少逗号）
                s = re.sub(r'([}\]])(\s*)([{\[])', r'\1,\2\3', s)
                # 修复没有引号的key
                s = re.sub(r'(\{|\,)\s*(\w+)\s*:', r'\1"\2":', s)
                result = json.loads(s)
                return self._fix_escaped_values(result)
            except json.JSONDecodeError:
                pass

            return None

        # 1. 先尝试直接解析
        result = try_parse(response)
        if result:
            self.logger.debug("Direct JSON parse succeeded")
            return result

        # 2. 尝试提取markdown代码块
        code_block_pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
        match = re.search(code_block_pattern, response)
        if match:
            result = try_parse(match.group(1))
            if result:
                self.logger.debug("Extracted JSON from code block")
                return result

        # 3. 尝试找到最外层的 {...}
        start = response.find('{')
        end = response.rfind('}')
        if start != -1 and end != -1 and end > start:
            result = try_parse(response[start:end+1])
            if result:
                self.logger.debug("Extracted JSON from braces")
                return result

        # 4. 最后尝试用更宽松的方式解析
        try:
            # 使用 ast.literal_eval 作为备选
            import ast
            # 将 true/false/null 转换为 Python 格式
            s = response
            s = re.sub(r'\btrue\b', 'True', s)
            s = re.sub(r'\bfalse\b', 'False', s)
            s = re.sub(r'\bnull\b', 'None', s)
            start = s.find('{')
            end = s.rfind('}')
            if start != -1 and end != -1:
                result = ast.literal_eval(s[start:end+1])
                if isinstance(result, dict):
                    self.logger.debug("Parsed using ast.literal_eval")
                    return result
        except Exception:
            pass

        self.logger.error(f"JSON parse error, could not extract valid JSON")
        self.logger.warning(f"Raw response (first 800 chars): {response[:800]}")
        return {}

    def _fix_escaped_values(self, obj: Any, key: str = None) -> Any:
        """
        递归修复字典和列表中的转义字符

        注意：对于 'code' 字段，不处理转义，因为代码中的 \n 是有意义的转义序列
        """
        if isinstance(obj, dict):
            return {k: self._fix_escaped_values(v, key=k) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._fix_escaped_values(item, key=key) for item in obj]
        elif isinstance(obj, str):
            # 对于代码字段，不进行转义处理
            # 因为代码中的 \n 应该保持为 \n（两个字符），而不是真正的换行
            if key in ('code', 'fixed_code', 'revised_content'):
                return obj

            # 对于其他字段，修复过度转义的换行符
            result = obj
            result = result.replace('\\\\n', '\n')
            result = result.replace('\\n', '\n')
            result = result.replace('\\\\r', '\r')
            result = result.replace('\\r', '\r')
            result = result.replace('\\\\t', '\t')
            result = result.replace('\\t', '\t')
            return result
        else:
            return obj

    def add_message(self, state: ResearchState, event_type: str, content: Any) -> None:
        """
        添加消息到状态（用于SSE流式输出）

        Args:
            state: 研究状态
            event_type: 事件类型
            content: 消息内容
        """
        message = {
            "type": event_type,
            "agent": self.name,
            "timestamp": datetime.now().isoformat(),
            "content": content
        }
        state["messages"].append(message)

        # 如果有消息队列，立即推送（支持实时流式输出）
        if "_message_queue" in state and state["_message_queue"] is not None:
            try:
                state["_message_queue"].put_nowait(message)
                self.logger.info(f"[SSE] Queued event: {event_type} (queue size: {state['_message_queue'].qsize()})")
            except Exception as e:
                self.logger.warning(f"Failed to push message to queue: {e}")
        else:
            self.logger.warning(f"[SSE] No queue available for event: {event_type}")

    def add_log(
        self,
        state: ResearchState,
        action: str,
        input_summary: str,
        output_summary: str,
        duration_ms: int,
        tokens_used: int = 0
    ) -> None:
        """添加执行日志"""
        log = {
            "timestamp": datetime.now().isoformat(),
            "agent": self.name,
            "action": action,
            "input_summary": input_summary,
            "output_summary": output_summary,
            "duration_ms": duration_ms,
            "tokens_used": tokens_used
        }
        state["logs"].append(log)

    def build_context_layers(
        self,
        state: ResearchState,
        tool_description: str = "",
        max_history_messages: int = 10,
    ) -> List[Dict[str, str]]:
        """
        构建 Prefix Caching 友好的四层上下文。

        按变化频率从低到高排序：
        - Layer 1 (memory): 跨 session 长期记忆
        - Layer 2 (tools): 可用工具/技能的精简描述
        - Layer 3 (history): 最近的会话消息摘要

        面试回答要点：
        "我设计了四层上下文：系统层（角色定义）、任务层（研究大纲）、
        用户层（历史记忆）、会话层（当前查询）。
        记忆放在最前面是为了 prefix caching，不是为了注意力。"

        Args:
            state: 研究状态
            tool_description: 工具描述文本（精简版，渐进式披露第一阶段）
            max_history_messages: 最多保留的历史消息数

        Returns:
            分层上下文列表
        """
        layers = []

        # Layer 1: 长期记忆（变化较慢）
        memory_ctx = state.get("memory_context", "")
        if memory_ctx:
            layers.append({
                "role": "system",
                "content": f"[历史记忆]\n{memory_ctx}",
                "layer": self.LAYER_MEMORY,
            })

        # Layer 2: 工具描述（中等变化）
        if tool_description:
            layers.append({
                "role": "system",
                "content": tool_description,
                "layer": self.LAYER_TOOLS,
            })

        # Layer 3: 会话历史（每次增加）
        messages = state.get("messages", [])
        if messages:
            # 只保留最近 N 条，旧的压缩为摘要
            recent = messages[-max_history_messages:]
            history_parts = []
            for msg in recent:
                msg_type = msg.get("type", "")
                content = msg.get("content", "")
                if isinstance(content, dict):
                    content = str(content)
                # 跳过 system_summary 类型的压缩消息
                if msg_type == "system_summary":
                    history_parts.append(f"[压缩历史] {content}")
                else:
                    history_parts.append(f"[{msg_type}] {content[:300]}")
            layers.append({
                "role": "user",
                "content": "[最近研究进展]\n" + "\n".join(history_parts),
                "layer": self.LAYER_HISTORY,
            })

        return layers


class AgentRegistry:
    """Agent 注册表"""

    _agents: Dict[str, BaseAgent] = {}

    @classmethod
    def register(cls, agent: BaseAgent) -> None:
        """注册Agent"""
        cls._agents[agent.name] = agent

    @classmethod
    def get(cls, name: str) -> Optional[BaseAgent]:
        """获取Agent"""
        return cls._agents.get(name)

    @classmethod
    def all(cls) -> Dict[str, BaseAgent]:
        """获取所有Agent"""
        return cls._agents.copy()
