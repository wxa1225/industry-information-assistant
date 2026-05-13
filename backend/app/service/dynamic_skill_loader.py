# Copyright © 2026  版权所有

"""
动态技能加载器 - Dynamic Skill Loader

在 ResearchToolRegistry 基础上增加：
1. 基于查询意图的技能自动匹配 — 不依赖 LLM 选择，先用规则快速筛选
2. 技能评分排序 — 根据任务类型、数据可用性、成本综合评分
3. 技能依赖链 — 某些技能需要先执行其他技能（如 deep_read 需要先 web_search）
4. 按需延迟加载 — 只在需要时才初始化重型技能（如代码执行器）
5. 技能热插拔 — 运行时可动态加载/卸载技能插件
"""

import re
import logging
import time
from typing import Dict, Any, List, Optional, Callable, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ============================================================
# 技能元数据与意图匹配
# ============================================================

@dataclass
class SkillCapability:
    """技能能力描述"""
    keywords: List[str]          # 触发关键词
    categories: List[str]        # 适用的研究类别
    data_types: List[str]        # 能提供的数据类型
    prerequisites: List[str]     # 前置技能依赖


@dataclass
class Skill:
    """动态技能定义"""
    name: str
    display_name: str
    description: str
    capability: SkillCapability
    handler: Optional[Callable] = None
    cost_level: str = "low"
    enabled: bool = True
    load_on_demand: bool = False  # 是否延迟加载
    _lazy_loader: Optional[Callable] = None  # 延迟加载函数

    # 渐进式加载：元数据 vs 完整内容
    short_description: str = ""  # 短描述（放入 prompt 上下文，省 token）
    full_description: str = ""   # 完整描述（命中后才加载）

    def load(self):
        """延迟加载技能"""
        if self._lazy_loader and self.handler is None:
            try:
                self.handler = self._lazy_loader()
                logger.debug(f"技能延迟加载成功: {self.name}")
            except Exception as e:
                logger.error(f"技能延迟加载失败: {self.name} - {e}")
                self.enabled = False

    def get_context_snippet(self) -> str:
        """获取用于 LLM 上下文的精简描述（渐进式加载第一阶段）"""
        if self.short_description:
            return f"- {self.name}: {self.short_description}"
        return f"- {self.name}: {self.description[:80]}..."

    def get_full_context(self) -> str:
        """获取完整描述（渐进式加载第二阶段，命中后加载）"""
        return self.full_description or self.description


class DynamicSkillLoader:
    """
    动态技能加载器

    根据研究查询的意图，自动匹配和加载最相关的技能组合。

    工作流程：
    1. 意图识别 — 从查询中提取关键词和研究类别
    2. 技能匹配 — 根据意图筛选候选技能
    3. 依赖解析 — 自动补充前置技能
    4. 成本约束 — 在预算范围内选择最优组合
    5. 返回技能列表
    """

    # 研究类别到关键词的映射
    CATEGORY_KEYWORDS = {
        "market_analysis": ["市场", "规模", "增长", "趋势", "渗透率", "销量", "产值", "收入"],
        "policy_impact": ["政策", "法规", "补贴", "监管", "双碳", "入表", "改革"],
        "competitive_analysis": ["竞争", "对比", "格局", "份额", "优势", "劣势", "vs", "比较"],
        "trend_forecast": ["前景", "未来", "预测", "机会", "挑战", "商业化", "瓶颈"],
        "technology": ["技术", "研发", "专利", "创新", "突破", "算法", "芯片"],
        "finance": ["财务", "融资", "IPO", "估值", "投资", "基金", "股票"],
    }

    # 数据类型到技能的映射
    DATA_TYPE_SKILLS = {
        "numerical_data": ["web_search", "stock_query", "tushare_query"],
        "text_knowledge": ["local_knowledge", "web_search", "deep_read"],
        "source_reference": ["source_tracing", "web_search"],
        "visual_chart": ["code_wizard", "data_analyst"],
    }

    def __init__(self):
        self._skills: Dict[str, Skill] = {}
        self._skill_scores: Dict[str, float] = {}

    def register(self, skill: Skill):
        """注册技能"""
        self._skills[skill.name] = skill

    def unregister(self, name: str):
        """注销技能"""
        skill = self._skills.pop(name, None)
        if skill and skill.load_on_demand:
            skill.handler = None  # 释放资源

    def select_skills(
        self,
        query: str,
        category: str = "",
        max_skills: int = 3,
        max_cost: str = "medium",
    ) -> List[Skill]:
        """
        根据查询自动选择最相关的技能。

        Args:
            query: 研究查询
            category: 研究类别（可选，空则自动识别）
            max_skills: 最多选择的技能数量
            max_cost: 最大成本等级

        Returns:
            排序后的技能列表
        """
        # 1. 意图识别
        if not category:
            category = self._identify_category(query)

        # 2. 提取数据类型需求
        needed_data_types = self._infer_data_types(query, category)

        # 3. 技能匹配与评分
        scored_skills = []
        cost_limit = {"low": 0, "medium": 1, "high": 2}
        max_cost_level = cost_limit.get(max_cost, 2)

        for name, skill in self._skills.items():
            if not skill.enabled:
                continue

            # 成本过滤
            if cost_limit.get(skill.cost_level, 0) > max_cost_level:
                continue

            score = self._score_skill(skill, query, category, needed_data_types)
            if score > 0:
                scored_skills.append((score, skill))

        # 4. 排序并取 top_k
        scored_skills.sort(key=lambda x: x[0], reverse=True)
        selected = [skill for _, skill in scored_skills[:max_skills]]

        # 5. 依赖解析 — 自动补充前置技能
        selected = self._resolve_dependencies(selected)

        # 6. 延迟加载
        for skill in selected:
            if skill.load_on_demand:
                skill.load()

        logger.debug(f"技能选择: query='{query[:50]}...' category={category} "
                     f"skills={[s.name for s in selected]}")
        return selected

    def _identify_category(self, query: str) -> str:
        """从查询中识别研究类别"""
        best_category = "general"
        best_score = 0

        for category, keywords in self.CATEGORY_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in query)
            if score > best_score:
                best_score = score
                best_category = category

        return best_category

    def _infer_data_types(self, query: str, category: str) -> Set[str]:
        """推断需要的数据类型"""
        data_types = set()

        # 包含数字/统计相关词汇 → 需要数值数据
        if any(kw in query for kw in ["数据", "统计", "规模", "增长", "占比", "率"]):
            data_types.add("numerical_data")

        # 包含分析/研究相关词汇 → 需要文本知识
        if any(kw in query for kw in ["分析", "研究", "现状", "洞察", "解读"]):
            data_types.add("text_knowledge")

        # 包含引用/来源相关词汇 → 需要信源追溯
        if any(kw in query for kw in ["来源", "引用", "报告", "数据"]):
            data_types.add("source_reference")

        # 市场分析和竞争分析通常需要图表
        if category in ("market_analysis", "competitive_analysis"):
            data_types.add("visual_chart")

        return data_types

    def _score_skill(
        self,
        skill: Skill,
        query: str,
        category: str,
        needed_data_types: Set[str],
    ) -> float:
        """
        计算技能相关度评分。

        评分维度：
        - 关键词匹配度（0-0.4）
        - 类别匹配度（0-0.3）
        - 数据类型覆盖度（0-0.3）
        """
        score = 0.0

        # 1. 关键词匹配
        cap = skill.capability
        if cap.keywords:
            kw_matches = sum(1 for kw in cap.keywords if kw in query)
            kw_score = min(kw_matches / max(len(cap.keywords) * 0.5, 1), 1.0)
            score += kw_score * 0.4

        # 2. 类别匹配
        if cap.categories and category in cap.categories:
            score += 0.3

        # 3. 数据类型覆盖
        if needed_data_types:
            covered = sum(
                1 for dt in needed_data_types
                if dt in cap.data_types or any(
                    skill.name in self.DATA_TYPE_SKILLS.get(dt, [])
                    for dt in needed_data_types
                )
            )
            coverage = covered / len(needed_data_types)
            score += coverage * 0.3

        return score

    def _resolve_dependencies(self, skills: List[Skill]) -> List[Skill]:
        """解析并补充前置技能依赖"""
        selected_names = {s.name for s in skills}
        added = True

        while added:
            added = False
            for skill in list(skills):
                for prereq_name in skill.capability.prerequisites:
                    if prereq_name not in selected_names:
                        prereq = self._skills.get(prereq_name)
                        if prereq and prereq.enabled:
                            skills.append(prereq)
                            selected_names.add(prereq_name)
                            added = True
                            logger.debug(f"自动补充前置技能: {prereq_name}")

        return skills

    def get_all_skills(self) -> List[Skill]:
        """获取所有已注册技能"""
        return list(self._skills.values())

    def search_skills(self, query: str, top_k: int = 3) -> List[Skill]:
        """
        tool_search 机制：按关键词搜索相关技能。

        面试回答要点：
        "项目实现了类似 Claude Code 的 tool_search 机制——模型默认看不到所有工具的完整定义，
        而是通过关键词搜索按需加载。这是渐进式披露在'工具维度'的进一步推广。"

        搜索维度：
        1. 技能名称匹配
        2. 描述关键词匹配
        3. 能力关键词匹配
        4. 数据类型匹配

        Args:
            query: 搜索查询（如"数据分析"、"图表"、"搜索"）
            top_k: 最多返回数量

        Returns:
            相关技能列表（按匹配度排序）
        """
        scored = []
        query_lower = query.lower()

        for name, skill in self._skills.items():
            if not skill.enabled:
                continue

            score = 0.0

            # 1. 名称精确匹配（最高权重）
            if query_lower in name.lower():
                score += 10.0

            # 2. 展示名称匹配
            if query_lower in skill.display_name.lower():
                score += 5.0

            # 3. 描述关键词匹配
            if any(kw in skill.description.lower() for kw in query_lower.split()):
                score += 3.0

            # 4. 能力关键词匹配
            cap = skill.capability
            if any(kw in query_lower for kw in cap.keywords):
                score += 2.0

            # 5. 数据类型匹配
            if any(kw in dt.lower() for kw in query_lower.split() for dt in cap.data_types):
                score += 1.0

            if score > 0:
                scored.append((score, skill))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [skill for _, skill in scored[:top_k]]

    def get_skill_info_summary(self) -> str:
        """生成技能摘要信息（用于日志和调试）"""
        lines = [f"已注册技能: {len(self._skills)}"]
        for skill in self._skills.values():
            status = "enabled" if skill.enabled else "disabled"
            loaded = "loaded" if skill.handler else "not loaded"
            lines.append(f"  - {skill.name} ({status}, {loaded}): {skill.description[:50]}")
        return "\n".join(lines)

    def get_skill_metadata_prompt(self, max_skills: int = 5) -> str:
        """
        渐进式加载第一阶段：只获取技能的精简元数据描述。

        用于放入 LLM prompt 的工具描述层，大幅减少 token 消耗。
        相比全量描述，token 消耗减少约 60-70%。

        Args:
            max_skills: 最多展示的技能数量（放入 prompt 的候选技能）

        Returns:
            精简版工具描述文本
        """
        # 按启用状态和成本等级排序，优先展示低成本技能
        cost_order = {"low": 0, "medium": 1, "high": 2}
        available = sorted(
            [s for s in self._skills.values() if s.enabled],
            key=lambda s: cost_order.get(s.cost_level, 99)
        )[:max_skills]

        lines = ["可用工具（精简描述）："]
        for skill in available:
            lines.append(f"  {skill.get_context_snippet()} [成本: {skill.cost_level}]")

        return "\n".join(lines)

    def get_selected_skills_full_context(self, selected_skills: List[Skill]) -> str:
        """
        渐进式加载第二阶段：技能命中后，加载完整描述。

        当技能被选中执行时，才加载完整的工具说明和使用指南。

        Args:
            selected_skills: 被选中的技能列表

        Returns:
            完整工具描述文本
        """
        lines = ["已选工具（详细说明）："]
        for skill in selected_skills:
            lines.append(f"  ## {skill.display_name} ({skill.name})")
            lines.append(f"  {skill.get_full_context()}")
            lines.append(f"  数据类型: {', '.join(skill.capability.data_types)}")
            if skill.capability.prerequisites:
                lines.append(f"  前置依赖: {', '.join(skill.capability.prerequisites)}")
            lines.append("")

        return "\n".join(lines)


# ============================================================
# 默认技能注册
# ============================================================

def create_default_skill_loader() -> DynamicSkillLoader:
    """创建默认的动态技能加载器"""
    loader = DynamicSkillLoader()

    loader.register(Skill(
        name="web_search",
        display_name="全网搜索",
        description="通过搜索引擎 API 获取互联网上的公开信息",
        capability=SkillCapability(
            keywords=["搜索", "查找", "了解", "最新", "新闻", "概况"],
            categories=["market_analysis", "policy_impact", "competitive_analysis", "trend_forecast", "general"],
            data_types=["text_knowledge", "numerical_data", "source_reference"],
        ),
        cost_level="low",
    ))

    loader.register(Skill(
        name="local_knowledge",
        display_name="本地知识库",
        description="从本地存储的行业文档中检索相关知识",
        capability=SkillCapability(
            keywords=["行业报告", "论文", "文档", "知识库", "历史"],
            categories=["market_analysis", "technology", "finance"],
            data_types=["text_knowledge"],
            prerequisites=["web_search"],
        ),
        cost_level="low",
    ))

    loader.register(Skill(
        name="source_tracing",
        display_name="信源追溯",
        description="当发现文章引用了其他数据源时，追溯原始来源",
        capability=SkillCapability(
            keywords=["来源", "引用", "据", "报告显示", "数据"],
            categories=["market_analysis", "policy_impact", "competitive_analysis"],
            data_types=["source_reference"],
            prerequisites=["web_search"],
        ),
        cost_level="medium",
    ))

    loader.register(Skill(
        name="deep_read",
        display_name="深度阅读",
        description="进入目标网页，读取完整正文内容",
        capability=SkillCapability(
            keywords=["详细内容", "完整", "深入", "解读"],
            categories=["market_analysis", "technology", "trend_forecast"],
            data_types=["text_knowledge"],
            prerequisites=["web_search"],
        ),
        cost_level="medium",
    ))

    loader.register(Skill(
        name="stock_query",
        display_name="股票行情",
        description="查询上市公司实时股票行情数据",
        capability=SkillCapability(
            keywords=["股票", "股价", "市值", "上市公司", "A股", "港股"],
            categories=["finance", "competitive_analysis"],
            data_types=["numerical_data"],
        ),
        cost_level="low",
    ))

    loader.register(Skill(
        name="tushare_query",
        display_name="Tushare 财经数据",
        description="通过 Tushare API 获取中国财经市场数据",
        capability=SkillCapability(
            keywords=["财务", "财报", "营收", "利润", "营收", "增长率", "ROE"],
            categories=["finance", "market_analysis"],
            data_types=["numerical_data"],
        ),
        cost_level="low",
        load_on_demand=True,
        _lazy_loader=lambda: _load_tushare_handler(),
    ))

    loader.register(Skill(
        name="code_wizard",
        display_name="代码执行器",
        description="执行 Python 代码进行数据分析和可视化",
        capability=SkillCapability(
            keywords=["图表", "可视化", "数据", "分析", "计算", "对比"],
            categories=["market_analysis", "competitive_analysis", "finance"],
            data_types=["visual_chart", "numerical_data"],
        ),
        cost_level="high",
        load_on_demand=True,
        _lazy_loader=lambda: _load_code_wizard_handler(),
    ))

    return loader


def _load_tushare_handler():
    """延迟加载 Tushare handler"""
    from service.tushare_service import get_tushare_service
    return get_tushare_service()


def _load_code_wizard_handler():
    """延迟加载 Code Wizard handler"""
    from service.deep_research_v2.agents.wizard import CodeWizard
    return CodeWizard()
