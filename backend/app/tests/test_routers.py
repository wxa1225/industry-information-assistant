# Copyright © 2026  版权所有

"""
路由集成测试

测试 FastAPI 端点的请求/响应周期，确保 API 契约正确。
使用 TestClient 模拟 HTTP 请求，验证路由注册、参数校验和错误处理。
"""

import os
import pytest
from unittest.mock import patch, MagicMock

# 在导入 app 之前设置环境变量
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-pytest-only"
os.environ["AUTO_MIGRATE"] = "false"


class TestHealthEndpoints:
    """健康探针端点测试"""

    def test_liveness_probe(self):
        """测试 /health/live 返回 200"""
        from fastapi.testclient import TestClient
        from app.app_main import app

        with TestClient(app) as client:
            response = client.get("/health/live")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"

    def test_hello_endpoint(self):
        """测试 /hello 返回 200"""
        from fastapi.testclient import TestClient
        from app.app_main import app

        with TestClient(app) as client:
            response = client.get("/hello")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"


class TestAuthRouter:
    """认证路由测试"""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.app_main import app
        return TestClient(app)

    def test_register_missing_fields(self, client):
        """注册缺少必填字段应返回 422"""
        response = client.post("/auth/register", json={})
        assert response.status_code == 422

    def test_register_success(self, client):
        """成功注册新用户"""
        response = client.post("/auth/register", json={
            "username": "testuser_integration",
            "password": "TestPass123!",
            "email": "test@example.com",
        })
        assert response.status_code == 200
        data = response.json()
        assert "user_id" in data or "id" in data

    def test_register_duplicate_username(self, client):
        """重复用户名应返回 400"""
        # 先注册
        client.post("/auth/register", json={
            "username": "duplicate_user_test",
            "password": "TestPass123!",
        })
        # 再注册相同用户名
        response = client.post("/auth/register", json={
            "username": "duplicate_user_test",
            "password": "TestPass123!",
        })
        assert response.status_code == 400

    def test_login_success(self, client):
        """成功登录返回 access_token"""
        # 先注册
        client.post("/auth/register", json={
            "username": "login_test_user",
            "password": "TestPass123!",
        })
        # 再登录
        response = client.post("/auth/login", json={
            "username": "login_test_user",
            "password": "TestPass123!",
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_wrong_password(self, client):
        """错误密码应返回 401"""
        response = client.post("/auth/login", json={
            "username": "nonexistent_user",
            "password": "wrong_password",
        })
        assert response.status_code == 401


class TestResearchRouter:
    """研究路由测试"""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.app_main import app
        return TestClient(app)

    def test_research_stream_missing_query(self, client):
        """缺少 query 应返回 422"""
        response = client.post("/research/stream", json={})
        assert response.status_code == 422

    def test_research_stream_valid_request(self, client):
        """有效请求的格式校验"""
        response = client.post("/research/stream", json={
            "query": "测试问题",
            "version": "v1",
            "max_iterations": 2,
        })
        # v1 版本会尝试调用真实 LLM，可能超时
        # 验证路由正确注册且参数被接受（不验证响应内容）
        assert response.status_code == 200

    def test_research_health(self, client):
        """研究健康检查端点"""
        response = client.get("/research/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    def test_research_stats(self, client):
        """研究统计端点"""
        response = client.get("/research/stats")
        assert response.status_code == 200
        data = response.json()
        assert "max_concurrent" in data

    def test_research_traces(self, client):
        """研究 trace 列表端点"""
        response = client.get("/research/traces")
        assert response.status_code == 200
        data = response.json()
        assert "traces" in data


class TestSessionRouter:
    """会话路由测试"""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.app_main import app
        return TestClient(app)

    @pytest.fixture
    def auth_token(self, client):
        """获取认证 token"""
        client.post("/auth/register", json={
            "username": "session_test_user",
            "password": "TestPass123!",
        })
        resp = client.post("/auth/login", json={
            "username": "session_test_user",
            "password": "TestPass123!",
        })
        return resp.json()["access_token"]

    def test_create_session(self, client, auth_token):
        """创建新会话"""
        response = client.post(
            "/sessions",
            json={"title": "Test Session"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Test Session"

    def test_list_sessions(self, client, auth_token):
        """列出会话"""
        response = client.get(
            "/sessions",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data

    def test_unauthorized_access(self, client):
        """未认证访问应返回 401"""
        response = client.get("/sessions")
        assert response.status_code == 401


class TestNewsRouter:
    """新闻路由测试"""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.app_main import app
        return TestClient(app)

    def test_news_list(self, client):
        """新闻列表端点"""
        response = client.get("/news/list")
        assert response.status_code == 200
        data = response.json()
        assert "news" in data

    def test_news_list_with_pagination(self, client):
        """新闻列表分页参数"""
        response = client.get("/news/list?page=1&page_size=10")
        assert response.status_code == 200

    def test_bidding_list(self, client):
        """招标列表端点"""
        response = client.get("/news/bidding/list")
        assert response.status_code == 200
        data = response.json()
        assert "bidding" in data


class TestDatabaseRouter:
    """数据库路由测试"""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.app_main import app
        return TestClient(app)

    def test_sql_execution_restricted(self, client):
        """SQL 执行应拒绝非 SELECT 语句"""
        response = client.post("/database/execute", json={
            "sql": "DELETE FROM users WHERE 1=1"
        })
        assert response.status_code == 400
