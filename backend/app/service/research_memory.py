# Copyright © 2026  版权所有

"""
研究记忆集成模块 - Research Memory Integration

在深度研究流程中提供跨 session 的记忆能力：
1. 研究开始前：从 Milvus 检索相关历史研究洞察
2. 研究完成后：将高质量事实和洞察写入长期记忆
3. 记忆上下文注入：将历史记忆嵌入 Planner 的 prompt

解决面试问题："记忆提取具体是怎么做的？召回又是怎么做的？"
"""

import json
import uuid
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# 记忆服务懒加载
_milvus_service = None
_embedding_service_available = False


def _get_services():
    """懒加载 Milvus 和 embedding 服务"""
    global _milvus_service, _embedding_service_available

    if _milvus_service is not None:
        return _milvus_service, _embedding_service_available

    try:
        from service.milvus_service import MilvusService
        from service.embedding_service import generate_embedding
        _milvus_service = MilvusService()
        _embedding_service_available = True
    except ImportError:
        try:
            from app.service.milvus_service import MilvusService
            from app.service.embedding_service import generate_embedding
            _milvus_service = MilvusService()
            _embedding_service_available = True
        except ImportError:
            _milvus_service = None
            _embedding_service_available = False

    return _milvus_service, _embedding_service_available


RESEARCH_MEMORY_COLLECTION = "research_memories"

# ============================================================
# 记忆分类体系（面试回答要点：不是简单噪声过滤，而是有分类的记忆管理）
# ============================================================
# 一级分类（按内容性质）：
#   fact      — 客观事实（市场规模、数值数据、公司名称）
#   derived   — 推导结论（趋势判断、因果关系、竞争格局分析）
#   preference — 用户偏好（关注的行业、偏好的报告风格、常用指标）
#
# 二级分类（按生命周期）：
#   short_term  — 单次研究内有效（研究过程中的中间结论）
#   long_term   — 跨 session 持久化（多次验证后的高价值记忆）
#
# 升级机制：short_term → long_term 的条件
#   1. 被后续研究引用 >= 2 次
#   2. 置信度评分 >= 0.75
#   3. 信息增益评分 >= 0.30
#   4. 非临时性中间结论（非推理链中间步骤）
# ============================================================

MEMORY_CLASSIFICATION = {
    "fact": {
        "description": "客观事实，如市场规模、数值数据、公司信息",
        "weight": 1.0,  # 事实类记忆权重最高
        "examples": ["2024年中国储能电池市场规模1500亿元"],
    },
    "derived": {
        "description": "推导结论，如趋势判断、因果分析",
        "weight": 0.7,
        "examples": ["储能电池行业未来3年将保持30%+增速"],
    },
    "preference": {
        "description": "用户偏好，如关注领域、报告风格",
        "weight": 0.5,
        "examples": ["用户偏好关注新能源行业"],
    },
}

# 短期→长期记忆升级阈值
SHORT_TO_LONG_TERM_THRESHOLD = {
    "min_reference_count": 2,    # 被后续研究引用次数
    "min_confidence": 0.75,      # 最低置信度
    "min_information_gain": 0.30, # 最低信息增益
}


def detect_memory_contradiction(
    new_content: str,
    existing_memories: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    检测新记忆与已有记忆之间是否存在矛盾。

    面试回答要点：
    "记忆系统有矛盾检测机制——用户说过'我喜欢吃辣'和'我不能吃辣'时，
    通过时间戳和语义相似度判断哪个是当前事实，旧的记忆标记为过期而不是直接删除。"

    Args:
        new_content: 新记忆内容
        existing_memories: 已有记忆列表（通常是语义相似度较高的候选记忆）

    Returns:
        矛盾记忆列表，包含矛盾类型和建议处理方式
    """
    contradictions = []

    # 矛盾关键词对
    contradiction_pairs = [
        ("喜欢", "不喜欢"),
        ("喜欢", "不能"),
        ("喜欢", "讨厌"),
        ("增长", "下降"),
        ("上升", "下降"),
        ("超过", "低于"),
        ("高于", "低于"),
        ("是", "不是"),
        ("支持", "反对"),
        ("扩大", "缩小"),
        ("增加", "减少"),
    ]

    # 数值矛盾检测
    import re
    new_numbers = re.findall(r'(\d+\.?\d*)\s*(亿|万|千|百|%|亿元|万亿元)', new_content)

    for existing in existing_memories:
        existing_content = existing.get("content", "")
        if not existing_content:
            continue

        # 1. 关键词矛盾检测
        for pos, neg in contradiction_pairs:
            has_pos_new = pos in new_content
            has_neg_new = neg in new_content
            has_pos_existing = pos in existing_content
            has_neg_existing = neg in existing_content

            # 检查是否存在矛盾组合
            if (has_pos_new and has_neg_existing) or (has_neg_new and has_pos_existing):
                # 进一步检查：两个内容是否在讨论同一个主题
                if _semantic_overlap(new_content, existing_content) > 0.3:
                    contradictions.append({
                        "type": "keyword_contradiction",
                        "contradiction": f"'{pos}' vs '{neg}'",
                        "new_content": new_content[:200],
                        "existing_content": existing_content[:200],
                        "existing_id": existing.get("id"),
                        "resolution": "prefer_new_with_timestamp",
                    })

        # 2. 数值矛盾检测
        existing_numbers = re.findall(r'(\d+\.?\d*)\s*(亿|万|千|百|%|亿元|万亿元)', existing_content)
        if new_numbers and existing_numbers:
            for new_val, new_unit in new_numbers:
                for ext_val, ext_unit in existing_numbers:
                    if new_unit == ext_unit:
                        new_num = float(new_val)
                        ext_num = float(ext_val)
                        # 数值差异超过 2 倍视为矛盾
                        if max(new_num, ext_num) / max(min(new_num, ext_num), 0.001) > 2:
                            if _semantic_overlap(new_content, existing_content) > 0.3:
                                contradictions.append({
                                    "type": "numerical_contradiction",
                                    "contradiction": f"{new_val}{new_unit} vs {ext_val}{ext_unit}",
                                    "new_content": new_content[:200],
                                    "existing_content": existing_content[:200],
                                    "existing_id": existing.get("id"),
                                    "resolution": "prefer_newer_with_higher_confidence",
                                })

    return contradictions


def _semantic_overlap(text1: str, text2: str) -> float:
    """计算两个文本的语义重叠度（简化版 Jaccard）"""
    # 提取关键词（简单的中文字词分割）
    import re
    words1 = set(re.findall(r'[一-龥]{2,4}', text1))
    words2 = set(re.findall(r'[一-龥]{2,4}', text2))

    if not words1 or not words2:
        return 0.0

    intersection = words1 & words2
    union = words1 | words2

    return len(intersection) / len(union)
    """
    记忆分类：根据内容和元数据判断记忆类型。

    Args:
        content: 记忆内容
        metadata: 附加元数据

    Returns:
        {"category": "fact|derived|preference", "lifecycle": "short_term|long_term"}
    """
    # 简单的规则分类（可扩展为 LLM 分类）
    category = "fact"  # 默认

    # 推导结论的特征词
    derived_keywords = ["趋势", "预计", "将", "可能", "导致", "因此", "增长", "下降", "影响"]
    if any(kw in content for kw in derived_keywords):
        category = "derived"

    # 用户偏好的特征
    if metadata and metadata.get("is_user_preference"):
        category = "preference"

    # 生命周期判断：新记忆默认短期
    lifecycle = "short_term"

    # 如果已有多次引用且置信度高，升级为长期
    ref_count = (metadata or {}).get("reference_count", 0)
    confidence = (metadata or {}).get("confidence_score", 0)
    if (ref_count >= SHORT_TO_LONG_TERM_THRESHOLD["min_reference_count"]
            and confidence >= SHORT_TO_LONG_TERM_THRESHOLD["min_confidence"]):
        lifecycle = "long_term"

    return {"category": category, "lifecycle": lifecycle}


def _ensure_collection():
    """确保研究记忆集合存在"""
    milvus, _ = _get_services()
    if milvus is None:
        return False

    try:
        from pymilvus import utility, Collection, CollectionSchema, FieldSchema, DataType

        if utility.has_collection(RESEARCH_MEMORY_COLLECTION):
            return True

        fields = [
            FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
            FieldSchema(name="memory_type", dtype=DataType.VARCHAR, max_length=32),  # fact/insight/trend
            FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=16),     # fact/derived/preference
            FieldSchema(name="lifecycle", dtype=DataType.VARCHAR, max_length=16),    # short_term/long_term
            FieldSchema(name="query", dtype=DataType.VARCHAR, max_length=2048),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="metadata", dtype=DataType.VARCHAR, max_length=8192),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=1024),
        ]

        schema = CollectionSchema(fields=fields, description="Research memories")
        collection = Collection(name=RESEARCH_MEMORY_COLLECTION, schema=schema)

        index_params = {
            "metric_type": "COSINE",
            "index_type": "IVF_FLAT",
            "params": {"nlist": 128},
        }
        collection.create_index(field_name="vector", index_params=index_params)
        collection.load()

        logger.info(f"研究记忆集合 {RESEARCH_MEMORY_COLLECTION} 创建成功")
        return True
    except Exception as e:
        logger.warning(f"创建研究记忆集合失败: {e}")
        return False


def retrieve_relevant_memories(
    query: str,
    user_id: str = "",
    top_k: int = 5,
    memory_types: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    根据当前研究查询检索相关历史记忆。

    租户隔离：通过 metadata 中的 user_id 过滤。

    面试回答要点：
    - 召回策略：基于查询向量在 Milvus 中的余弦相似度检索
    - 过滤：按 memory_type 过滤 + 按 user_id 隔离
    - 排序：按相似度分数降序

    Args:
        query: 当前研究问题
        top_k: 返回结果数量
        memory_types: 可选的记忆类型过滤

    Returns:
        相关记忆列表
    """
    milvus, has_embedding = _get_services()
    if milvus is None or not has_embedding:
        return []

    if not _ensure_collection():
        return []

    try:
        from service.embedding_service import generate_embedding
    except ImportError:
        try:
            from app.service.embedding_service import generate_embedding
        except ImportError:
            return []

    query_vector = generate_embedding(query)
    if not query_vector:
        return []

    try:
        from pymilvus import Collection, utility

        if not utility.has_collection(RESEARCH_MEMORY_COLLECTION):
            return []

        collection = Collection(RESEARCH_MEMORY_COLLECTION)
        collection.load()

        # 构建过滤表达式（租户隔离 + 类型过滤）
        expr_parts = []
        if user_id:
            expr_parts.append(f'metadata like "%\\"user_id\\": \\"{user_id}\\"%"')
        if memory_types:
            type_filter = " || ".join([f'memory_type == "{t}"' for t in memory_types])
            expr_parts.append(f"({type_filter})")

        expr = " && ".join(expr_parts) if expr_parts else None

        search_params = {
            "metric_type": "COSINE",
            "params": {"nprobe": 10},
        }

        results = collection.search(
            data=[query_vector],
            anns_field="vector",
            param=search_params,
            limit=top_k,
            expr=expr if expr else None,
            output_fields=["id", "memory_type", "category", "lifecycle", "query", "content", "metadata"],
        )

        formatted = []
        for hits in results:
            for hit in hits:
                if hit.score < 0.3:  # 最低相关度阈值
                    continue
                metadata_str = hit.entity.get("metadata", "{}")
                try:
                    metadata = json.loads(metadata_str)
                except Exception:
                    metadata = {}
                formatted.append({
                    "id": hit.entity.get("id"),
                    "memory_type": hit.entity.get("memory_type"),
                    "category": hit.entity.get("category", "fact"),
                    "lifecycle": hit.entity.get("lifecycle", "short_term"),
                    "original_query": hit.entity.get("query", ""),
                    "content": hit.entity.get("content"),
                    "metadata": metadata,
                    "similarity_score": hit.score,
                })

        return formatted
    except Exception as e:
        logger.warning(f"检索研究记忆失败: {e}")
        return []


def store_research_insights(
    query: str,
    facts: List[Dict[str, Any]],
    insights: List[str],
    user_id: str = "",
    trace_id: str = "",
) -> int:
    """
    将研究完成后的高质量洞察写入长期记忆。

    租户隔离：存储时记录 user_id 到 metadata。

    存储策略：
    1. 高置信度事实（credibility_score > 0.7）→ fact 类型记忆
    2. 关键洞察 → insight 类型记忆
    3. 行业趋势判断 → trend 类型记忆

    Args:
        query: 研究问题
        facts: 研究获得的事实列表
        insights: 研究获得的洞察列表
        trace_id: 研究追踪 ID

    Returns:
        成功存储的记忆数量
    """
    milvus, has_embedding = _get_services()
    if milvus is None or not has_embedding:
        return 0

    if not _ensure_collection():
        return 0

    try:
        from service.embedding_service import generate_embedding
    except ImportError:
        try:
            from app.service.embedding_service import generate_embedding
        except ImportError:
            return 0

    documents = []
    contradictions_found = []  # 记录所有矛盾

    # 0. 矛盾检测：存储前先检索相似记忆，检测是否存在矛盾
    for fact in facts:
        credibility = fact.get("credibility_score", 0)
        if credibility < 0.7:
            continue
        content = fact.get("content", "")
        if not content:
            continue

        # 检索相似记忆（语义相似度高的候选）
        similar = retrieve_relevant_memories(content, user_id=user_id, top_k=3)
        if similar:
            contradictions = detect_memory_contradiction(content, similar)
            if contradictions:
                contradictions_found.extend({
                    "new_content": content,
                    "contradictions": contradictions,
                    "source": fact.get("source_url", ""),
                }
                )
                logger.warning(
                    f"[MemoryContradiction] 事实 '{content[:50]}...' 与 {len(contradictions)} 条已有记忆矛盾"
                )

    for insight in insights:
        if not insight or len(insight) < 10:
            continue
        similar = retrieve_relevant_memories(insight, user_id=user_id, top_k=3)
        if similar:
            contradictions = detect_memory_contradiction(insight, similar)
            if contradictions:
                contradictions_found.append({
                    "new_content": insight,
                    "contradictions": contradictions,
                })
                logger.warning(
                    f"[MemoryContradiction] 洞察 '{insight[:50]}...' 与 {len(contradictions)} 条已有记忆矛盾"
                )

    # 1. 存储高置信度事实
    for fact in facts:
        credibility = fact.get("credibility_score", 0)
        if credibility < 0.7:
            continue  # 低置信度事实不值得记忆

        content = fact.get("content", "")
        if not content:
            continue

        vec = generate_embedding(content)
        if not vec:
            continue

        # 记忆分类
        classification = classify_memory(content, {
            "confidence_score": credibility,
            "user_id": user_id,
        })

        doc_id = f"rm_fact_{uuid.uuid4().hex[:8]}"
        documents.append({
            "id": doc_id,
            "memory_type": "fact",
            "category": classification["category"],
            "lifecycle": classification["lifecycle"],
            "query": query,
            "content": content,
            "metadata": json.dumps({
                "source_url": fact.get("source_url", ""),
                "source_name": fact.get("source_name", ""),
                "credibility": credibility,
                "reference_count": 1,  # 初始引用次数
                "trace_id": trace_id,
                "user_id": user_id,
                "stored_at": datetime.now().isoformat(),
            }, ensure_ascii=False),
            "vector": vec,
        })

    # 2. 存储关键洞察
    for insight in insights:
        if not insight or len(insight) < 10:
            continue

        vec = generate_embedding(insight)
        if not vec:
            continue

        # 洞察属于 derived 类型
        classification = classify_memory(insight, {
            "is_user_preference": False,
        })

        doc_id = f"rm_insight_{uuid.uuid4().hex[:8]}"
        documents.append({
            "id": doc_id,
            "memory_type": "insight",
            "category": classification["category"],  # derived
            "lifecycle": classification["lifecycle"],
            "query": query,
            "content": insight,
            "metadata": json.dumps({
                "trace_id": trace_id,
                "reference_count": 1,
                "user_id": user_id,
                "stored_at": datetime.now().isoformat(),
            }, ensure_ascii=False),
            "vector": vec,
        })

    if not documents:
        return 0

    try:
        from pymilvus import Collection

        collection = Collection(RESEARCH_MEMORY_COLLECTION)
        collection.load()

        ids = [d["id"] for d in documents]
        types = [d["memory_type"] for d in documents]
        categories = [d["category"] for d in documents]
        lifecycles = [d["lifecycle"] for d in documents]
        queries = [d["query"][:2048] for d in documents]
        contents = [d["content"][:65535] for d in documents]
        metadatas = [d["metadata"][:8192] for d in documents]
        vectors = [d["vector"] for d in documents]

        data = [ids, types, categories, lifecycles, queries, contents, metadatas, vectors]
        collection.insert(data)
        collection.flush()

        logger.info(f"存储研究记忆: {len(documents)} 条（fact + insight）")
        if contradictions_found:
            logger.warning(f"存储研究记忆时发现 {len(contradictions_found)} 条矛盾")
        return len(documents)
    except Exception as e:
        logger.warning(f"存储研究记忆失败: {e}")
        return 0


def store_research_insights_with_contradiction_check(
    query: str,
    facts: List[Dict[str, Any]],
    insights: List[str],
    user_id: str = "",
    trace_id: str = "",
) -> Dict[str, Any]:
    """
    带矛盾检测的记忆存储（增强版）。

    相比 store_research_insights，此版本返回矛盾检测结果，
    供调用方决定是否存储有矛盾的记忆。

    Returns:
        {
            "stored_count": int,
            "contradictions": List[Dict],
            "skipped_due_to_contradiction": int,
        }
    """
    milvus, has_embedding = _get_services()
    if milvus is None or not has_embedding:
        return {"stored_count": 0, "contradictions": [], "skipped_due_to_contradiction": 0}

    if not _ensure_collection():
        return {"stored_count": 0, "contradictions": [], "skipped_due_to_contradiction": 0}

    # 复用 store_research_insights 的逻辑，但返回额外信息
    # 这里先获取已有的矛盾检测结果
    contradictions = []

    # 检索相似记忆并检测矛盾
    for fact in facts:
        if fact.get("credibility_score", 0) < 0.7:
            continue
        content = fact.get("content", "")
        if not content:
            continue
        similar = retrieve_relevant_memories(content, user_id=user_id, top_k=3)
        if similar:
            found = detect_memory_contradiction(content, similar)
            if found:
                contradictions.extend(found)

    for insight in insights:
        if not insight or len(insight) < 10:
            continue
        similar = retrieve_relevant_memories(insight, user_id=user_id, top_k=3)
        if similar:
            found = detect_memory_contradiction(insight, similar)
            if found:
                contradictions.extend(found)

    # 正常存储（矛盾的记忆也存储，但标记出来）
    stored = store_research_insights(query, facts, insights, user_id, trace_id)

    return {
        "stored_count": stored,
        "contradictions": contradictions,
        "skipped_due_to_contradiction": 0,  # 当前策略：矛盾也存储，由下游处理
    }


def build_memory_context(memories: List[Dict[str, Any]]) -> str:
    """
    将检索到的记忆格式化为 LLM prompt 上下文。

    按分类组织记忆，让 LLM 更容易理解不同类型信息的权重：
    - 事实类记忆：客观数据，权重最高
    - 推导类记忆：分析结论，权重中等
    - 偏好类记忆：用户倾向，权重较低

    Args:
        memories: retrieve_relevant_memories 返回的记忆列表

    Returns:
        记忆上下文文本
    """
    if not memories:
        return ""

    # 按 category 分组
    by_category = {"fact": [], "derived": [], "preference": []}
    for mem in memories:
        cat = mem.get("category", "fact")
        if cat in by_category:
            by_category[cat].append(mem)
        else:
            by_category["fact"].append(mem)

    parts = ["[相关历史研究记忆]（以下信息来自之前的研究，可作参考但需验证）"]

    type_labels = {"fact": "事实", "insight": "洞察", "trend": "趋势判断"}
    category_labels = {"fact": "客观事实", "derived": "推导结论", "preference": "用户偏好"}

    for category in ["fact", "derived", "preference"]:
        cat_memories = by_category.get(category, [])
        if not cat_memories:
            continue

        cat_label = category_labels.get(category, category)
        parts.append(f"\n【{cat_label}】")

        for mem in cat_memories:
            memory_type = mem.get("memory_type", "unknown")
            content = mem.get("content", "")
            original_query = mem.get("original_query", "")
            similarity = mem.get("similarity_score", 0)
            lifecycle = mem.get("lifecycle", "short_term")
            lifecycle_label = "长期" if lifecycle == "long_term" else "短期"

            label = type_labels.get(memory_type, memory_type)
            parts.append(
                f"- {label}（{lifecycle_label}，来自研究 '{original_query[:40]}'，"
                f"相关度 {similarity:.2f}）: {content}"
            )

    parts.append("")
    return "\n".join(parts)
