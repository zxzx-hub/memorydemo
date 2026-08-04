# Agent Memory Service

这是一个可在本地运行的多租户 Agent Memory Service MVP。仓库采用“一个代码仓库、两个独立应用”的结构：

~~~text
memorydemo/
├─ backend/       FastAPI 记忆后端、领域模型、数据库迁移、测试和演示脚本
├─ chatbot/   独立 FastAPI 聊天机器人，调用 DeepSeek 和 memory API
├─ front/     独立静态演示页面，浏览器通过 HTTP 访问 chatbot/API
├─ docker-compose.yml  PostgreSQL/pgvector 和 Redis
└─ AGENTS.md  工程约束
~~~

front/ 和 chatbot/ 不挂载到 backend/src/service/main.py。后端只负责 API、数据库、Redis 和记忆领域服务；三个应用通过 HTTP 连接。

## 当前链路

~~~text
浏览器 front:5500
        │
        ├── /chat ───────────────► chatbot:8787 ──► DeepSeek
        │                                  │
        └── /v1/memory/* ───────► memory API:8000
                                           │
                               PostgreSQL:5432 + Redis:6379
~~~

聊天机器人每轮对话的处理顺序是：

1. 从 memory API 读取当前租户的 Context Package。
2. 将记忆上下文、SQLite 中的会话历史和当前问题提交给模型。
3. 将用户消息和机器人回答写入 memory API 的原始事件。
4. 触发一次 Consolidate Once，生成 Evidence、TaskCheckpoint 和 LongTermCandidate。
5. 同时把完整会话历史保存到 chatbot/data/chatbot.db。

## 当前完成度和边界

已接通：

- PostgreSQL/pgvector、Redis、Alembic 和就绪检查；
- 不可变 TenantContext、开发身份解析器和跨租户 fail-closed 校验；
- POST /v1/memory/write 的 event、consolidate、promote_candidates 联合请求；
- 原始事件幂等写入、Working Memory、增量游标和 Consolidate Once 三兄弟结果；
- POST /v1/memory/read 的 META、RESUME、EXPRESS、QUICK、NORMAL、DEEP/AUTO 路由；
- active 长期主记录的精确、向量、图谱召回和 Context Package 组装；
- 确定性 Consolidator、Mock LLM/检索计划适配器和候选治理领域服务；
- 前端聊天演示和独立 chatbot 服务。

当前明确未完成或未作为默认 HTTP 链路启用：

- POST /v1/memory/gc 的完整生命周期执行仍未实现，当前返回 501 FEATURE_NOT_AVAILABLE；
- promote_candidates 目前只写入租户绑定的 Outbox 任务并返回 queued，默认 API 进程没有启动治理 Worker；
- Candidate Governance 服务和 PostgreSQL 适配器已经存在，适合下一阶段接入 Outbox Worker/管理入口；
- 生产认证尚未接入，开发环境使用请求头解析租户身份，不应直接用于生产。

因此，本项目当前可以演示“聊天 → 记忆读取 → 原始事件写入 → Consolidate Once → 数据落库”，但不能把 GC 或自动长期治理描述为已完成的生产能力。

## 前置条件

- Windows PowerShell；
- Docker Desktop 已启动；
- 已创建 conda 环境 memory；
- memory 环境中的 Python 主版本为 3.12；
- chatbot 需要可用的 DeepSeek API Key。

确认 Python 环境：

~~~powershell
conda run -n memory python --version
~~~

所有 Python 命令都应在 memory 环境中执行。Docker 默认只运行 PostgreSQL/Redis，不替代宿主机的 memory 环境。

## 推荐启动：四个窗口

### 窗口 1：启动 PostgreSQL 和 Redis

~~~powershell
cd D:\project\memorydemo
docker compose up -d postgres redis
docker compose ps
~~~

默认连接信息：

~~~text
PostgreSQL: 127.0.0.1:5432 / database=memory / user=memory / password=memory
Redis:      127.0.0.1:6379 / database=0
~~~

### 窗口 2：启动 memory API

~~~powershell
conda activate memory
cd D:\project\memorydemo\backend

conda run -n memory python -m pip install -e ".[dev]"
conda run -n memory alembic upgrade head

$env:MEMORY_ENABLE_DEVELOPMENT_TENANT_RESOLVER = "true"
conda run -n memory uvicorn service.main:app --app-dir src --host 0.0.0.0 --port 8000 --reload
~~~

验证：

~~~powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
~~~

/health 表示进程存活；/ready 会检查 PostgreSQL 和 Redis。业务请求必须携带开发身份请求头：

~~~text
X-Development-Tenant-ID: tenant_a
X-Development-Principal-ID: user_demo
X-Trace-ID: trace_optional
~~~

这些请求头只由 DevelopmentTenantResolver 转换成只读 TenantContext，不会直接传给 Repository。生产环境应替换为正式认证解析器。

### 窗口 3：启动 chatbot

~~~powershell
conda activate memory
cd D:\project\memorydemo\chatbot

if (-not (Test-Path .env)) { Copy-Item .env.example .env }
conda run -n memory python -m pip install -r requirements.txt
~~~

编辑 D:\project\memorydemo\chatbot\.env，至少填写：

~~~text
DEEPSEEK_API_KEY=你的key
MEMORY_SERVICE_URL=http://127.0.0.1:8000
CHATBOT_TENANT_ID=tenant_a
CHATBOT_USER_ID=user_demo
CHATBOT_WORKSPACE_ID=chatbot_ws
~~~

启动并验证：

~~~powershell
conda run -n memory uvicorn main:app --host 127.0.0.1 --port 8787 --reload
Invoke-RestMethod http://127.0.0.1:8787/health
~~~

正常时应看到 ok=true 和 memory_service_ok=true。chatbot 会把租户身份作为请求头转发给 memory API，不会把可信 tenant_id 放入业务 JSON。

### 窗口 4：启动 front

~~~powershell
conda activate memory
cd D:\project\memorydemo\front
conda run -n memory python -m http.server 5500
~~~

浏览器打开 http://127.0.0.1:5500/，页面默认配置为：

~~~text
Chatbot Base: http://127.0.0.1:8787
API Base:     http://127.0.0.1:8000
Tenant ID:    tenant_a
User ID:      user_demo
Workspace:    chatbot_ws
Session/Task: demo
~~~

点击“检查链路”后即可聊天。切换 Tenant ID 为 tenant_b 可以演示相同用户/任务标识下的租户隔离。

检查五个端口：

~~~powershell
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in 5500,8000,8787,5432,6379 }
~~~

## API 概览

### 运维接口

~~~text
GET /health
GET /ready
~~~

### 统一写入口

~~~text
POST /v1/memory/write
~~~

请求体使用 type 区分：

~~~json
{
  "type": "event",
  "idempotency_key": "demo-001",
  "workspace_id": "chatbot_ws",
  "event": {
    "event_id": "evt-demo-001",
    "event_type": "chat_message",
    "role": "user",
    "content": "以后给我讲技术方案时，先讲总体架构，再展开字段和代码。",
    "source": "demo",
    "session_id": "demo",
    "task_id": "demo"
  },
  "signals": {"consolidation_reason": "explicit_remember"}
}
~~~

另有：

- {"type":"consolidate","workspace_id":"chatbot_ws","trigger":"manual"}；
- {"type":"promote_candidates","candidate_ids":["candidate_x"],"idempotency_key":"promote-001"}，当前只排队治理任务。

请求正文禁止携带可信 tenant_id。跨租户或缺少上下文的访问必须 fail closed。

### 统一读入口

~~~text
POST /v1/memory/read
~~~

支持 auto、meta、resume、express、quick、normal、deep。示例：

~~~powershell
$headers = @{
  "X-Development-Tenant-ID" = "tenant_a"
  "X-Development-Principal-ID" = "user_demo"
  "X-Trace-ID" = "trace_read_demo"
}
$body = @{
  mode = "auto"
  query = "我的技术方案表达偏好是什么"
  task_id = "demo"
  workspace_id = "chatbot_ws"
  agent_id = "demo-agent"
  agent_role = "assistant"
  top_k = 8
  token_budget = 1200
  need_evidence = $false
} | ConvertTo-Json -Compress

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/memory/read" -Headers $headers -ContentType "application/json" -Body $body
~~~

索引只返回 memory_id，最终结果会在同一租户内回读 active 长期主记录，再组装 ContextPackage。没有经过候选治理的内容不会自动出现在长期记忆结果中。

### 生命周期入口

~~~text
POST /v1/memory/gc
~~~

接口契约已保留，但当前实现返回 501 FEATURE_NOT_AVAILABLE，不要把页面上的 GC 按钮当作已完成的删除流程。

## 数据在哪里

### chatbot 本地 SQLite

~~~text
D:\project\memorydemo\chatbot\data\chatbot.db
~~~

保存聊天机器人的 sessions 和 messages，用于会话历史和向模型提供近期上下文。

### PostgreSQL

容器名通常为 memorydemo-postgres-1。主要表包括：

~~~text
memory_events              原始事件
working_memory             工作记忆持久化状态
task_memory                任务记忆
task_checkpoints           短期任务检查点
memory_evidence            证据
memory_candidates          长期候选
long_term_memory           长期主记录
long_term_memory_versions  主记录版本快照
memory_usage_stats         recalled/used 等使用统计
memory_lifecycle_state     生命周期状态
memory_index_projections   派生索引状态
memory_exact_keys          精确键索引
memory_vector_indexes      向量索引元数据
memory_graph_nodes/edges   PostgreSQL 图谱投影
memory_audit_logs          审计记录
consolidation_cursors      收束游标
outbox_jobs                候选治理/索引等后台任务
~~~

### Redis

容器名通常为 memorydemo-redis-1。Working Memory key 必须带租户前缀，例如：

~~~text
tenant:tenant_a:working-memory:chatbot_ws
~~~

查看示例：

~~~powershell
docker exec memorydemo-redis-1 redis-cli GET tenant:tenant_a:working-memory:chatbot_ws
~~~

Navicat 可以连接 PostgreSQL（也可打开 SQLite 文件，取决于 Navicat 版本）；Redis 建议使用 RedisInsight 或 redis-cli。

## 测试和质量检查

后端命令都从 backend/ 目录、在 memory 环境执行：

~~~powershell
cd D:\project\memorydemo\backend
conda run -n memory ruff format --check src/service tests scripts migrations
conda run -n memory ruff check src/service tests scripts migrations
conda run -n memory mypy src/service
conda run -n memory python -m pytest
~~~

也可以执行：

~~~powershell
conda run -n memory make check
~~~

测试覆盖 TenantContext、双租户隔离、Redis key、幂等事件、Working Memory、Consolidate Once 游标/失败回滚、候选来源和读取链路。标记为 integration 的 PostgreSQL 测试需要先启动容器并执行 alembic upgrade head。

## Docker 说明

默认：

~~~powershell
docker compose up -d postgres redis
~~~

api 服务被放在可选 container-api profile 中。如果只是临时验证 API 镜像，可以执行：

~~~powershell
docker compose --profile container-api up --build
~~~

这不是常规开发路径，因为容器内 Python 不等同于宿主机 memory conda 环境。

## 目录说明

~~~text
backend/src/service/auth/             TenantContext 和解析器
backend/src/service/domain/           枚举、领域模型、命令和结果 schema
backend/src/service/services/         write/read/consolidate/retrieval/governance/lifecycle
backend/src/service/ports/            Repository、缓存、向量、图谱、LLM、Job Port
backend/src/service/infrastructure/   PostgreSQL、Redis、pgvector、图谱和默认适配器
backend/migrations/            Alembic 迁移
backend/tests/                unit、integration、security、fixtures
backend/scripts/run_demo.py   health/ready 基础演示
chatbot/main.py           聊天 API、SQLite 会话和 memory API 客户端
front/index.html          独立浏览器演示页面
front/app.js              聊天、读取、Consolidate、GC 调试按钮
~~~

### 本地生成物与清理边界

`__pycache__/`、`.pytest_cache/` 等目录由 Python 工具自动生成，不属于源码，
可以随时删除，后续运行服务或测试时会自动重建。`.codebuddy/.tmp/` 只用于临时
检查，也不属于运行链路。后端的 ExactKey 能力由 `ports/` 和数据库 Repository
实现，不依赖单独的 `infrastructure/exact/` 目录。

`backend/docs/` 中的领域设计、API 契约、实施计划和验收文档是项目资料，不参与
运行时加载；本次清理不会移动或删除其中任何文件。

## 下一步实现建议

1. 接入 Outbox Worker，按冻结的 tenant_id 调用 CandidateGovernanceService；
2. 为候选治理增加受保护的内部入口或后台任务消费流程；
3. 完成 MemoryService.gc 的评估、降权、归档和显式删除级联；
4. 接入正式 JWT/mTLS 认证并关闭 DevelopmentTenantResolver；
5. 增加前端和 chatbot 的自动化端到端测试。

## 设计文档

- [实施计划](backend/docs/implementation-plan.md)
- [领域模型](backend/docs/domain-model.md)
- [API 契约](backend/docs/api-contract.md)
- [架构决策](backend/docs/architecture-decisions.md)
- [测试矩阵](backend/docs/test-matrix.md)
- [领域架构事实来源](backend/docs/agent-memory-design.html)
- [工程约束](AGENTS.md)
