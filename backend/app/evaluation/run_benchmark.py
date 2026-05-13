#!/usr/bin/env python3
"""
基准测试运行脚本

运行 V1（简单研究）vs V2（多智能体深度研究）对比测试，
产出量化报告。

用法:
    cd backend
    python -m app.evaluation.run_benchmark [--cases 3] [--config v1|v2|both]
"""

import asyncio
import json
import os
import sys
import time
import logging
from pathlib import Path
from typing import Dict, Any, List

# 设置路径
APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from dotenv import load_dotenv
load_dotenv()

from evaluation.benchmark import BenchmarkRunner, BenchmarkCase, BenchmarkResult
from evaluation.metrics import ResearchMetrics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("benchmark")

GOLD_STANDARD_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "golden_test_set.json"
REPORT_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "benchmark_report.md"


async def research_v1(query: str) -> Dict[str, Any]:
    """
    V1 研究函数 — 简单研究模式（单 Agent，直接 LLM 调用）。
    模拟快速但不深度的研究。
    """
    from openai import OpenAI

    client = OpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url=os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    )
    model = os.getenv("DASHSCOPE_MODEL", "qwen-plus")

    start = time.time()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一个专业的行业研究分析师。请针对用户的问题提供详细的研究分析，包含数据、事实和洞察。请用中文回答。"},
                {"role": "user", "content": f"请深入研究以下问题，提供包含具体数据、来源引用和多维度分析的报告：\n\n{query}"}
            ],
            temperature=0.3,
            max_tokens=4000,
        )

        report = response.choices[0].message.content
        duration = time.time() - start
        tokens = response.usage.total_tokens if response.usage else 0

        # 构造 ResearchState 兼容格式
        state = {
            "final_report": report,
            "facts": [],
            "references": [],
            "data_points": [],
            "charts": [],
            "outline": [],
            "draft_sections": {},
            "logs": [{"model": model, "tokens_used": tokens, "duration": duration}],
        }

        # 从报告中尝试提取事实
        state["facts"] = _extract_facts(report)

        return state

    except Exception as e:
        logger.error(f"V1 研究失败: {e}")
        return {
            "final_report": "",
            "facts": [],
            "references": [],
            "data_points": [],
            "logs": [],
            "error": str(e),
        }


async def research_v2(query: str) -> Dict[str, Any]:
    """
    V2 研究函数 — 多智能体深度研究模式。
    """
    try:
        from service.deep_research_v2 import DeepResearchV2
        from service.deep_research_v2.state import ResearchState

        researcher = DeepResearchV2()
        state = ResearchState(query=query)

        result = await researcher.run(query, max_iterations=2)

        # 转换为评估格式
        return {
            "final_report": result.get("final_report", ""),
            "facts": result.get("facts", []),
            "references": result.get("references", []),
            "data_points": result.get("data_points", []),
            "charts": result.get("charts", []),
            "outline": result.get("outline", []),
            "draft_sections": result.get("draft_sections", {}),
            "conflict_report": result.get("conflict_report", {}),
            "logs": result.get("logs", []),
        }

    except ImportError:
        logger.warning("V2 模块不可用，跳过 V2 测试")
        return {"final_report": "", "facts": [], "references": [], "data_points": [], "logs": [], "error": "V2 module not available"}
    except Exception as e:
        logger.error(f"V2 研究失败: {e}")
        return {"final_report": "", "facts": [], "references": [], "data_points": [], "logs": [], "error": str(e)}


def _extract_facts(text: str) -> List[Dict]:
    """从报告文本中简单提取事实（用于 V1 评估）。"""
    import re
    facts = []
    # 提取包含数字的句子
    sentences = re.split(r'[。；;.\n]', text)
    for sentence in sentences:
        sentence = sentence.strip()
        if re.search(r'\d+', sentence) and len(sentence) > 10:
            facts.append({
                "content": sentence,
                "source_name": "",
                "source_url": "",
                "source_type": "llm_generated",
            })
    return facts


async def run_benchmark(config: str = "both", max_cases: int = None):
    """运行基准测试"""

    # 加载黄金测试集
    runner = BenchmarkRunner(str(GOLD_STANDARD_PATH))
    if not runner.cases:
        logger.error("无法加载黄金测试集，请检查路径: %s", GOLD_STANDARD_PATH)
        sys.exit(1)

    cases = runner.cases
    if max_cases:
        cases = cases[:max_cases]

    logger.info(f"加载 {len(cases)} 个测试用例")

    results_by_config = {}

    if config in ("v1", "both"):
        logger.info("=" * 60)
        logger.info("开始 V1（简单研究）测试")
        logger.info("=" * 60)

        v1_results = []
        for case in cases:
            result = await runner.run_single(
                case,
                lambda q: research_v1(q),
                config_name="v1_simple",
            )
            v1_results.append(result)
            logger.info(f"  V1 [{case.id}] 得分={result.total_score:.3f} 耗时={result.duration_seconds:.1f}s")

        results_by_config["v1_simple"] = v1_results

    if config in ("v2", "both"):
        logger.info("=" * 60)
        logger.info("开始 V2（多智能体深度研究）测试")
        logger.info("=" * 60)

        v2_results = []
        for case in cases:
            result = await runner.run_single(
                case,
                lambda q: research_v2(q),
                config_name="v2_multi_agent",
            )
            v2_results.append(result)
            logger.info(f"  V2 [{case.id}] 得分={result.total_score:.3f} 耗时={result.duration_seconds:.1f}s")

        results_by_config["v2_multi_agent"] = v2_results

    # 生成对比报告
    comparison = runner.compare_configs(results_by_config)
    report = runner.generate_comparison_markdown(comparison)

    # 添加详细结果
    detailed_report = _build_detailed_report(comparison, results_by_config, cases)

    # 保存报告
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(detailed_report)

    logger.info(f"\n基准测试完成！报告已保存至: {REPORT_PATH}")

    # 打印摘要
    print("\n" + "=" * 60)
    print("基准测试摘要")
    print("=" * 60)
    for config_name, stats in comparison["configs"].items():
        print(f"  {config_name}: 平均分={stats['avg_score']:.3f} "
              f"平均耗时={stats['avg_duration']:.1f}s "
              f"平均成本=¥{stats['avg_cost']:.4f} "
              f"成功率={stats['success_rate']:.0%}")
    print(f"\n最优配置: {comparison['best_config']}")

    return comparison


def _build_detailed_report(
    comparison: Dict[str, Any],
    results_by_config: Dict[str, List[BenchmarkResult]],
    cases: List[BenchmarkCase],
) -> str:
    """构建详细的 Markdown 报告"""
    lines = [
        "# 行业信息助手 - 基准测试报告\n",
        f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"测试集: {len(cases)} 个测试用例\n",
        "---\n",
    ]

    # 对比表格
    lines.append("## 配置对比\n")
    lines.append("| 配置 | 平均分 | 平均耗时 | 平均成本 | 成功率 | 测试数 |")
    lines.append("|------|--------|---------|---------|--------|--------|")
    for config_name, stats in comparison["configs"].items():
        lines.append(
            f"| {config_name} "
            f"| {stats['avg_score']:.3f} "
            f"| {stats['avg_duration']:.1f}s "
            f"| ¥{stats['avg_cost']:.4f} "
            f"| {stats['success_rate']:.0%} "
            f"| {stats.get('successful', 0)}/{stats['count']} |"
        )
    lines.append(f"\n**最优配置**: {comparison['best_config']}\n")

    # 各配置的详细结果
    for config_name, results in results_by_config.items():
        lines.append(f"\n## {config_name} 详细结果\n")
        lines.append("| ID | 查询 | 得分 | 耗时 | Token | LLM调用 | 错误 |")
        lines.append("|----|------|------|------|-------|---------|------|")
        for r in results:
            query_short = r.query[:30] + "..." if len(r.query) > 30 else r.query
            error_mark = f"⚠️ {r.error[:30]}" if r.error else ""
            lines.append(
                f"| {r.case_id} | {query_short} "
                f"| {r.total_score:.3f} "
                f"| {r.duration_seconds:.1f}s "
                f"| {r.total_tokens} "
                f"| {r.llm_calls} "
                f"| {error_mark} |"
            )

        # 按类别汇总
        lines.append(f"\n### 按类别汇总 ({config_name})\n")
        category_scores = {}
        for r in results:
            case = next((c for c in cases if c.id == r.case_id), None)
            if case:
                cat = case.category
                if cat not in category_scores:
                    category_scores[cat] = []
                category_scores[cat].append(r.total_score)

        lines.append("| 类别 | 平均分 | 测试数 |")
        lines.append("|------|--------|--------|")
        for cat, scores in category_scores.items():
            avg = sum(scores) / len(scores)
            cat_name = {
                "market_analysis": "市场分析",
                "policy_impact": "政策影响",
                "competitive_analysis": "竞争分析",
                "trend_forecast": "趋势预测",
            }.get(cat, cat)
            lines.append(f"| {cat_name} | {avg:.3f} | {len(scores)} |")

    # 结论与建议
    lines.append("\n## 结论与建议\n")
    if "v1_simple" in comparison["configs"] and "v2_multi_agent" in comparison["configs"]:
        v1_score = comparison["configs"]["v1_simple"]["avg_score"]
        v2_score = comparison["configs"]["v2_multi_agent"]["avg_score"]
        improvement = (v2_score - v1_score) / v1_score * 100 if v1_score > 0 else 0

        lines.append(f"- V1 简单研究平均分: **{v1_score:.3f}**")
        lines.append(f"- V2 多智能体平均分: **{v2_score:.3f}**")
        lines.append(f"- V2 相对 V1 提升: **{improvement:+.1f}%**")
        lines.append("")
        if v2_score > v1_score:
            lines.append("多智能体架构在研究质量上显著优于简单 LLM 调用，")
            lines.append("验证了 Architect → Scout → Analyst → Writer → Critic 协作流程的价值。")
        else:
            lines.append("V2 多智能体架构未见明显优势，可能需要优化 Agent 间协作效率或 Prompt 质量。")

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="运行基准测试")
    parser.add_argument("--cases", type=int, default=None, help="运行测试数量（默认全部）")
    parser.add_argument("--config", choices=["v1", "v2", "both"], default="both", help="测试配置")
    args = parser.parse_args()

    asyncio.run(run_benchmark(config=args.config, max_cases=args.cases))
