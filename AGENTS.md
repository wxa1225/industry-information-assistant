# AGENTS.md — 智能行业研究平台编码指南

> 本文档供 AI Coding 工具（Claude Code / Cursor / Codex）和人类开发者参考。
> 建立此文档的目的是让 AI 工具在项目中持续提供高质量输出，不重复探索已解决的问题。

## 项目概述

- **项目名称**：智能行业研究平台 — 带交叉验证的 AI 深度研究报告生成系统
- **技术栈**：FastAPI + React 19 + LangGraph + Milvus + PostgreSQL + Redis
- **核心能力**：6 个专家 Agent 协作生成研究报告，每份报告的结论都经过多源交叉验证，每条事实带置信度评分

## 架构约束

### 必须遵守的规则

1. **所有 LLM 调用必须通过 `BaseAgent.call_llm()`** — 不要绕过重试/降级/可观测性体系
2. **所有 Agent 的 `call_llm` 调用必须使用 `context_layers` 参数** — 通过 `self.build_context_layers(state)` 构建，确保 Prefix Caching 友好
3. **Prompt 中不要硬拼接记忆上下文** — 记忆通过 `context_layers` 作为 Layer 1 传入，不在 `user_prompt` 中拼接
4. **新增 Agent 必须继承 `BaseAgent` 并实现 `process()` 方法**
5. **所有状态修改必须返回 `dict(state)` 副本** — LangGraph 要求不可变状态更新
6. **SSE 事件必须通过 `self.add_message()` 推送** — 不要直接操作 `_message_queue`

### 技术选型约束

| 层 | 选择 | 不要替换为 | 原因 |
|---|------|-----------|------|
| 数据库 | PostgreSQL | MySQL | PG jsonb/pgvector 能力强，2026 新项目共识 |
| 向量库 | Milvus | 内存 FAISS | 生产级分布式，支撑大规模向量检索 |
| 缓存 | Redis | 内存字典 | 跨进程共享 + 分布式锁 |
| LLM 路由 | deepseek-v3.2(写作/审核) + qwen-plus(搜索) | 全局单模型 | 成本优化，搜索占 60% token |
| Agent 编排 | LangGraph | 手写 asyncio | 审核-修订循环需要条件边 |
| 冲突检测 | 正则+Jaccard(粗筛) + LLM(精判) | 纯 LLM | O(N²) 调用量不可接受 |

## LLM 调用最佳实践

### 四层上下文设计（Prefix Caching 友好）

```python
# 正确示例
context_layers = self.build_context_layers(state, tool_description=tool_meta)
response = await self.call_llm(
    system_prompt="你的角色定义...",
    user_prompt="当前任务的具体指令...",
    context_layers=context_layers,
    json_mode=True,
)

# 错误示例 — 不要这样：
prompt = f"{memory_context}\n\n{self.PROMPT.format(query=...)}"  # 拼接到 user_prompt，破坏前缀缓存
```

### JSON 解析

所有 `call_llm(json_mode=True)` 的返回必须通过 `self.parse_json_response(response)` 解析，它处理 markdown 代码块、尾随逗号、无效转义等常见问题。

## 评估体系

- 7 项自动化指标在 `evaluation/metrics.py` 中实现
- precision/recall/F1 在 `evaluation/metrics.py` 的 `compute_precision_recall_f1()` 中实现
- 15 条黄金测试集在 `evaluation/gold_standard.json` 中
- 运行评估：`python app/evaluation/run_benchmark.py`

## 可观测性

- 所有 LLM 调用自动记录 token 用量、成本、延迟
- trace_id 贯穿整个研究生命周期
- 按 Agent 维度输出成本分布
- 访问 `GET /trace/{trace_id}` 获取全链路 Trace

## 成本优化

- 成本熔断：单研究超过 ¥5.00 自动终止
- LLM 响应缓存：SHA256 去重，TTL 24 小时
- 指数退避重试：1s → 2s → 4s
- 模型降级：主模型不可用时自动切换到备用模型
