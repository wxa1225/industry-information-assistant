# 第三轮修复记录 — Memory、Benchmark、Harness、Skill 优化

> 日期：2026-05-12
> 背景：针对面试准备中暴露的不足，补全 Memory 系统、Benchmark 评估、LLM Harness、动态 Skill 加载

---

## 一、新增文件

### 1. Memory 噪声过滤

| 文件 | 说明 |
|------|------|
| `backend/app/service/memory_noise_filter.py` | 四层噪声过滤器：哈希去重、语义相似度（>0.90）、信息增益（>0.15）、价值评分（>0.30） |

### 2. Memory 召回优化（集成到现有文件）

| 修改 | 说明 |
|------|------|
| `backend/app/service/memory_service.py` | 新增：噪声过滤集成、混合召回（语义 60% + 时间衰减 25% + 重要性 15%）、时间衰减因子（指数衰减 λ=0.05）、重要性加权（类型+长度+实体） |

### 3. Benchmark 评估系统

| 文件 | 说明 |
|------|------|
| `data/golden_test_set.json` | 15 个黄金测试用例，覆盖市场分析、政策影响、竞争分析、趋势预测四大类别 |
| `backend/app/evaluation/run_benchmark.py` | V1 vs V2 基准测试运行器，自动产出对比报告 |

### 4. LLM Harness 优化

| 文件 | 说明 |
|------|------|
| `backend/app/service/llm_harness.py` | LLM 调用管理器：响应缓存（SHA256 去重）、Few-shot 示例库（5 个 Agent 各含高质量示例）、重试与降级策略（指数退避 + 多模型 fallback）、调用统计 |

### 5. 动态 Skill 加载

| 文件 | 说明 |
|------|------|
| `backend/app/service/dynamic_skill_loader.py` | 动态技能加载器：基于意图自动匹配技能、技能评分排序、依赖链解析、延迟加载（代码执行器、Tushare 等重型组件）、热插拔 |

---

## 二、修改的文件

| 文件 | 修改内容 |
|------|---------|
| `backend/app/service/memory_service.py` | 导入 MemoryNoiseFilter；__init__ 初始化过滤器并加载已有摘要；新增 _load_existing_memory_summaries()；新增 _estimate_similarity()；新增 _filter_summary_data()；create_memory() 增加噪声过滤；retrieve_memories() 改为混合召回 + 重排序；新增 _rerank_memories()、_compute_time_decay()、_compute_importance() |
| `backend/app/service/memory_noise_filter.py` | 修复正则表达式中中文引号导致的 SyntaxError |

---

## 三、各模块的核心设计

### Memory 噪声过滤

```
新记忆 → 长度检查 → 哈希去重 → 语义相似度 → 信息增益 → 价值评分 → 存储
         (<20字)   (MD5)      (embedding)  (停用词/数字) (密度/事实/完整)
```

四层过滤确保只存储高质量记忆，避免"垃圾进、垃圾出"。

### Memory 召回策略

```
查询 → 向量搜索(Milvus, 召回 3×top_k) → 混合重排序 → 返回 top_k
                                    ├─ 语义得分 × 0.6
                                    ├─ 时间衰减 × 0.25 (e^{-0.05×days})
                                    └─ 重要性 × 0.15 (类型+长度+实体)
```

### Benchmark 评估

```
Golden Set (15 cases) → V1 (单 Agent) → 指标计算 → 报告
                      → V2 (多智能体) → 指标计算 → /
                                          ↓
                          对比报告（平均分/耗时/成本/成功率/按类别汇总）
```

### LLM Harness

```
调用请求 → 缓存检查 → Few-shot 注入 → 重试(指数退避) → 模型降级 → 缓存结果
           (SHA256)    (每Agent 2例)   (最多3次)         (fallback_models)
```

### 动态 Skill 加载

```
查询 → 意图识别 → 技能匹配 → 评分排序 → 依赖解析 → 延迟加载 → 返回技能列表
       (关键词)    (类别+数据)  (0-1分)    (前置技能)   (按需加载)
```

---

## 四、面试问题回答补充

### Q: "你的 Agent 是怎么选择工具的？是硬编码还是动态感知？"

**A**: 使用 DynamicSkillLoader 实现动态感知。根据查询关键词识别研究类别（市场/政策/竞争/趋势），推断需要的数据类型（数值/文本/信源/图表），然后对每个技能进行三维评分（关键词匹配 40% + 类别匹配 30% + 数据类型覆盖 30%），自动选择 top-K 个技能。同时支持技能依赖链自动补充前置技能。

### Q: "长期记忆是怎么避免噪声积累的？"

**A**: 四层噪声过滤：①哈希去重（完全相同内容不重复）；②语义相似度（embedding 计算，>0.9 视为重复）；③信息增益（停用词比例、数字密度，<0.15 视为噪声）；④价值评分（信息密度 40% + 事实性 35% + 完整性 25%，<0.30 丢弃）。召回时采用混合排序：语义 60% + 时间衰减 25% + 重要性 15%。

### Q: "LLM 调用失败怎么处理？"

**A**: LLMHarness 提供三层保障：①缓存命中避免重复调用；②指数退避重试（最多 3 次，延迟 1s→2s→4s）；③多模型降级（主模型失败自动切换到备用模型）。同时统计缓存命中率、重试率、失败率等指标。

### Q: "怎么评估你的研究质量？有量化数据吗？"

**A**: 使用 15 个黄金测试集运行 Benchmark，7 项自动指标（来源多样性、引用密度、时效性、章节完整度、幻觉率、数据丰富度、冲突解决率）+ LLM-as-Judge。支持 V1（简单研究）vs V2（多智能体）对比，自动产出 Markdown 报告。

---

## 五、总结

本次修复聚焦于**算法深度**问题，补充了：

- ✅ Memory 噪声过滤（四层过滤，避免垃圾积累）
- ✅ Memory 召回优化（混合排序，时间衰减 + 重要性加权）
- ✅ Benchmark 评估系统（15 个黄金用例，V1 vs V2 对比）
- ✅ LLM Harness（缓存 + Few-shot + 重试降级）
- ✅ 动态 Skill 加载（意图匹配 + 评分排序 + 依赖链）

这些模块使项目在**算法设计能力**和**系统架构能力**两个维度都达到了大厂面试的可接受水平。
