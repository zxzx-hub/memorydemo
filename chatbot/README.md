# 本地记忆聊天机器人

这是一个用于连接 `memorydemo` 后端的轻量 FastAPI 聊天机器人。

```text
chatbot -> memorydemo backend API -> PostgreSQL / Redis
```

chatbot 负责：

- 调用 DeepSeek 生成回答；
- 用 SQLite 保存本地会话和短期消息历史；
- 回答前调用 `POST /v1/memory/read` 检索 Agent Memory Service 的 Context Package；
- 回答后调用 `POST /v1/memory/write` 写入 user/assistant 对话事件；
- 写入后触发一次 `type=consolidate` 的 manual Consolidate Once。

租户身份不会放进业务请求正文。chatbot 在本地开发阶段通过以下请求头连接后端的 `DevelopmentTenantResolver`：

```text
X-Development-Tenant-ID
X-Development-Principal-ID
X-Trace-ID
```

## 启动方式

本仓库要求后端 API、前端静态服务和 chatbot 都在宿主机名为 `memory` 的 conda 环境中运行。Docker 默认只跑 PostgreSQL 和 Redis。

### 1. 启动 memorydemo 依赖

```powershell
cd D:\project\memorydemo
docker compose up -d postgres redis
```

### 2. 启动 memorydemo 后端

```powershell
cd D:\project\memorydemo\backend
conda run -n memory python -m pip install -e ".[dev]"
conda run -n memory alembic upgrade head
$env:MEMORY_ENABLE_DEVELOPMENT_TENANT_RESOLVER = "true"
conda run -n memory uvicorn main:app --app-dir src --host 0.0.0.0 --port 8000 --reload
```

验证：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
```

### 3. 启动 chatbot

```powershell
cd D:\project\memorydemo\chatbot
Copy-Item .env.example .env
# 打开 .env，把 DeepSeek API Key 写入 DEEPSEEK_API_KEY。

conda run -n memory python -m pip install -r requirements.txt
conda run -n memory uvicorn main:app --host 127.0.0.1 --port 8787 --reload
```

chatbot API 地址：

```text
http://127.0.0.1:8787
```

## 关键配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `MEMORY_SERVICE_URL` | `http://127.0.0.1:8000` | memorydemo 后端地址 |
| `MEMORY_SERVICE_PORTS` | `8000` | 自动探测端口 |
| `CHATBOT_TENANT_ID` | `tenant_a` | 开发租户头 |
| `CHATBOT_USER_ID` | `user_demo` | 开发主体头 |
| `CHATBOT_AGENT_ID` | `chatbot` | 读取请求中的 Agent ID |
| `CHATBOT_AGENT_ROLE` | `assistant` | 读取请求中的 Agent 角色 |
| `CHATBOT_WORKSPACE_ID` | `chatbot_ws` | 默认写入和读取使用的 workspace；前端也可以在 `/chat` 请求中传入 `workspace_id` 覆盖 |
| `CHATBOT_DATA_DIR` | `D:\project\memorydemo\chatbot\data` | SQLite 会话库目录 |

## 测试

新建会话：

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8787/sessions" `
  -ContentType "application/json" `
  -Body '{"title":"memorydemo 测试会话"}'
```

连续聊天：

```powershell
$body = @{
  message = "你好，记住我正在测试 Agent Memory Service。"
  session_id = "demo"
  history_limit = 12
} | ConvertTo-Json -Compress

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8787/chat" `
  -ContentType "application/json; charset=utf-8" `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
```

继续同一个会话：

```powershell
$body = @{
  message = "我刚才让你记住了什么？"
  session_id = "demo"
  history_limit = 12
} | ConvertTo-Json -Compress

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8787/chat" `
  -ContentType "application/json; charset=utf-8" `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
```

查看会话列表：

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8787/sessions"
```

查看某个会话的消息：

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8787/sessions/demo/messages"
```

## 存储位置

chatbot 自己的短期会话历史保存在：

```text
D:\project\memorydemo\chatbot\data\chatbot.db
```

长期记忆和工作记忆由 `memorydemo` 后端写入 PostgreSQL 和 Redis。
