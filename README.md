# Agent Memory Service

多租户 Agent Memory Service MVP。当前仓库采用一个代码仓库、两个独立应用的组织方式：

```text
memorydemo/
  api/     FastAPI 后端服务、数据库迁移、测试和演示脚本
  front/   独立测试前端，浏览器通过 HTTP 调用后端 API
  chatbot/ 独立聊天机器人，通过 HTTP 调用后端记忆 API
```

`front/` 和 `chatbot/` 都不挂载到 `api/app/main.py`。后端只负责 API、数据库、缓存和领域服务；前端和聊天机器人独立启动，只通过 HTTP 访问后端。

## 当前能力

- FastAPI 应用工厂
- `GET /health` 存活检查
- `GET /ready` PostgreSQL 与 Redis 就绪检查
- `POST /v1/memory/write`、`read`、`gc` 三个业务入口
- 只读 TenantContext 与 fail-closed 依赖
- async SQLAlchemy、Redis、Alembic、Port/Adapter
- Docker Compose 本地 PostgreSQL 16 + pgvector + Redis

`write` 和 `read` 已绑定默认服务；`gc` 仍未完整实现。缺少认证上下文时返回 401；未实现能力返回 501。它们不会返回伪造的成功结果。

本地开发可显式启用 `DevelopmentTenantResolver`：

```text
MEMORY_ENABLE_DEVELOPMENT_TENANT_RESOLVER=true
X-Development-Tenant-ID: tenant_a
X-Development-Principal-ID: developer
X-Trace-ID: trace_optional
```

这些请求头只由开发解析器转换成不可变 `TenantContext`，不会直接传给 Service 或 Repository。生产环境不得启用该解析器。

## 本地环境

项目 Python 部分只在名为 `memory` 的 conda 环境中运行，Python 必须为 3.12。

```powershell
cd D:\project\memorydemo\api
conda run -n memory python --version
conda run -n memory python -m pip install -e ".[dev]"
```

根目录的 `.env.example` 可复制为 `.env` 后用于记录本地配置。不要提交 `.env`。

## 推荐启动方式：Docker 跑依赖，conda 跑后端、chatbot 和前端

本项目要求后端 API、chatbot 和前端静态服务都在宿主机名为 `memory` 的 conda 环境中运行。Docker 默认只用于 PostgreSQL 和 Redis。

先在仓库根目录启动依赖：

```powershell
cd D:\project\memorydemo
docker compose up -d postgres redis
```

然后在 `api/` 目录迁移数据库并启动 API：

```powershell
cd D:\project\memorydemo\api
conda run -n memory alembic upgrade head
$env:MEMORY_ENABLE_DEVELOPMENT_TENANT_RESOLVER = "true"
conda run -n memory uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

验证：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
```

演示脚本：

```powershell
cd D:\project\memorydemo\api
conda run -n memory python scripts/run_demo.py
```

如果只是临时验证容器镜像，可以显式启用 `container-api` profile：

```powershell
cd D:\project\memorydemo
docker compose --profile container-api up --build
```

注意：API 容器运行在容器内 Python 环境中，不等同于宿主机 `memory` conda 环境；常规开发和验收仍以 `conda run -n memory ...` 为准。

## 启动前端

前端测试控制台位于：

```text
D:\project\memorydemo\front
```

启动静态服务：

```powershell
cd D:\project\memorydemo\front
conda run -n memory python -m http.server 5500
```

浏览器访问：

```text
http://127.0.0.1:5500/
```

前端页面中的 `API Base` 保持为：

```text
http://127.0.0.1:8000
```

前端页面中的 `Chatbot Base` 保持为：

```text
http://127.0.0.1:8787
```

后端保留 CORS，用于允许独立前端访问 `/v1/memory/*` API。

## 启动聊天机器人

聊天机器人位于：

```text
D:\project\memorydemo\chatbot
```

启动前请先按上文启动 PostgreSQL、Redis 和后端 API。然后：

```powershell
cd D:\project\memorydemo\chatbot
Copy-Item .env.example .env
# 打开 .env，把 DeepSeek API Key 写入 DEEPSEEK_API_KEY。
conda run -n memory python -m pip install -r requirements.txt
conda run -n memory uvicorn main:app --host 127.0.0.1 --port 8787 --reload
```

chatbot 默认连接：

```text
http://127.0.0.1:8000
```

它通过开发请求头向后端提供租户上下文，不会把 `tenant_id` 放入业务请求正文。

## 开发检查

后端检查在 `api/` 目录执行：

```powershell
cd D:\project\memorydemo\api
conda run -n memory ruff format --check app tests scripts migrations
conda run -n memory ruff check app tests scripts migrations
conda run -n memory mypy app
conda run -n memory python -m pytest
```

也可以使用 `api/Makefile`：

```powershell
cd D:\project\memorydemo\api
make check
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

- [详细实施计划](api/docs/implementation-plan.md)
- [领域模型](api/docs/domain-model.md)
- [API 契约](api/docs/api-contract.md)
- [架构决策](api/docs/architecture-decisions.md)
- [测试矩阵](api/docs/test-matrix.md)

领域架构事实来源是 `api/docs/agent-memory-design.html`，工程硬约束见 `AGENTS.md`。
