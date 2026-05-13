# 智能行业研究平台 — 带交叉验证的 AI 深度研究报告生成系统

> 面向券商/咨询公司/投研团队的 AI 行业研究报告自动生成平台
> 核心差异化：每份报告的结论都经过多源交叉验证，每条事实带置信度评分

## 问题背景

券商分析师和咨询顾问撰写行业研究报告时面临三个核心痛点：

1. **数据采集耗时** — 需要手动搜索行业数据、政策文件、公司信息，通常占研究时间的 60%+
2. **矛盾结论难辨** — 不同来源给出互相矛盾的数据（A 报告说市场规模 1000 亿，B 报告说 5000 亿），人工验证费时
3. **质量难以保证** — 纯靠人工经验判断信息来源可信度，缺乏系统化的置信度评估

本系统用多智能体协作自动化"研究计划 → 数据采集 → 分析 → 撰写 → 审核"全流程，并在审核环节自动检测数据冲突、执行交叉验证、输出带置信度的验证结论。

## 系统架构

```
用户输入行业研究问题（如"中国新能源汽车市场规模与竞争格局"）
        │
        ▼
┌───────────────────────────────────────────────┐
│           ChiefArchitect (总架构师)            │
│  意图解析 → 生成研究大纲 → 制定搜索计划        │
└───────────────────┬───────────────────────────┘
                    │
        ┌───────────▼───────────┐
        │   DeepScout (侦察员)    │
        │  多源数据采集 → 事实提取│
        └───────────┬───────────┘
                    │
        ┌───────────▼─────────────────────┐
        │  DataAnalyst + CodeWizard       │
        │  数据分析 → Python 代码执行 → 图表│
        └───────────┬─────────────────────┘
                    │
        ┌───────────▼─────────────┐
        │   LeadWriter (首席写手)   │
        │  逐章撰写研究报告        │
        └───────────┬─────────────┘
                    │
        ┌───────────▼───────────────────────────┐
        │        CriticMaster (审核+交叉验证)     │
        │  ① 质量审核 → ② 冲突检测               │
        │  ③ 交叉验证 → ④ 置信度评分              │
        └───────────┬───────────────────────────┘
                    │
                    ▼
        ┌───────────────────────────────┐
        │  研究报告 + 验证档案            │
        │  （每结论带置信度+证据链）     │
        └───────────────────────────────┘
```

## 核心能力

| 能力 | 说明 |
|------|------|
| **多智能体研究流程** | 6 个专家 Agent 协作：架构师定大纲 → 侦察员搜数据 → 分析师做分析 → 代码极客画图 → 写手写报告 → 审核员质检 |
| **交叉验证引擎** | 自动检测报告中的矛盾数据（数值矛盾、结论方向矛盾），发起补充搜索验证，输出验证结论 |
| **置信度评分** | 四维加权：来源权威性 35% + 交叉验证 30% + 时效性 20% + 信息具体度 15%，每条事实独立评分 |
| **动态工具选择** | 根据研究问题意图自动匹配技能（搜索/知识库/Tushare 财经/代码执行），依赖链自动补全 |
| **LLM 调用优化** | 响应缓存 + Few-shot 示例 + 指数退避重试 + 多模型降级，调用失败率降低 90%+ |
| **代码自愈** | Python 数据分析沙箱执行，失败后 LLM 自动修复（最多 3 次重试） |
| **全链路可观测** | 每次研究生成 trace_id，记录所有 LLM 调用、token 消耗、成本估算，按 Agent 维度输出成本分布 |
| **记忆系统** | 长期记忆四层噪声过滤（哈希/语义/信息增益/价值评分），混合召回（语义 60% + 时间衰减 25% + 重要性 15%） |
| **自动化评估** | 7 项指标 + LLM-as-Judge + 15 条黄金测试集，支持 V1 vs V2 A/B 对比 |

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | FastAPI + Python 3.10+ |
| 前端 | React 19 + TypeScript + Vite 6 + Ant Design 5 |
| LLM | 阿里云百炼 (DashScope) — deepseek-v3.2, qwen-plus 多模型路由 |
| 存储 | PostgreSQL + Redis + Milvus (向量库) + Elasticsearch + MinIO |
| 搜索 | 博查 Web Search API |
| 基础设施 | Docker Compose |

## 快速启动

### 1. 启动基础设施

```bash
docker compose up -d
```

包含：PostgreSQL (5432), Redis (6379), Milvus (19530), Elasticsearch (1200), MinIO (9001/9001)

### 2. 配置环境变量

```bash
cd backend
cp .env.example .env
# 编辑 .env，填入 API Key
```

必填项：
```env
DASHSCOPE_API_KEY=your-key     # 阿里云百炼
BOCHA_API_KEY=your-key         # 博查搜索
```

### 3. 启动后端

```bash
cd backend
pip install -r requirements.txt
python app/app_main.py
```

### 4. 启动前端

```bash
cd frontend
npm install --legacy-peer-deps
npm run dev
```

前端默认运行在 `http://localhost:5173`，后端在 `http://localhost:8000`。

## API 文档

启动后端后访问：`http://localhost:8000/docs`

### 核心 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/research/stream` | 启动深度研究（SSE 流式） |
| GET | `/trace/{trace_id}` | 获取研究的全链路 Trace（执行轨迹 + 成本报告） |
| GET | `/traces` | 列出所有研究 Trace |
| GET | `/research/checkpoint/{session_id}` | 获取研究检查点 |

## 评估体系

系统内置自动化评估模块 (`backend/app/evaluation/`)，支持：

- **7 项自动化指标**：来源多样性、引用密度、时效性、章节完整度、幻觉率、数据丰富度、冲突解决率
- **LLM-as-a-Judge**：对逻辑连贯性、论点支撑度、专业深度、可读性进行 rubric-based 评估
- **15 条黄金测试集**：覆盖 AI 芯片、安责险、新能源汽车、云计算、半导体等行业分析场景
- **基准测试对比**：支持 A/B 对比不同配置（V1 vs V2，不同 prompt 版本）的效果

## 项目结构

```
industry_information_assistant/
├── backend/app/
│   ├── config/              # LLM & Agent 配置（per-agent 模型分配）
│   ├── core/                # 数据库、Redis、缓存
│   ├── models/              # 数据模型（用户、会话、知识库、研究检查点）
│   ├── router/              # API 路由
│   ├── service/
│   │   ├── deep_research_v2/    # V2 多智能体协作引擎
│   │   │   ├── agents/          # 6 个专家 Agent
│   │   │   ├── graph.py         # 工作流状态机
│   │   │   └── service.py       # 服务入口
│   │   ├── conflict_detector/   # 冲突检测与交叉验证模块
│   │   ├── observability/       # 可观测性（Token 统计 + Trace + 成本）
│   │   └── chat_service.py      # 聊天服务
│   └── evaluation/          # 自动化评估体系
│       ├── metrics.py         # 7 项自动化指标
│       ├── llm_judge.py       # LLM-as-a-Judge
│       ├── benchmark.py       # 基准测试运行器
│       ├── gold_standard.json # 黄金测试集
│       └── report.py          # 评估报告生成
├── frontend/src/
│   ├── pages/chat/          # 聊天 + 深度研究页面
│   └── api/                 # API 调用
├── docker-compose.yml       # 基础设施编排
└── docker/init-db/          # 数据库初始化脚本
```

## 项目结构

```
industry_information_assistant/
├── backend/app/
│   ├── config/              # LLM &Agent 配置（per-agent 模型分配）
│   ├── core/                # 数据库、Redis、缓存
│   ├── models/              # 数据模型（用户、会话、知识库、研究检查点）
│   ├── router/              # API 路由
│   ├── service/
│   │   ├── deep_research_v2/    # V2 多智能体协作引擎
│   │   │   ├── agents/          # 6 个专家 Agent
│   │   │   ├── graph.py         # 工作流状态机
│   │   │   └── service.py       # 服务入口
│   │   ├── conflict_detector/   # 冲突检测与交叉验证模块
│   │   ├── observability/       # 可观测性（Token 统计 + Trace + 成本）
│   │   └── chat_service.py      # 聊天服务
│   └── evaluation/          # 自动化评估体系
│       ├── metrics.py         # 7 项自动化指标
│       ├── llm_judge.py       # LLM-as-a-Judge
│       ├── benchmark.py       # 基准测试运行器
│       ├── gold_standard.json # 黄金测试集
│       └── report.py          # 评估报告生成
├── frontend/src/
│   ├── pages/chat/          # 聊天 + 深度研究页面
│   └── api/                 # API 调用
├── docker-compose.yml       # 基础设施编排
└── docker/init-db/          # 数据库初始化脚本
```
