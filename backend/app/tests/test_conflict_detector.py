"""冲突检测器测试"""
import pytest

from service.conflict_detector.detector import ConflictDetector, ConflictPair


class TestConflictDetector:
    """冲突检测逻辑测试"""

    def setup_method(self):
        self.detector = ConflictDetector()

    def test_no_conflicts_with_empty_list(self):
        """空列表不应有冲突"""
        results = self.detector.detect([])
        assert len(results) == 0

    def test_no_conflicts_with_single_fact(self):
        """单个事实不应有冲突"""
        facts = [{
            "id": "f1",
            "content": "2024年中国AI市场规模达1000亿元",
        }]
        results = self.detector.detect(facts)
        assert len(results) == 0

    def test_detect_numerical_conflict(self):
        """检测到数值矛盾"""
        facts = [
            {
                "id": "f1",
                "content": "2024年中国AI市场规模达1000亿元",
                "source_type": "official",
            },
            {
                "id": "f2",
                "content": "2024年中国AI市场规模达500亿元",
                "source_type": "news",
            },
        ]
        results = self.detector.detect(facts)
        # 同一主题的不同数值应被检测
        conflict_pairs = [r for r in results if r.conflict_type == "numerical"]
        assert len(conflict_pairs) >= 1

    def test_no_conflict_same_numbers(self):
        """相同数值的两个事实不应冲突"""
        facts = [
            {"id": "f1", "content": "市场规模1000亿元"},
            {"id": "f2", "content": "市场规模1000亿元"},
        ]
        results = self.detector.detect(facts)
        assert len(results) == 0

    def test_no_conflict_different_topics(self):
        """不同主题的事实不应冲突"""
        facts = [
            {"id": "f1", "content": "AI市场规模1000亿元"},
            {"id": "f2", "content": "新能源汽车销量500万辆"},
        ]
        results = self.detector.detect(facts)
        # 不同主题不应判为冲突
        for r in results:
            assert r.conflict_type != "numerical" or "不同主题" in r.description

    def test_conflict_pair_to_dict(self):
        """ConflictPair 序列化"""
        fact_a = {"id": "f1", "content": "A"}
        fact_b = {"id": "f2", "content": "B"}
        pair = ConflictPair(
            fact_a=fact_a, fact_b=fact_b,
            conflict_type="numerical", field_name="size",
            value_a="100", value_b="200",
            description="test"
        )
        d = pair.to_dict()
        assert d["fact_a_id"] == "f1"
        assert d["fact_b_id"] == "f2"
        assert d["conflict_type"] == "numerical"
        assert d["severity"] == "major"
        assert d["resolved"] is False

    def test_temporal_conflict(self):
        """时间矛盾检测"""
        facts = [
            {"id": "f1", "content": "2024年市场规模1000亿，2025年预测2000亿"},
            {"id": "f2", "content": "2024年市场规模1000亿，2025年预测800亿"},
        ]
        results = self.detector.detect(facts)
        temporal = [r for r in results if r.conflict_type == "temporal"]
        assert len(temporal) >= 1

    def test_conflict_severity(self):
        """冲突严重程度分级"""
        fact_a = {"id": "f1", "content": "A"}
        fact_b = {"id": "f2", "content": "B"}
        pair = ConflictPair(
            fact_a=fact_a, fact_b=fact_b,
            conflict_type="numerical", field_name="size",
            value_a="100", value_b="200", description="test"
        )
        assert pair.severity in ("critical", "major", "minor")
        pair.resolved = True
        pair.resolution = "已验证f1正确"
        assert pair.resolved is True
