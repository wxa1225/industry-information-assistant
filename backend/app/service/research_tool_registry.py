# Copyright © 2026  版权所有

"""
研究工具注册表 - Research Tool Registry

为 V2 DeepScout 提供动态工具感知与选择能力：
1. 将搜索/检索方法注册为统一格式的工具
2. LLM 根据章节类型和上下文动态选择工具组合
3. 避免"为了技术而堆技术"——每个工具都有明确的业务场景

解决面试问题："底层是如何动态感知并加载可用 skills 的？"
"""

import logging
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ResearchTool:
    """研究工具定义"""
    name: str                     # 工具唯一名称
    display_name: str             # 展示名称
    description: str              # 工具描述
    when_to_use: str              # 何时使用（给 LLM 的提示）
    cost_level: str = "low"       # 成本等级: low/medium/high
    enabled: bool = True          # 是否启用


class ResearchToolRegistry:
    """
    研究工具注册表

    管理所有可用的研究工具，支持：
    1. 注册/注销工具
    2. 生成工具列表供 LLM 选择
    3. 根据 LLM 的选择执行对应工具
    """

    # 工具选择提示词模板
    TOOL_SELECTION_PROMPT = """你是一个研究工具选择器。根据以下研究任务，从可用工具中选择最合适的工具组合。

## 研究任务
章节标题: {section_title}
章节描述: {section_description}
章节类型: {section_type}
研究问题: {query}

## 可用工具
{tool_descriptions}

## 输出格式
```json
{{
    "selected_tools": ["tool_name_1", "tool_name_2"],
    "reason": "选择这些工具的原因"
}}
```

注意：
1. 选择 1-3 个最适合的工具
2. 不要选择未启用的工具
3. 如果只需要一个工具就足够，不要选多个"""

    def __init__(self):
        self._tools: Dict[str, ResearchTool] = {}
        self._handlers: Dict[str, Callable] = {}

    def register(
        self,
        name: str,
        display_name: str,
        description: str,
        when_to_use: str,
        handler: Optional[Callable] = None,
        cost_level: str = "low",
    ) -> None:
        """注册一个研究工具"""
        tool = ResearchTool(
            name=name,
            display_name=display_name,
            description=description,
            when_to_use=when_to_use,
            cost_level=cost_level,
        )
        self._tools[name] = tool
        if handler:
            self._handlers[name] = handler
        logger.debug(f"Research tool registered: {name}")

    def unregister(self, name: str) -> None:
        """注销一个研究工具"""
        self._tools.pop(name, None)
        self._handlers.pop(name, None)

    def get_tool(self, name: str) -> Optional[ResearchTool]:
        """获取指定工具"""
        return self._tools.get(name)

    def get_handler(self, name: str) -> Optional[Callable]:
        """获取指定工具的执行函数"""
        return self._handlers.get(name)

    def get_enabled_tools(self) -> List[ResearchTool]:
        """获取所有已启用的工具"""
        return [t for t in self._tools.values() if t.enabled]

    def get_tool_descriptions(self) -> str:
        """生成工具描述文本（给 LLM 看）—— 完整版"""
        lines = []
        for tool in self.get_enabled_tools():
            lines.append(
                f"- {tool.name}: {tool.description}\n"
                f"  适用场景: {tool.when_to_use}\n"
                f"  成本: {tool.cost_level}"
            )
        return "\n".join(lines)

    def get_tool_metadata_light(self, max_tools: int = 5) -> str:
        """
        渐进式披露第一阶段：只获取工具的精简元数据。

        用于放入 LLM prompt 的工具描述区，大幅减少 token 消耗。
        相比全量描述，token 消耗减少约 50-60%。

        面试回答要点：
        "Skills/工具用了渐进式披露——第一层只加载 name + description 的元数据，
        模型命中后才加载完整的 when_to_use 和使用指南，避免上下文爆炸。"
        """
        enabled = [t for t in self._tools.values() if t.enabled][:max_tools]
        lines = ["可用研究工具（精简描述）："]
        for tool in enabled:
            lines.append(f"  - {tool.display_name}({tool.name}): {tool.description[:60]} [成本:{tool.cost_level}]")
        return "\n".join(lines)

    def get_tool_descriptions_full(self, tool_names: List[str]) -> str:
        """
        渐进式披露第二阶段：指定工具命中后，加载完整说明。

        当工具被选中执行时，才加载完整的 when_to_use 和使用指南。
        """
        lines = []
        for name in tool_names:
            tool = self._tools.get(name)
            if tool:
                lines.append(f"## {tool.display_name} ({tool.name})")
                lines.append(f"描述: {tool.description}")
                lines.append(f"适用场景: {tool.when_to_use}")
                lines.append(f"成本等级: {tool.cost_level}")
                lines.append("")
        return "\n".join(lines)

    def to_selection_prompt(
        self,
        section_title: str,
        section_description: str,
        section_type: str,
        query: str,
    ) -> str:
        """生成完整的工具选择 prompt"""
        return self.TOOL_SELECTION_PROMPT.format(
            section_title=section_title,
            section_description=section_description,
            section_type=section_type,
            query=query,
            tool_descriptions=self.get_tool_descriptions(),
        )


def create_default_registry() -> ResearchToolRegistry:
    """
    创建默认的工具注册表

    默认注册以下工具：
    1. web_search - 全网搜索（Bocha API）
    2. local_knowledge - 本地知识库搜索（Milvus 向量检索）
    3. source_tracing - 信源追溯（查找原始数据来源）
    4. deep_read - 深度阅读（进入网页读取完整内容）
    5. stock_query - 股票行情查询（上市公司实时数据）
    """
    registry = ResearchToolRegistry()

    registry.register(
        name="web_search",
        display_name="全网搜索",
        description="通过搜索引擎 API 获取互联网上的公开信息",
        when_to_use="通用场景，获取行业概况、市场数据、新闻报道等",
        cost_level="low",
    )

    registry.register(
        name="local_knowledge",
        display_name="本地知识库",
        description="从本地存储的行业文档中检索相关知识",
        when_to_use="需要查找已有行业报告、论文、文档中的信息",
        cost_level="low",
    )

    registry.register(
        name="source_tracing",
        display_name="信源追溯",
        description="当发现文章引用了其他数据源时，追溯原始来源",
        when_to_use="发现'据XX统计'、'XX报告显示'等引用时",
        cost_level="medium",
    )

    registry.register(
        name="deep_read",
        display_name="深度阅读",
        description="进入目标网页，读取完整正文内容",
        when_to_use="搜索摘要显示有高价值信息，需要获取完整内容时",
        cost_level="medium",
    )

    registry.register(
        name="stock_query",
        display_name="股票行情",
        description="查询上市公司实时股票行情数据",
        when_to_use="研究问题涉及特定上市公司，需要了解其股票表现",
        cost_level="low",
    )

    # 7.1 工具设计"宽口径"：一个宽泛的 data_query 工具替代多个窄工具
    # 面试回答要点：
    # "工具设计采用宽口径原则——不是为每种数据源都建一个工具（stock_query, bond_query,
    # fund_query...），而是用一个统一的 data_query 工具，通过参数适配多种数据源。
    # 这样 LLM 不需要记住几十个细粒度工具，降低了 prompt 复杂度和维护成本。"
    registry.register(
        name="data_query",
        display_name="财经数据查询",
        description="统一查询财经市场数据（股票、基金、债券、指数、财务指标等）",
        when_to_use="需要查询任何财经数据时使用，包括：股价、财报、行业数据、宏观经济指标、基金净值、债券收益率等",
        cost_level="low",
    )

    return registry
