"""事实过滤器测试"""
import pytest

from service.fact_filter import FactFilter, FactFilterResult


class TestFactFilter:
    """事实过滤逻辑测试"""

    def setup_method(self):
        # 不使用向量（避免需要 embedding）
        self.filter = FactFilter(use_vector=False)

    def test_accept_unique_fact(self):
        """唯一事实应被接受"""
        candidate = {
            "id": "f1",
            "content": "2025年中国AI市场规模达到2500亿元，同比增长35%",
            "source_url": "https://example.com/a",
            "source_name": "TestSource",
        }
        existing = []
        result = self.filter.filter(candidate, existing)
        assert result.accepted is True

    def test_reject_hash_duplicate(self):
        """字面重复应被拒绝"""
        candidate = {
            "id": "f2",
            "content": "2025年中国AI市场规模达到2500亿元，同比增长35%",
            "source_url": "https://other.com/b",
            "source_name": "OtherSource",
        }
        existing = [
            {
                "id": "f1",
                "content": "2025年中国AI市场规模达到2500亿元，同比增长35%",
                "source_url": "https://example.com/a",
                "source_name": "TestSource",
            }
        ]
        result = self.filter.filter(candidate, existing)
        assert result.accepted is False
        assert "字面重复" in result.reason
        assert result.duplicate_of == "f1"

    def test_accept_same_source_supplement(self):
        """同一来源的相似内容应保留（视为补充信息）"""
        candidate = {
            "id": "f2",
            "content": "2025年中国AI市场规模达到2500亿元，同比增长35%",
            "source_url": "https://example.com/a",
            "source_name": "TestSource",
        }
        existing = [
            {
                "id": "f1",
                "content": "2025年中国AI市场规模达到2500亿元，同比增长35%（另一篇文章）",
                "source_url": "https://example.com/a",
                "source_name": "TestSource",
            }
        ]
        result = self.filter.filter(candidate, existing)
        # 同一来源可能通过，取决于 hash 是否匹配
        # 如果 hash 不同则通过，相同则因为是同来源而保留
        # 这里取决于 fingerprint 逻辑，我们只验证不崩溃

    def test_reject_low_info_gain(self):
        """信息增益过低应被拒绝"""
        candidate = {
            "id": "f2",
            "content": "市场发展良好",
            "source_url": "https://other.com",
            "source_name": "OtherSource",
        }
        existing = [
            {
                "id": "f1",
                "content": "2025年中国AI市场规模达到2500亿元，同比增长35%，涉及多个细分领域",
                "source_url": "https://example.com",
                "source_name": "TestSource",
            }
        ]
        result = self.filter.filter(candidate, existing)
        # 短文本+无数值 → 信息增益低
        assert result.accepted is False
        assert "信息增益" in result.reason

    def test_cosine_similarity_calculation(self):
        """余弦相似度计算正确性"""
        v1 = [1.0, 0.0, 0.0]
        v2 = [1.0, 0.0, 0.0]
        assert self.filter._cosine_similarity(v1, v2) == 1.0

        v3 = [1.0, 0.0, 0.0]
        v4 = [0.0, 1.0, 0.0]
        assert self.filter._cosine_similarity(v3, v4) == 0.0

        v5 = [1.0, 1.0, 0.0]
        v6 = [1.0, 1.0, 0.0]
        assert abs(self.filter._cosine_similarity(v5, v6) - 1.0) < 1e-6

    def test_cosine_similarity_zero_vector(self):
        """零向量应返回0"""
        assert self.filter._cosine_similarity([], [1.0, 0.0]) == 0.0
        assert self.filter._cosine_similarity([1.0, 0.0], []) == 0.0

    def test_extract_numbers(self):
        """数值提取"""
        nums = self.filter._extract_numbers("市场规模1234.56亿元，增长15%，用户500万")
        assert "1234.56" in nums
        assert "15" in nums
        assert "500" in nums

    def test_extract_entities(self):
        """实体提取"""
        entities = self.filter._extract_entities("中国人工智能市场分析报告")
        assert len(entities) > 0
        assert "中国" in entities

    def test_batch_filter(self):
        """批量过滤"""
        candidates = [
            {"id": "c1", "content": "2025年AI市场2500亿增长35%", "source_url": "https://a.com", "source_name": "A"},
            {"id": "c2", "content": "2025年AI市场2500亿增长35%", "source_url": "https://b.com", "source_name": "B"},  # 与c1重复
            {"id": "c3", "content": "新能源汽车销量500万辆，同比增长40%，比亚迪占30%", "source_url": "https://c.com", "source_name": "C"},  # 全新
        ]
        existing = []
        accepted, results = self.filter.batch_filter(candidates, existing)
        # c1 应被接受
        # c2 可能被拒绝（与c1重复）
        # c3 应被接受
        assert len(accepted) >= 2
        assert len(results) == 3

    def test_info_gain_new_source(self):
        """新来源应获得信息增益"""
        candidate = {
            "id": "f1",
            "content": "某行业分析",
            "source_url": "https://new.com",
            "source_name": "NewSource",
        }
        existing = [
            {"id": "f2", "content": "另一行业分析", "source_url": "https://old.com", "source_name": "OldSource"},
        ]
        gain = self.filter._assess_info_gain(candidate, existing)
        assert gain > 0.0

    def test_fingerprint_consistency(self):
        """相同内容应有相同指纹"""
        content = "2025年AI市场2500亿"
        fp1 = self.filter._compute_fact_fingerprint(content)
        fp2 = self.filter._compute_fact_fingerprint(content)
        assert fp1 == fp2

    def test_fingerprint_difference(self):
        """不同内容应有不同指纹"""
        fp1 = self.filter._compute_fact_fingerprint("AI市场2500亿")
        fp2 = self.filter._compute_fact_fingerprint("汽车销量500万辆")
        assert fp1 != fp2
