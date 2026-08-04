# Agent Memory Service - 记忆聊天前端

这是 Agent Memory Service 的独立前端应用，使用纯静态 `HTML + CSS + JavaScript`。它位于同一仓库的 `front/` 目录中，但不运行后端业务逻辑，也不会被后端 `main.py` 挂载。

主流程是：

```text
front -> chatbot -> backend API -> PostgreSQL / Redis
```

用户在页面和机器人聊天；`chatbot/` 调用大模型生成回答，并通过 `backend/` 中运行的 API 读写记忆。页面也保留了直接调用记忆 API 的调试按钮。

## 🚀 启动步骤

### 1. 启动依赖和后端服务

本项目要求后端 API、chatbot 和前端静态服务都在宿主机名为 `memory` 的 conda 环境中运行。Docker 默认只跑 PostgreSQL 和 Redis。

先启动后端依赖：

```powershell
cd D:\project\memorydemo
docker compose up -d postgres redis
```

再启动 API：

```powershell
cd D:\project\memorydemo\backend
conda run -n memory alembic upgrade head
$env:MEMORY_ENABLE_DEVELOPMENT_TENANT_RESOLVER = "true"
conda run -n memory uvicorn service.main:app --app-dir src --host 0.0.0.0 --port 8000 --reload
```

后端 API 地址默认为：

```text
http://127.0.0.1:8000
```

### 2. 启动 chatbot

```powershell
cd D:\project\memorydemo\chatbot
Copy-Item .env.example .env
# 打开 .env，把 DeepSeek API Key 写入 DEEPSEEK_API_KEY。
conda run -n memory python -m pip install -r requirements.txt
conda run -n memory uvicorn main:app --host 127.0.0.1 --port 8787 --reload
```

chatbot 地址默认为：

```text
http://127.0.0.1:8787
```

### 3. 启动前端

```powershell
cd D:\project\memorydemo\front
conda run -n memory python -m http.server 5500
```

浏览器打开：

```text
http://127.0.0.1:5500/
```

后端和 chatbot 都保留 CORS，因此此前端可以从 `5500` 调用 `8787` 和 `8000`。

## 🎯 界面功能

### 顶部栏：核心上下文

| 字段 | 作用 | 默认值 |
|------|------|--------|
| `Chatbot Base` | 聊天机器人 API 地址 | `http://127.0.0.1:8787` |
| `API Base` | 记忆后端 API 地址，主要用于调试 | `http://127.0.0.1:8000` |
| `Tenant ID` | 租户 ID（多租户隔离） | `tenant_a` |
| `User ID` | 用户 ID | `user_demo` |
| `Workspace` | 工作空间 ID | `chatbot_ws` |
| `Session / Task` | chatbot 会话 ID，也是 memory task_id | `demo` |

点击 **"检查链路"** 可以验证 chatbot、后端 API、数据库和 Redis 是否就绪。

### 左侧：聊天区

| 操作 | 按钮 | 触发接口 |
|------|------|---------|
| 发送消息 | `发送给机器人` 或 `Enter` | `POST /chat` |
| 调试 Consolidate | `调试 Consolidate` | `POST /v1/memory/write` (type=consolidate) |
| 调试读取记忆 | `调试读取记忆` | `POST /v1/memory/read` |
| GC 评估 | `GC 评估` | `POST /v1/memory/gc` (action=evaluate, dry_run=true) |
| 清空 | `清空对话` | (UI 操作) |

### 右侧：记忆面板

- **Context Package 视图**：聊天时展示 chatbot 注入给大模型的记忆上下文；调试读取时展示 Context Package 分组
- **原始响应 视图**：展示 chatbot 或后端返回的完整 JSON

### 底部：日志

折叠展开最近 5 条 API 请求（HTTP 方法 / 路径 / 状态码 / 耗时）。

## 🧪 典型使用流程

1. **打开页面** → 自动检查 chatbot + memory API 链路
2. **修改 Tenant ID** → 例如改为 `tenant_b`，观察多租户隔离效果
3. **发送几条消息** → 例如 "以后讲技术方案先讲总体架构"
4. chatbot 会自动读取记忆、调用大模型、写入本轮对话并触发 Consolidate Once
5. **继续追问** → 例如 "我刚才对技术方案表达有什么偏好？"
6. **切换 Tenant ID** → 再问同样问题，观察隔离效果
7. 必要时使用调试按钮直接读取 memory API 或触发 GC 评估

## 🔍 多租户隔离验证

把 `Tenant ID` 切到 `tenant_b`，重新发送几条消息，触发 Consolidate 和读取。

- `tenant_a` 写入的内容 `tenant_b` 完全看不到
- 后端在 `405`/`422`/`NOT_FOUND` 时统一对外表现为隔离错误码

## ⚠️ 注意

- chatbot 的 `/chat` 会调用大模型，请确保 `.env` 中有 `DEEPSEEK_API_KEY`
- chatbot 会通过 memory API 写入数据库；`gc` 当前仍可能返回未实现能力错误
- 这是 **MVP 演示工具**，不是生产前端
- 如需用于生产环境，请实现正式的 JWT 认证（替换 `DevelopmentTenantResolver`）
