# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有

"""
Pytest 配置与共享 Fixtures

提供：
- 测试数据库连接（自动创建和清理）
- 模拟 LLM 客户端（避免真实 API 调用）
- FastAPI TestClient
- 共享的测试用户和会话
"""

import os
import sys
import uuid
import pytest
from typing import Generator
from unittest.mock import MagicMock, patch

# 确保 backend/app 在 Python 路径中，使 `from service.xxx` 导入可用
APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

# 设置测试环境变量
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-pytest-only"
os.environ["POSTGRES_HOST"] = os.getenv("TEST_POSTGRES_HOST", "localhost")
os.environ["POSTGRES_PORT"] = os.getenv("TEST_POSTGRES_PORT", "5432")
os.environ["POSTGRES_USER"] = os.getenv("TEST_POSTGRES_USER", "postgres")
os.environ["POSTGRES_PASSWORD"] = os.getenv("TEST_POSTGRES_PASSWORD", "postgres123")
os.environ["POSTGRES_DB"] = os.getenv("TEST_POSTGRES_DB", "industry_assistant_test")
os.environ["REDIS_HOST"] = os.getenv("TEST_REDIS_HOST", "localhost")
os.environ["REDIS_PORT"] = os.getenv("TEST_REDIS_PORT", "6379")
os.environ["AUTO_MIGRATE"] = "true"


@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """会话级别的测试环境设置"""
    yield


@pytest.fixture
def mock_llm_response():
    """模拟 LLM API 返回"""
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content='{"status": "success", "data": "test"}'
            ),
            finish_reason="stop"
        )
    ]
    mock_response.usage = MagicMock(
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150
    )
    return mock_response


@pytest.fixture
def mock_llm_client(mock_llm_response):
    """模拟 OpenAI 客户端"""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_llm_response
    return mock_client


@pytest.fixture
def mock_search_response():
    """模拟搜索 API 返回"""
    return {
        "results": [
            {
                "title": "Test Article 1",
                "link": "https://example.com/1",
                "snippet": "This is a test search result about industry data.",
                "published_date": "2026-01-15",
            },
            {
                "title": "Test Article 2",
                "link": "https://example.com/2",
                "snippet": "Another test result with market analysis data.",
                "published_date": "2026-02-20",
            },
        ]
    }


@pytest.fixture
def test_user_id():
    """生成测试用户 ID"""
    return str(uuid.uuid4())


@pytest.fixture
def test_session_id():
    """生成测试会话 ID"""
    return str(uuid.uuid4())


@pytest.fixture
def test_trace_id():
    """生成测试 trace ID"""
    return str(uuid.uuid4())


@pytest.fixture
def sample_research_query():
    """样本研究查询"""
    return "中国新能源汽车市场的发展趋势和竞争格局是什么？"


@pytest.fixture
def sample_industry_data():
    """样本行业数据"""
    return {
        "industry": "新能源汽车",
        "metrics": {
            "market_size": "5000亿元",
            "growth_rate": "25%",
            "companies": ["比亚迪", "特斯拉", "蔚来", "小鹏"],
        }
    }


@pytest.fixture
def patch_openai_client(mock_llm_client):
    """全局补丁：替换 OpenAI 客户端"""
    with patch("openai.OpenAI", return_value=mock_llm_client):
        yield mock_llm_client


@pytest.fixture
def patch_httpx_client():
    """全局补丁：替换 httpx 客户端（用于搜索 API 模拟）"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "results": [
            {"title": "Test", "link": "https://example.com", "snippet": "Test snippet"}
        ]
    }

    mock_client = MagicMock()
    mock_client.post.return_value = mock_response
    mock_client.get.return_value = mock_response

    with patch("httpx.Client", return_value=mock_client):
        yield mock_client


@pytest.fixture
def patch_redis_client():
    """全局补丁：替换 Redis 客户端"""
    mock_redis = MagicMock()
    mock_redis.get.return_value = None
    mock_redis.set.return_value = True
    mock_redis.delete.return_value = True
    mock_redis.ping.return_value = True
    mock_redis.exists.return_value = False

    with patch("redis.Redis", return_value=mock_redis):
        yield mock_redis
