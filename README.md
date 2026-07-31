# Agent Memory Service

多租户 Agent Memory Service MVP。当前仓库交付实施计划、领域/接口契约和可运行基础骨架；完整记忆业务、业务表与迁移将在后续阶段实现。

## 当前能力

- FastAPI 应用工厂
- `GET /health` 存活检查
- `GET /ready` PostgreSQL 与 Redis 就绪检查
- `POST /v1/memory/write`、`read`、`gc` 严格请求契约
- 只读 TenantContext 与 fail-closed 依赖
- async SQLAlchemy、Redis、Alembic、Port/Adapter 骨架
- Docker Compose 本地 PostgreSQL 16 + pgvector + Redis

业务端点尚未绑定实现；缺少认证上下文时返回 401，绑定可信上下文但未绑定服务时返回 501。它们不会返回伪造的成功结果。

本地开发可显式启用 `DevelopmentTenantResolver`：

```text
MEMORY_ENABLE_DEVELOPMENT_TENANT_RESOLVER=true
X-Development-Tenant-ID: tenant_a
X-Development-Principal-ID: developer
X-Trace-ID: trace_optional
```

这些请求头只由开发解析器转换成不可变 `TenantContext`，不会直接传给
Service 或 Repository。生产环境不得启用该解析器。

## 本地环境

项目只在名为 `memory` 的 conda 环境中运行，Python 必须为 3.12。

```powershell
conda run -n memory python --version
conda run -n memory python -m pip install -e ".[dev]"
```

复制 `.env.example` 为 `.env` 后可覆盖 `MEMORY_*` 配置。不要提交 `.env`。

## 运行应用

先启动依赖：

```powershell
docker compose up -d postgres redis
```

再启动 API：

```powershell
conda run -n memory alembic upgrade head
conda run -n memory uvicorn app.main:app --host 0.0.0.0 --port 8000
```

验证：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
conda run -n memory python scripts/run_demo.py
```

也可完整使用容器：

```powershell
docker compose up --build
```

## 开发检查

```powershell
conda run -n memory ruff format --check app tests scripts migrations
conda run -n memory ruff check app tests scripts migrations
conda run -n memory mypy app
conda run -n memory python -m pytest
```

## 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `MEMORY_APP_NAME` | `agent-memory-service` | 服务名 |
| `MEMORY_ENVIRONMENT` | `development` | 运行环境 |
| `MEMORY_LOG_LEVEL` | `INFO` | 日志等级 |
| `MEMORY_HOST` | `0.0.0.0` | 服务监听地址 |
| `MEMORY_PORT` | `8000` | 服务端口 |
| `MEMORY_DATABASE_URL` | 本地 asyncpg URL | PostgreSQL 连接 |
| `MEMORY_REDIS_URL` | `redis://localhost:6379/0` | Redis 连接 |
| `MEMORY_READINESS_TIMEOUT_SECONDS` | `2` | 单依赖就绪超时 |

## 架构文档

- [详细实施计划](docs/implementation-plan.md)
- [领域模型](docs/domain-model.md)
- [API 契约](docs/api-contract.md)
- [架构决策](docs/architecture-decisions.md)
- [测试矩阵](docs/test-matrix.md)

领域架构事实来源是 `docs/agent-memory-design.html`，工程硬约束见 `AGENTS.md`。
