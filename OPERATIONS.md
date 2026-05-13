# 运维手册

本文档回答四个关键问题：怎么部署？怎么监控？怎么测试？怎么回滚？

---

## 一、怎么部署？

### 1.1 开发环境

```bash
# 1. 安装依赖
make install

# 2. 配置环境变量（复制 .env.example 并填写）
cp .env.example .env

# 3. 启动基础设施
docker-compose up -d postgres redis milvus etcd minio

# 4. 运行数据库迁移
make migrate

# 5. 启动开发服务器
make run
```

### 1.2 生产环境 - Docker Compose

```bash
# 1. 准备 .env 文件（必须设置 JWT_SECRET_KEY 和所有 API Keys）
cat > .env <<EOF
JWT_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
POSTGRES_PASSWORD=<强密码>
DASHSCOPE_API_KEY=<你的key>
BOCHAAI_API_KEY=<你的key>
CORS_ORIGINS=https://your-domain.com
AUTO_MIGRATE=true
LOG_LEVEL=WARNING
EOF

# 2. 一键启动所有服务
docker-compose up -d

# 3. 验证
curl http://localhost:8000/health/live   # 应返回 {"status":"ok"}
curl http://localhost:8000/health/ready  # 应返回 {"status":"ready",...}
```

### 1.3 生产环境 - Kubernetes

```bash
# 1. 创建 Secrets
kubectl create secret generic industry-info-secrets \
  --from-literal=JWT_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))") \
  --from-literal=DASHSCOPE_API_KEY=<key> \
  --from-literal=POSTGRES_PASSWORD=<password> \
  -n industry-info

# 2. 创建 ConfigMap
kubectl create configmap industry-info-config \
  --from-literal=CORS_ORIGINS=https://your-domain.com \
  --from-literal=LOG_LEVEL=WARNING \
  --from-literal=DB_POOL_SIZE=10 \
  -n industry-info

# 3. 部署
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml

# 4. 验证
kubectl rollout status deployment/industry-info-api
kubectl get pods -n industry-info
```

### 1.4 部署检查清单

- [ ] `JWT_SECRET_KEY` 已设置为强随机值
- [ ] `CORS_ORIGINS` 已设置为具体域名（非 `*`）
- [ ] 数据库密码已更换为强密码
- [ ] 所有 API Keys 已通过环境变量注入
- [ ] `AUTO_MIGRATE` 在生产环境设为 `false`（使用 `make migrate` 手动迁移）
- [ ] 日志级别设为 `WARNING`（生产环境）
- [ ] 数据库连接池参数已调优
- [ ] Kubernetes: liveness/readiness probes 已配置
- [ ] Kubernetes: 资源 limits 已设置
- [ ] Kubernetes: ingress rate limiting 已启用

---

## 二、怎么监控？

### 2.1 健康检查端点

| 端点 | 用途 | 返回 |
|------|------|------|
| `GET /health/live` | Kubernetes liveness probe | `{"status": "ok"}` |
| `GET /health/ready` | Kubernetes readiness probe | `{"status": "ready/not_ready", "checks": {...}}` |
| `GET /research/health` | 研究服务健康（LLM/搜索/向量库） | 各依赖服务的状态和延迟 |
| `GET /research/stats` | 并发队列统计 | 当前并发数、队列等待数 |

### 2.2 Prometheus 指标

`GET /research/metrics` 返回 Prometheus 格式的指标：

```
research_requests_total          # 总请求数
research_errors_total            # 总错误数
research_duration_seconds        # 研究耗时分布
research_tokens_total            # Token 消耗
research_cost_yuan_total         # 成本消耗（元）
research_concurrent_active       # 当前并发研究数
research_concurrent_queued       # 队列中等待的研究数
```

### 2.3 结构化日志

所有日志以 JSON 格式输出，包含 `trace_id` 字段用于请求追踪：

```json
{
  "timestamp": "2026-05-12T10:30:00",
  "level": "INFO",
  "logger": "app.request",
  "message": "请求完成",
  "trace_id": "abc123",
  "extra": {
    "method": "POST",
    "path": "/research/stream",
    "status": 200,
    "duration_ms": 150
  }
}
```

采集方式：
- **ELK**: Filebeat 采集 JSON 日志到 Elasticsearch
- **Loki**: Promtail 采集到 Loki，Grafana 查询
- **Datadog**: 配置 JSON 日志管道

### 2.4 Trace 追踪

每个研究任务生成完整的 Trace 记录，存储在 `data/traces/` 目录下：

```bash
# 查看特定研究的完整 Trace
curl http://localhost:8000/research/trace/{trace_id}

# 查看所有研究摘要
curl http://localhost:8000/research/traces
```

Trace 包含：
- 每个 Agent 的调用记录（模型、input/output tokens、耗时）
- 成本报告（按 Agent 分组的成本消耗）
- 执行轨迹（状态变更历史）

### 2.5 审计日志

所有写操作（POST/PUT/DELETE/PATCH）自动记录审计日志：

```json
{
  "event": "audit",
  "timestamp": "2026-05-12T10:30:00Z",
  "user_id": "authenticated",
  "client_ip": "10.0.0.1",
  "method": "POST",
  "path": "/research/stream",
  "status_code": 200,
  "duration_ms": 150
}
```

### 2.6 告警规则（建议）

在 Prometheus Alertmanager 中配置：

```yaml
groups:
  - name: research-alerts
    rules:
      - alert: HighErrorRate
        expr: rate(research_errors_total[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "研究服务错误率过高"

      - alert: HighCost
        expr: rate(research_cost_yuan_total[1h]) > 10
        for: 1h
        labels:
          severity: critical
        annotations:
          summary: "研究成本异常升高"

      - alert: ServiceDegraded
        expr: research_concurrent_queued > 10
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "研究队列积压严重"
```

---

## 三、怎么测试？

### 3.1 测试分层

| 层级 | 位置 | 覆盖率目标 | 说明 |
|------|------|-----------|------|
| 单元测试 | `backend/app/tests/test_*.py` | 核心逻辑 > 80% | 纯函数、工具类、算法 |
| 集成测试 | `backend/app/tests/test_routers.py` | 所有路由 > 100% | API 端点请求/响应 |
| 端到端测试 | 手动/脚本 | 关键路径 | 完整研究工作流 |

### 3.2 运行测试

```bash
# 运行所有测试
make test

# 运行测试并生成覆盖率报告
make test-cov

# 运行特定测试文件
cd backend && pytest app/tests/test_conflict_detector.py -v

# 运行特定测试方法
cd backend && pytest app/tests/test_conflict_detector.py::TestConflictDetector::test_numerical_conflict -v

# 只运行集成测试（不需要真实数据库）
cd backend && pytest app/tests/test_routers.py -v -k "not cancelled"
```

### 3.3 测试基础设施

`conftest.py` 提供以下共享 fixtures：

| Fixture | 用途 |
|---------|------|
| `mock_llm_response` | 模拟 LLM API 返回 |
| `mock_llm_client` | 模拟 OpenAI 客户端 |
| `mock_search_response` | 模拟搜索 API 返回 |
| `test_user_id` | 生成测试用户 ID |
| `test_session_id` | 生成测试会话 ID |
| `patch_openai_client` | 全局替换 OpenAI 客户端 |
| `patch_redis_client` | 全局替换 Redis 客户端 |
| `sample_research_query` | 样本研究查询 |

### 3.4 CI/CD 自动测试

每次 push/PR 自动运行：
1. **Lint**: Ruff 代码检查和格式化
2. **Type Check**: mypy 类型检查
3. **Test**: pytest 单元测试和集成测试
4. **Security**: Bandit 安全扫描 + Safety 依赖漏洞检查
5. **Build**: Docker 镜像构建

CI 状态查看：`.github/workflows/ci.yml`

### 3.5 新增测试指南

```python
# 新增单元测试示例
class TestYourFeature:
    def setup_method(self):
        """每个测试方法运行前的设置"""
        self.service = YourService()

    def test_happy_path(self):
        result = self.service.do_something("input")
        assert result.status == "success"
        assert len(result.data) > 0

    def test_edge_case_empty_input(self):
        with pytest.raises(ValueError):
            self.service.do_something("")

# 新增集成测试示例
class TestYourEndpoint:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.app_main import app
        return TestClient(app)

    def test_endpoint_returns_200(self, client):
        response = client.post("/your/endpoint", json={"key": "value"})
        assert response.status_code == 200
        assert "expected_field" in response.json()
```

---

## 四、怎么回滚？

### 4.1 数据库回滚（Alembic）

```bash
# 查看当前迁移状态
cd backend && alembic current

# 查看迁移历史
cd backend && alembic history

# 回滚到上一个版本
cd backend && alembic downgrade -1

# 回滚到指定版本
cd backend && alembic downgrade 0001_initial_schema

# 回滚到最初始状态（清空所有表）
cd backend && alembic downgrade base
```

### 4.2 应用回滚 - Docker Compose

```bash
# 方法 1: 回滚到上一个镜像版本
docker-compose down
docker tag industry-info-assistant:previous industry-info-assistant:latest
docker-compose up -d

# 方法 2: 使用带版本号的镜像
docker-compose down
# 修改 docker-compose.yml 中的 image 标签为上一个版本
docker-compose up -d

# 验证回滚
curl http://localhost:8000/health/live
```

### 4.3 应用回滚 - Kubernetes

```bash
# 查看部署历史
kubectl rollout history deployment/industry-info-api -n industry-info

# 查看特定版本详情
kubectl rollout history deployment/industry-info-api --revision=3 -n industry-info

# 回滚到上一个版本
kubectl rollout undo deployment/industry-info-api -n industry-info

# 回滚到指定版本
kubectl rollout undo deployment/industry-info-api --to-revision=2 -n industry-info

# 监控回滚状态
kubectl rollout status deployment/industry-info-api -n industry-info

# 暂停回滚（如果需要手动干预）
kubectl rollout pause deployment/industry-info-api -n industry-info

# 恢复回滚
kubectl rollout resume deployment/industry-info-api -n industry-info
```

### 4.4 蓝绿部署策略

```yaml
# k8s/deployment-blue.yaml (当前版本)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: industry-info-api-blue
  labels:
    app: industry-info-api
    version: blue
spec:
  replicas: 2
  # ... 其他配置与主 deployment 相同
---
# k8s/deployment-green.yaml (新版本)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: industry-info-api-green
  labels:
    app: industry-info-api
    version: green
spec:
  replicas: 2
  # ... 使用新镜像版本
```

切换流量：
```bash
# 部署新版本（green）
kubectl apply -f k8s/deployment-green.yaml

# 验证 green 版本健康
kubectl get pods -l app=industry-info-api,version=green

# 切换 service 指向 green
kubectl patch service industry-info-api-svc \
  -p '{"spec":{"selector":{"version":"green"}}}'

# 如果出现问题，切回 blue
kubectl patch service industry-info-api-svc \
  -p '{"spec":{"selector":{"version":"blue"}}}'
```

### 4.5 回滚检查清单

- [ ] 数据库迁移已回滚（`alembic current` 确认版本）
- [ ] 应用已回滚到上一个镜像版本
- [ ] 健康检查通过（`/health/live` 和 `/health/ready`）
- [ ] 关键功能验证（手动测试核心 API）
- [ ] 监控指标恢复正常（错误率、延迟、成本）
- [ ] 用户影响评估（回滚期间是否有数据损失）
- [ ] 记录回滚原因和时间线

### 4.6 数据备份

```bash
# PostgreSQL 备份
docker exec industry_postgres pg_dump -U postgres industry_assistant > backup-$(date +%Y%m%d).sql

# PostgreSQL 恢复
docker exec -i industry_postgres psql -U postgres industry_assistant < backup-20260512.sql

# Redis 备份
docker cp industry_redis:/data/dump.rdb ./redis-backup-$(date +%Y%m%d).rdb

# Milvus 备份（需要停止服务）
docker cp industry_milvus:/var/lib/milvus ./milvus-backup-$(date +%Y%m%d)/
```

---

## 附录：常见问题

### Q: 如何查看某个请求的完整链路？

每个请求自动生成 `trace_id`，在响应头的 `X-Trace-ID` 中返回。通过 trace_id 可以：
1. 在日志中搜索该 trace_id 的所有日志条目
2. 如果是研究请求，通过 `/research/trace/{trace_id}` 查看完整执行轨迹

### Q: 如何排查 LLM API 调用失败？

1. 查看 `/research/health` 端点确认 LLM 服务状态
2. 查看日志中 `level: "ERROR"` 的条目
3. 检查 `data/traces/` 目录下的 trace 文件
4. 确认 `DASHSCOPE_API_KEY` 环境变量正确设置

### Q: 研究队列积压怎么办？

1. 查看 `/research/stats` 确认队列长度
2. 检查 `/research/metrics` 中的 `research_concurrent_active` 指标
3. 临时方案：增加 `_MAX_CONCURRENT_RESEARCH` 值（在 `service.py` 中）
4. 长期方案：引入任务队列（Celery/Redis Queue）实现异步处理
