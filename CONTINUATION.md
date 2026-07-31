# Agent Memory Service 开发交接总结

更新时间：2026-07-31  
工作区：`D:\project\memorydemo`  
运行环境：Conda `memory`，Python 3.12.13

> 本文用于后续继续开发。当前操作已经终止，不应把“提示词 4”视为已完成。

## 1. 当前总体状态

| 阶段 | 状态 | 说明 |
|---|---|---|
| 提示词 0：`AGENTS.md` | 已完成 | 已固化多租户、三层记忆、Consolidate Once、LLM 权限、主记录、删除和 Conda 规则。 |
| 提示词 1：计划与工程骨架 | 已完成 | 文档、FastAPI 骨架、Docker/Alembic/pytest 等基础文件已建立。 |
| 提示词 2：TenantContext、领域模型、数据库 | 已完成 | TenantContext、20 张核心表、初始迁移、租户 Repository 和隔离测试已建立。 |
| 提示词 3：write 与 Consolidate Once | 已完成 | 事件写入、Working Memory、三兄弟结果、事务游标、Outbox、默认 Consolidator 已实现并测试。 |
| 提示词 4：候选治理和长期主记录 | **部分实现，未验收** | 上一轮被中断；代码和迁移已写入一部分，但缺少完整测试、索引失败处理和最终验证。 |
| 提示词 5：read 与 Context Package | **主体已实现，待最终验收** | 单元测试已通过；PostgreSQL 不可用，因此迁移和 SQL 集成测试尚未实际完成。 |
| GC、删除与生命周期 | 未开始 | `MemoryService.gc` 仍返回 `FEATURE_NOT_AVAILABLE`。 |

## 2. 已完成的基础工程

### 2.1 项目约束和文档

已存在：

- `AGENTS.md`
- `docs/agent-memory-design.html`
- `docs/implementation-plan.md`
- `docs/domain-model.md`
- `docs/api-contract.md`
- `docs/architecture-decisions.md`
- `docs/test-matrix.md`
- `implementation-plan.md`
- `README.md`

注意：`docs/api-contract.md` 尚未同步提示词 3、4、5 的最终请求和响应结构，后续需要更新。

### 2.2 TenantContext 与隔离

已实现：

- 不可变 `TenantContext`
- 只能由 `TenantResolver` 创建
- `DevelopmentTenantResolver`
- FastAPI 认证中间件注入
- 缺失上下文时 fail closed
- 请求正文额外 `tenant_id` 被 Pydantic `extra="forbid"` 拒绝
- Repository 显式接收 `TenantContext`
- Redis key 使用 `tenant:{tenant_id}:...`
- PostgreSQL 主键、唯一键和主要关联均绑定 `tenant_id`

### 2.3 数据库

核心 20 张表已定义，包括：

- `memory_events`
- `working_memory`
- `task_memory`
- `task_checkpoints`
- `memory_evidence`
- `memory_candidates`
- `long_term_memory`
- `long_term_memory_versions`
- `memory_usage_stats`
- `memory_lifecycle_state`
- `tenant_memory_quota`
- `memory_deletion_requests`
- `memory_index_projections`
- `memory_exact_keys`
- `memory_vector_indexes`
- `memory_graph_nodes`
- `memory_graph_edges`
- `memory_audit_logs`
- `consolidation_cursors`
- `outbox_jobs`

迁移文件：

- `migrations/versions/20260731_0001_initial_memory_schema.py`
- `migrations/versions/20260731_0002_write_chain_event_fields.py`
- `migrations/versions/20260731_0003_governance_state.py`

其中 `0003` 已生成并通过 Alembic offline SQL 生成检查，但**没有实际应用到 PostgreSQL**。

## 3. 提示词 3：已完成内容

### 3.1 统一写入

`MemoryService.write` 已支持可区分联合：

- `event`
- `consolidate`
- `promote_candidates`

主要文件：

- `app/domain/commands.py`
- `app/domain/results.py`
- `app/services/default_memory_service.py`

### 3.2 原始事件和 Working Memory

已实现：

- `event_id` 生成或接收
- `tenant_id + event_id/idempotency_key` 幂等
- 原始正文及引用不可被重复写入修改
- session/task/role/content/type/source/time 持久化
- file/tool/artifact 引用
- Redis Working Memory
- `tenant_id + workspace_id` 隔离
- 配置化 message/token/idle 收束阈值

### 3.3 Consolidate Once

已实现：

- 租户工作区锁
- 增量游标
- 无新增事件幂等返回
- Evidence、TaskCheckpoint、LongTermCandidate 同源兄弟结果
- 三类结果和游标在同一数据库事务内保存
- 失败时不推进游标
- 稳定批次 ID、检查点号、候选治理 Outbox
- `DeterministicConsolidator`
- `MockLLMConsolidator`
- 指定中文偏好规则识别

主要文件：

- `app/services/consolidate_once.py`
- `app/infrastructure/consolidation/deterministic.py`
- `app/infrastructure/db/repositories/write.py`
- `app/infrastructure/redis/working_memory.py`
- `app/infrastructure/memory/in_memory.py`

## 4. 提示词 4：已做但尚未完成的内容

### 4.1 已写入的部分

已经增加：

- `GovernanceSuggestion`
- `GovernanceChecks`
- `GovernanceCandidateState`
- `GovernanceResult`
- `GovernanceUnitOfWork` Port
- `GovernanceAdvisor` Port
- `IndexProjector` Port
- `DeterministicGovernanceAdvisor`
- `ProjectionPlanner`
- `CandidateGovernanceService`
- 内存 Governance UoW
- SQLAlchemy Governance UoW
- candidate 治理状态字段
-长期版本 `snapshot`
- `IndexStatus.FAILED`
- Alembic `0003`

相关文件：

- `app/services/candidate_governance.py`
- `app/services/projection_planner.py`
- `app/ports/governance_advisor.py`
- `app/ports/governance_store.py`
- `app/ports/index_projector.py`
- `app/infrastructure/governance/`
- `app/infrastructure/memory/governance.py`
- `app/infrastructure/db/repositories/governance.py`
- `migrations/versions/20260731_0003_governance_state.py`

### 4.2 未完成和未验证项

以下内容不能视为完成：

- 尚未编写 CREATE、REFINE、CORRECT、MERGE、SUPERSEDE、DEFER、IGNORE 的完整测试矩阵。
- 尚未验证跨租户 evidence、duplicate/conflict target 的 PostgreSQL 行为。
- 尚未验证版本竞争和并发锁行为。
- 尚未完成并测试独立 `IndexProjectionService`。
- 尚未完成“索引执行失败后 projection 标记 failed/stale、主记录不回滚、可重试”的端到端测试。
- PostgreSQL GraphStore 当前主要实现读取/遍历和删除，候选治理到正式 graph node/edge 投影的完整 Worker 尚未完成。
- SQL Governance Repository 未经过真实 PostgreSQL 集成测试。
- `CandidateGovernanceService` 和 SQL UoW 虽已通过当时的 Mypy，但逻辑没有做最终代码审查。
- 提示词 4 的全部验收测试尚未运行。

继续开发前，建议优先完成提示词 4，不要直接假设长期主记录治理已经可靠。

## 5. 提示词 5：已实现内容

### 5.1 ReadRequest

`ReadMemoryRequest` 已扩展并提供 `ReadRequest` 别名，字段包括：

- `mode`
- `query`
- `task_id`
- `workspace_id`
- `task_goal`
- `agent_id`
- `agent_role`
- `current_stage`
- `current_step`
- `memory_id`
- `memory_key`
- `normalized_key`
- `scope_filters`
- `memory_types`
- `time_range`
- `need_evidence`
- `token_budget`
- `top_k`

模式包括：

- `AUTO`
- `META`
- `RESUME`
- `EXPRESS`
- `QUICK`
- `NORMAL`
- `DEEP`

### 5.2 RetrievalPlan

严格模型包含：

- `sub_queries`
- `memory_types`
- `scopes`
- `entities`
- `relations`
- `time_range`
- `need_evidence`
- `recommended_mode`

已实现：

- `RetrievalPlanProvider` Port
- `DeterministicRetrievalPlanProvider`
- `LLMRetrievalPlanProvider`
- LLM 返回无效 schema 时回退到确定性计划
- LLM payload 不包含可信 `tenant_id`
- 最终记录选择不由 LLM 执行

### 5.3 AUTO 路由

当前确定性规则：

- 已知 memory ID/key/type+normalized key → EXPRESS
- 有 task_id 且没有 query → RESUME
- 原因、影响、依赖、多跳词语 → DEEP
- 多条件、多个 scope/type、时间范围 → NORMAL
- 其他语义问题 → QUICK

只有 NORMAL/DEEP 调用 RetrievalPlan Provider。

### 5.4 各模式

已实现：

- META：只返回控制信息，不返回长期正文
- RESUME：按 `tenant_id + task_id` 获取最新有效 checkpoint
- EXPRESS：memory ID、exact key、type+normalized key
- QUICK：vector → memory ID → tenant canonical reread
- NORMAL：多子查询 vector、精确条件、一跳 graph
- DEEP：多子查询、三跳 graph、默认证据回查

### 5.5 公共检索链

已实现：

1. 绑定 TenantContext
2. 生成 META 允许范围
3. 索引只返回 memory ID
4. 使用 `tenant_id + memory_id` 回读主记录
5. active/valid/type/scope/time 过滤
6. memory ID 去重
7. 配置化确定性评分
8. top_k 与 token budget
9. Context Package 分组
10. 按需 Evidence 回查

向量适配器返回其他租户 ID 时，当前租户 Repository 回读不到正文，因此不会进入结果。

### 5.6 Context Package

已实现：

- `ContextMeta`
- `TaskCheckpointView`
- `MemoryContextItem`
- `EvidenceExcerpt`
- `TokenUsage`
- `ContextPackage`

分组：

- facts
- preferences
- constraints
- decisions
- progress

不会把数据库完整记录原样注入 Agent。

### 5.7 排序和预算

排序权重已移入配置：

- semantic relevance
- confidence
- importance
- explicitness
- freshness
- retrieval weight
- scope match

配置字段位于：

- `app/core/config.py`
- `.env.example`

当前 token 估算规则是近似的 `ceil(字符数 / 4)`，后续可以替换为真实 tokenizer。

### 5.8 使用统计

已实现：

- 被当前租户主记录成功回读的候选增加 `recall_count`
- 真正进入 Context Package 的记录才增加 `use_count`
- expired/superseded/预算淘汰记录不会增加 `use_count`
- 跨租户未回读记录不会增加当前或其他租户计数

`confirmed` 和 `corrected` 仍由其他业务动作更新，read 不会误改。

### 5.9 主要 Read 文件

- `app/services/retrieval_service.py`
- `app/services/context_compiler.py`
- `app/ports/retrieval_store.py`
- `app/ports/retrieval_plan_provider.py`
- `app/infrastructure/retrieval/`
- `app/infrastructure/db/repositories/retrieval.py`
- `app/infrastructure/db/repositories/exact_key.py`
- `app/infrastructure/vector/postgresql.py`
- `app/infrastructure/graph/postgresql.py`
- `app/infrastructure/memory/retrieval.py`
- `app/main.py`

## 6. 已编写的 Read 测试

`tests/unit/test_read_chain.py` 已覆盖：

- META
- RESUME
- EXPRESS memory ID
- EXPRESS memory key
- EXPRESS type + normalized key
- EXPRESS 跨租户 NOT_FOUND
- QUICK
- NORMAL
- DEEP
- AUTO 五种路由
- Context Package 五类分组
- token budget
- 重复结果去重
- expired/superseded 过滤
- Evidence 按需读取
- recall/use 计数分离
- vector 返回跨租户 ID 后主记录回读阻止
- A/B 使用相同 memory ID 时分别返回各自正文

`tests/integration/test_read_chain_postgresql.py` 已创建，用于验证：

- A/B 相同 memory ID
- PostgreSQL 主记录回读隔离
- A/B recall/use 计数隔离

该集成测试尚未真正运行通过，因为最后 PostgreSQL 服务不可用。

## 7. 最后一次实际检查结果

最后一次全量 pytest：

```text
collected 52 items
47 passed
5 skipped
```

跳过的 5 项均为 PostgreSQL 集成测试：

- `tests/integration/test_read_chain_postgresql.py`
- `tests/integration/test_tenant_database_isolation.py` 中 3 项
- `tests/integration/test_write_chain_postgresql.py`

跳过原因：

```text
PostgreSQL integration service unavailable
ConnectionRefusedError / WinError 1225
```

当时 Docker Desktop Engine 也不可连接：

```text
failed to connect to docker API
pipe/dockerDesktopLinuxEngine not found
```

最后一次成功的静态检查发生在增加少量最终 Read 文件之前：

```text
Ruff: passed
Mypy: Success, 89 source files
```

随后又增加了：

- `LLMRetrievalPlanProvider`
- ReadRequest/ReadResult 别名
- PostgreSQL Read 集成测试
- TimeRange 校验和少量路由调整

因此恢复后必须重新运行 Ruff 和 Mypy，不能直接引用之前结果作为最终验收。

Alembic offline SQL 检查成功：

```text
20260731_0001
→ 20260731_0002
→ 20260731_0003
```

但 `0003` 未连接数据库执行。

## 8. 已知风险和待处理问题

### 高优先级

1. 完成提示词 4 的治理动作和安全测试。
2. 启动 PostgreSQL/Redis，实际应用 `0003`。
3. 运行全部 PostgreSQL 集成测试。
4. 对 SQL Governance Repository 做真实事务和并发验证。
5. 实现并测试索引构建失败、failed/stale、重试和 Graph 投影 Worker。

### Read 链路待确认

1. 默认 Mock LLM 返回通用无效 plan，当前会安全回退到确定性计划；需要增加该回退路径的显式测试。
2. 默认 Deep 确定性计划会生成关系类型，但没有自动抽取实体；没有实体时 PostgreSQL GraphStore 返回空结果。真实 LLM plan 或规则实体抽取需后续补充。
3. 当前 META 权限只能依据 TenantContext 的 principal 以及请求中可核对的 workspace/agent；TenantContext 尚未携带完整 project/agent claims，因此 project scope 默认不会被授权。
4. token 预算使用近似字符估算，不是模型 tokenizer。
5. `docs/api-contract.md`、`docs/domain-model.md` 和 README 尚未同步新 Read 契约。
6. 尚未增加真实 FastAPI `/v1/memory/read` 成功响应集成测试。

### 工作区说明

- 当前目录不是 Git 仓库，无法使用 `git status` 或 `git diff` 精确区分每阶段修改。
- 不要使用 `git reset --hard` 或其他破坏性方式清理。
- 所有后续 Python 命令必须在 `memory` Conda 环境执行。

## 9. 建议恢复顺序

### 第一步：确认环境

依次执行，避免 Windows 上并行 `conda run` 争用临时文件：

```powershell
conda run -n memory python --version
docker compose up -d
docker compose ps
```

如果 Docker Desktop 未启动，需要先由用户启动 Docker Desktop。

### 第二步：应用迁移

```powershell
conda run -n memory alembic current
conda run -n memory alembic upgrade head
conda run -n memory alembic current
```

预期 head：

```text
20260731_0003
```

### 第三步：重新执行基础门禁

```powershell
conda run -n memory ruff format --check .
conda run -n memory ruff check .
conda run -n memory mypy app
conda run -n memory python -m pytest
```

### 第四步：优先完成提示词 4

建议先补：

1. 七个治理动作单元测试
2. evidence/duplicate/conflict 跨租户测试
3. 版本竞争测试
4. 重复治理幂等测试
5. 安全审计不泄露正文测试
6. index failure 主记录不回滚测试
7. PostgreSQL Governance 集成测试

### 第五步：验收提示词 5

在 PostgreSQL 可用时至少单独运行：

```powershell
conda run -n memory python -m pytest tests/integration/test_read_chain_postgresql.py -vv
conda run -n memory python -m pytest tests/unit/test_read_chain.py -vv
```

之后补 API 成功路径测试和文档更新。

## 10. 下一位开发者的完成标准

只有同时满足以下条件，才能宣布提示词 4 和提示词 5 完成：

- `0003` 已实际应用到 PostgreSQL
- Ruff 通过
- Mypy strict 通过
- 全部单元测试通过
- PostgreSQL 集成测试无跳过且通过
- 七种治理动作全部有测试
- 七种读取模式全部有测试
- 双租户相同业务 ID 不串租户
- index failure 不回滚主记录
- vector/graph/exact 命中后都重新读取同租户 active 主记录
- 只有最终 Context Package 记录增加 `use_count`
- API 和领域文档已同步当前 schema

