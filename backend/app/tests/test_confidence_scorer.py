"""置信度评分器测试"""
import pytest
from datetime import datetime, timedelta

from service.conflict_detector.scorer import ConfidenceScorer, WEIGHTS


class TestConfidenceScorer:
    """置信度评分逻辑测试"""

    def setup_method(self):
        self.scorer = ConfidenceScorer()

    def test_official_source_high_score(self):
        """官方来源应获得高置信度"""
        fact = {
            "id": "f1",
            "content": "2025年中国AI市场规模达2000亿元",
            "source_type": "official",
            "source_url": "https://www.gov.cn/ai-report",
        }
        result = self.scorer.score(fact)
        assert result.source_score > 0.8

    def test_self_media_low_score(self):
        """自媒体应获得低置信度"""
        fact = {
            "id": "f2",
            "content": "听说AI市场很大",
            "source_type": "self_media",
            "source_url": "https://blog.example.com",
        }
        result = self.scorer.score(fact)
        assert result.source_score < 0.5

    def test_gov_domain_bonus(self):
        """政府域名应获得加分"""
        fact_gov = {
            "id": "f1",
            "content": "报告内容",
            "source_type": "news",
            "source_url": "https://www.stats.gov.cn/report",
        }
        fact_com = {
            "id": "f2",
            "content": "报告内容",
            "source_type": "news",
            "source_url": "https://www.example.com",
        }
        r_gov = self.scorer.score(fact_gov)
        r_com = self.scorer.score(fact_com)
        assert r_gov.source_score > r_com.source_score

    def test_corroborated_validation(self):
        """被交叉验证佐证应获得高验证分"""
        fact = {
            "id": "f1",
            "content": "2025年市场规模2000亿",
            "source_type": "news",
        }
        validation = {"status": "corroborated"}
        result = self.scorer.score(fact, validation_result=validation)
        assert result.validation_score == 0.9

    def test_contradicted_validation(self):
        """被矛盾应获得低验证分"""
        fact = {"id": "f1", "content": "数据", "source_type": "news"}
        validation = {"status": "contradicted"}
        result = self.scorer.score(fact, validation_result=validation)
        assert result.validation_score == 0.2

    def test_recent_data_high_recency(self):
        """近期数据应获得高时效分"""
        current_year = datetime.now().year
        fact = {
            "id": "f1",
            "content": f"{current_year}年最新数据：市场规模增长",
            "source_type": "news",
        }
        result = self.scorer.score(fact)
        assert result.recency_score >= 0.9

    def test_old_data_low_recency(self):
        """陈旧数据应获得低时效分"""
        fact = {
            "id": "f1",
            "content": "2018年市场规模数据",
            "source_type": "news",
        }
        result = self.scorer.score(fact)
        assert result.recency_score < 0.6

    def test_specific_content_score(self):
        """包含具体数值和来源的内容应获得高具体分"""
        fact = {
            "id": "f1",
            "content": "2024年中国AI芯片市场规模达到1,234.56亿元，同比增长45.6%，预计2025年将突破1,500亿元",
            "source_type": "report",
            "source_url": "https://example.com/report",
        }
        result = self.scorer.score(fact)
        assert result.specificity_score > 0.8

    def test_conflict_penalty(self):
        """未解决冲突应降低置信度"""
        fact = {"id": "f1", "content": "数据A", "source_type": "news"}
        from service.conflict_detector.detector import ConflictPair
        conflict = ConflictPair(
            fact_a=fact, fact_b={"id": "f2", "content": "数据B"},
            conflict_type="numerical", field_name="size",
            value_a="100", value_b="200", description="冲突",
            severity="major", resolved=False
        )
        result_no_conflict = self.scorer.score(fact)
        result_with_conflict = self.scorer.score(fact, conflict_pair=conflict)
        assert result_with_conflict.overall_score < result_no_conflict.overall_score

    def test_score_all_batch(self):
        """批量评分"""
        facts = [
            {"id": "f1", "content": "2025年AI市场数据", "source_type": "official", "source_url": "https://www.gov.cn"},
            {"id": "f2", "content": "市场很大", "source_type": "self_media", "source_url": "https://blog.com"},
            {"id": "f3", "content": "2024年数据详述", "source_type": "news", "source_url": "https://news.edu.cn"},
        ]
        results = self.scorer.score_all(facts)
        assert len(results) == 3
        assert results["f1"].overall_score > results["f2"].overall_score

    def test_score_clamped_to_0_1(self):
        """分数应在0-1之间"""
        fact = {"id": "f1", "content": "测试", "source_type": "official"}
        result = self.scorer.score(fact)
        assert 0.0 <= result.overall_score <= 1.0

    def test_to_dict_rounds(self):
        """to_dict 应正确舍入"""
        fact = {"id": "f1", "content": "2025年测试数据123.456", "source_type": "news", "source_url": "https://example.com"}
        result = self.scorer.score(fact)
        d = result.to_dict()
        assert d["fact_id"] == "f1"
        assert isinstance(d["overall_score"], float)
        assert len(str(d["overall_score"]).split(".")[-1]) <= 3
