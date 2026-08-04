# MemoryBear 本地部署与启动总结

## 1. 项目架构

MemoryBear 是前后端分离项目：

- 后端：`D:\project\MemoryBear-main\api`
  - Python 3.12
  - FastAPI + Uvicorn
  - PostgreSQL、Redis、Neo4j、Elasticsearch
  - Celery 用于异步任务
- 前端：`D:\project\MemoryBear-main\web`
  - React 18 + TypeScript + Vite
  - 默认端口：`5175`
- 前端通过 `/api` 代理访问本机 `8001` 端口的后端。

调用关系：

```text
浏览器 localhost:5175
    → React/Vite 前端
    → /api 代理
    → FastAPI 127.0.0.1:8001
    → PostgreSQL / Redis / Neo4j / Elasticsearch
```

## 2. 独立运行环境

本项目使用独立 Conda 环境：

```powershell
conda activate memorybear
python --version
```

当前环境解释器：

```text
C:\Users\L0836\.conda\envs\memorybear\python.exe
Python 3.12.13
```

Python 包安装在 Conda 环境中，不取决于执行命令时所在的目录。但运行项目命令时应进入 `api`，以便正确读取 `.env`、`alembic.ini` 等配置。

## 3. Docker 基础服务

MemoryBear 使用独立 Compose 项目，不修改、不停止、不复用 `memorydemo`。

配置文件：

```text
D:\project\MemoryBear-main\docker-compose.memorybear.yml
```

启动：

```powershell
cd D:\project\MemoryBear-main
docker compose -f docker-compose.memorybear.yml up -d
```

查看状态：

```powershell
docker compose -f docker-compose.memorybear.yml ps
```

查看日志：

```powershell
docker compose -f docker-compose.memorybear.yml logs -f
```

停止但保留数据：

```powershell
docker compose -f docker-compose.memorybear.yml stop
```

服务及端口：

| 服务 | 宿主机地址/端口 |
|---|---|
| PostgreSQL | `127.0.0.1:5433` |
| Redis | `127.0.0.1:6380` |
| Neo4j Browser | `http://127.0.0.1:7475` |
| Neo4j Bolt | `127.0.0.1:7688` |
| Elasticsearch | `http://127.0.0.1:9201` |

本地开发数据库账号：

```text
PostgreSQL 用户：memorybear
PostgreSQL 密码：memorybear_dev_password
PostgreSQL 数据库：memorybear

Neo4j 用户：neo4j
Neo4j 密码：memorybear_dev_password
```

上述账号仅适合本地开发，生产环境必须更换密码。

## 4. 后端依赖安装

项目的 `requirements.txt` 与 `pyproject.toml` 曾经不一致，`requirements.txt` 遗漏了 `deprecated` 等依赖。现已给 `pyproject.toml` 增加 setuptools 包发现配置，并将项目以 editable 模式安装。

以后重新安装可执行：

```powershell
conda activate memorybear
cd D:\project\MemoryBear-main\api
python -m pip install -e . --proxy http://127.0.0.1:7897
```

检查依赖：

```powershell
python -m pip check
```

代理端口检测：

```powershell
Test-NetConnection 127.0.0.1 -Port 7897
```

注意：此前误写为 `789` 会造成 `WinError 10061`。正确端口是 `7897`。

## 5. 后端启动

首次启动前执行数据库迁移：

```powershell
conda activate memorybear
cd D:\project\MemoryBear-main\api
python -m alembic upgrade head
```

启动后端：

```powershell
python -m uvicorn service.main:app --host 0.0.0.0 --port 8001
```

开发时如需自动重载：

```powershell
python -m uvicorn service.main:app --host 0.0.0.0 --port 8001 --reload
```

项目初始化很重，首次运行建议不使用 `--reload`，避免重复加载模型。

真正启动成功的标志：

```text
Application startup complete
```

后端接口文档：

```text
http://127.0.0.1:8001/docs
```

## 6. 前端启动

打开一个新的 PowerShell：

```powershell
cd D:\project\MemoryBear-main\web
npm run dev
```

如尚未安装前端依赖：

```powershell
npm install
npm run dev
```

本机访问：

```text
http://localhost:5175/
```

Vite 还会显示 `172.*`、`10.*` 地址，它们分别可能是 Docker、WSL、Hyper-V、VPN 或局域网网卡地址。当前电脑自己访问时优先使用 `localhost:5175`。

## 7. 系统初始化和登录

后端运行后初始化管理员：

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8001/backend/setup
```

第一次执行返回：

```text
Superuser created successfully.
```

表示管理员创建成功。

再次执行返回：

```text
Superuser already exists.
```

表示管理员已经存在，无须重复初始化，也不是错误。执行这个 HTTP 请求与当前激活的是 `base`、`memory` 还是 `memorybear` 环境无关，因为它只是向已经运行的后端发送请求。

默认登录账号：

```text
邮箱：admin@example.com
密码：admin_password
```

登录地址：

```text
http://localhost:5175/#/login
```

## 8. 今天遇到的主要报错

### 8.1 `datrie` 构建失败

报错：

```text
Microsoft Visual C++ 14.0 or greater is required
```

原因：Windows + Python 3.12 没找到预编译 wheel，pip 尝试从源码编译，但电脑缺少 C++ Build Tools。

解决：

```powershell
conda install -c conda-forge datrie=0.8.3 -y
```

### 8.2 `volcenginesdkarkruntime` 错误

环境曾安装错误的同名包 `volcenginesdkarkruntime 0.0.1`，里面没有项目需要的 `Ark` 类。

正确依赖来自：

```text
volcengine-python-sdk[ark]==5.0.19
```

### 8.3 `deprecated` 缺失

原因：`deprecated>=1.3.1` 写在 `pyproject.toml`，但没有写入原来的 `requirements.txt`，所以执行 `pip install -r requirements.txt` 不会安装它。

现已通过安装完整项目补齐。

### 8.4 editable 安装发现多个顶层包

报错：

```text
Multiple top-level packages discovered in a flat-layout: ['app', 'migrations']
```

原因：项目缺少 setuptools 包发现规则。现已配置只安装 `app*`，排除 `migrations*`、`tests*` 和 `scripts*`。

### 8.5 DeepDoc OCR 模型下载失败

后端首次启动会下载：

```text
InfiniFlow/deepdoc
```

目前已下载部分模型，但 Hugging Face CDN 通过代理下载布局模型时发生：

```text
SSLError: UNEXPECTED_EOF_WHILE_READING
```

模型目录：

```text
D:\project\MemoryBear-main\api\res\deepdoc
```

完整目录应包含：

```text
det.onnx
rec.onnx
tsr.onnx
ocr.res
layout.laws.onnx
layout.manual.onnx
layout.onnx
layout.paper.onnx
```

如果后端继续提示缺少 `layout.*.onnx`，需要从以下页面手动下载并放入上述目录：

```text
https://huggingface.co/InfiniFlow/deepdoc/tree/main
```

### 8.6 PSReadLine 异常

报错来源：

```text
Microsoft.PowerShell.PSConsoleReadLine.Paste
System.Console.SetCursorPosition
```

这是 PowerShell 在粘贴多行命令时的终端渲染 Bug，不是 MemoryBear、Conda 或后端报错。建议逐行执行命令，或升级 PSReadLine。

## 9. 每日启动流程

### 第一步：启动 Docker 底座

```powershell
cd D:\project\MemoryBear-main
docker compose -f docker-compose.memorybear.yml up -d
```

### 第二步：启动后端

```powershell
conda activate memorybear
cd D:\project\MemoryBear-main\api
python -m uvicorn service.main:app --host 0.0.0.0 --port 8001
```

### 第三步：启动前端

```powershell
cd D:\project\MemoryBear-main\web
npm run dev
```

### 第四步：访问

```text
前端：http://localhost:5175/
API 文档：http://127.0.0.1:8001/docs
Neo4j：http://127.0.0.1:7475
```

## 10. 常用检查命令

```powershell
# 查看 Conda 环境
conda env list

# 确认 Python 来自 memorybear
python -c "import sys; print(sys.executable)"

# 检查 Python 依赖
python -m pip check

# 查看 Docker 服务
docker compose -f D:\project\MemoryBear-main\docker-compose.memorybear.yml ps

# 测试后端
Invoke-WebRequest http://127.0.0.1:8001/docs

# 测试 Elasticsearch
Invoke-RestMethod http://127.0.0.1:9201

# 测试端口
Test-NetConnection 127.0.0.1 -Port 5433
Test-NetConnection 127.0.0.1 -Port 6380
Test-NetConnection 127.0.0.1 -Port 7688
```
