# Agent Memory Service - 独立测试前端

这是 Agent Memory Service 的独立测试前端应用，使用纯静态 `HTML + CSS + JavaScript`。它位于同一仓库的 `front/` 目录中，但不运行后端业务逻辑，也不会被后端 `main.py` 挂载；它只通过 `API Base` 调用 `api/` 里的 FastAPI 接口。

## 🚀 启动步骤

### 1. 启动依赖和后端服务

本项目要求后端 API 和前端静态服务都在宿主机名为 `memory` 的 conda 环境中运行。Docker 默认只跑 PostgreSQL 和 Redis。

先启动后端依赖：

```powershell
cd D:\project\memorydemo
docker compose up -d postgres redis
```

再启动 API：

```powershell
cd D:\project\memorydemo\api
conda run -n memory alembic upgrade head
$env:MEMORY_ENABLE_DEVELOPMENT_TENANT_RESOLVER = "true"
conda run -n memory uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

后端 API 地址默认为：

```text
http://127.0.0.1:8000
```

### 2. 启动前端

```powershell
cd D:\project\memorydemo\front
conda run -n memory python -m http.server 5500
```

浏览器打开：

```text
http://127.0.0.1:5500/
```

后端保留 CORS，因此此前端可以从 `5500` 调用 `8000` 的 API。

## 🎯 界面功能

### 顶部栏：核心上下文

| 字段 | 作用 | 默认值 |
|------|------|--------|
| `API Base` | 后端 API 地址 | `http://127.0.0.1:8000` |
| `Tenant ID` | 租户 ID（多租户隔离） | `tenant_a` |
| `User ID` | 用户 ID | `user_demo` |
| `Workspace` | 工作空间 ID | `ws_001` |
| `Task` | 任务 ID | `task_001` |

点击 **"检查后端"** 可以验证后端是否启动。

### 左侧：聊天区

| 操作 | 按钮 | 触发接口 |
|------|------|---------|
| 发送消息 | `发送` 或 `Enter` | `POST /v1/memory/write` (type=event) |
| 触发 Consolidate Once | `Consolidate Once` | `POST /v1/memory/write` (type=consolidate) |
| 读取记忆 | `读取记忆` | `POST /v1/memory/read` |
| GC 评估 | `GC 评估` | `POST /v1/memory/gc` (action=evaluate, dry_run=true) |
| 清空 | `清空对话` | (UI 操作) |

### 右侧：记忆面板

- **Context Package 视图**：以卡片形式展示 `facts / preferences / checkpoints / entities`
- **原始响应 视图**：展示后端返回的完整 JSON

### 底部：日志

折叠展开最近 5 条 API 请求（HTTP 方法 / 路径 / 状态码 / 耗时）。

## 🧪 典型使用流程

1. **打开页面** → 自动检查后端连接
2. **修改 Tenant ID** → 例如改为 `tenant_b`，观察多租户隔离效果
3. **发送几条消息** → 例如 "我偏好简洁的回复"、"我住在北京"
4. **点击 Consolidate Once** → 把事件窗口收束成 Evidence / TaskCheckpoint / Candidates
5. **点击 读取记忆** → 自动用刚才输入框的文字查（空时用 "最近的对话"）
6. **切换 Tenant ID** → 再读取，看到空结果（验证隔离）
7. **点击 GC 评估** → 干跑一次生命周期评估

## 🔍 多租户隔离验证

把 `Tenant ID` 切到 `tenant_b`，重新发送几条消息，触发 Consolidate 和读取。

- `tenant_a` 写入的内容 `tenant_b` 完全看不到
- 后端在 `405`/`422`/`NOT_FOUND` 时统一对外表现为隔离错误码

## ⚠️ 注意

- 后端 `write` 会写入数据库；`gc` 当前仍可能返回未实现能力错误
- 这是 **MVP 测试工具**，不是生产前端
- 如需用于生产环境，请实现正式的 JWT 认证（替换 `DevelopmentTenantResolver`）
