# Agent Memory Service 实施计划

## 目标与交付原则

本计划把 MVP 拆为十个可独立验收的阶段。每个阶段都必须遵守 `AGENTS.md` 与
`backend/docs/agent-memory-design.html`，尤其是 TenantContext、三层记忆、Consolidate Once、
PostgreSQL 主记录和确定性治理不变量。

任何阶段都不能通过跨租户扫描后过滤、从短期摘要生成长期记忆、让 LLM 直接写状态，或把派生索引当成事实来源来缩短实现路径。

## 阶段 1：TenantContext 和基础设施

- **输入**：认证后的主体声明、环境配置、PostgreSQL/Redis 连接信息、trace ID。
- **输出**：只读 `TenantContext`、fail-closed 依赖、FastAPI 应用、配置加载、结构化错误、数据库和 Redis 健康探针。
- **修改模块**：`backend/src/service/auth`、`backend/src/api/dependencies.py`、`backend/src/service/core`、`backend/src/infrastructure/db`、`backend/src/infrastructure/redis`、`backend/src/main.py`。
- **数据库变更**：建立 Alembic 基线；暂不创建业务表。
- **测试要求**：配置覆盖、TenantContext 不可变、正文出现 `tenant_id` 被拒绝、无上下文请求 fail closed、`/health` 和 `/ready`。
- **完成标准**：应用在 `memory` conda 环境启动；健康检查可用；就绪检查真实探测 PostgreSQL 和 Redis；没有业务代码依赖客户端 tenant ID。

## 阶段 2：领域模型与数据库

- **输入**：领域对象定义、复合键规则、生命周期状态和版本关系。
- **输出**：Pydantic 领域对象、SQLAlchemy 模型、Repository/UoW Port、首批迁移和租户级约束。
- **修改模块**：`backend/src/domain`、`backend/src/ports/repositories.py`、`backend/src/ports/unit_of_work.py`、`backend/src/infrastructure/db/models`、`backend/src/infrastructure/db/repositories`、`migrations`。
- **数据库变更**：创建 `memory_events`、`working_memory`、`task_memory`、`task_checkpoints`、`evidence`、`long_term_candidates`、`long_term_memory`、`memory_versions`、使用/生命周期/删除/索引投影/审计/Outbox 表；所有键绑定 `tenant_id`。
- **测试要求**：schema 校验、枚举和状态约束、复合主键/唯一键、相同业务 ID 的双租户共存、Repository 查询必须要求 `tenant_id`。
- **完成标准**：迁移可正向执行和回滚；对象与物理列映射唯一；不存在只按业务 ID 查询的 Repository API。

## 阶段 3：MemoryService.write

- **输入**：可信 `TenantContext` 与不含 `tenant_id` 的 `WriteMemoryRequest`。
- **输出**：不可变 `RawEvent`、更新后的 `WorkingMemory`、幂等写入结果和审计事件。
- **修改模块**：`backend/src/service/memory_service.py`、事件/工作记忆 Repository、exact idempotency 支持、API 路由。
- **数据库变更**：写入幂等键、事件顺序、工作区游标和审计索引。
- **测试要求**：正常写入、重复 idempotency key、事件不变性、工作记忆更新、请求体 tenant 覆盖拒绝、事务失败不产生半写。
- **完成标准**：同一请求可安全重试；原始事件先可靠保存；所有读写带当前租户；write 尚未触发收束时不伪造长期记忆。

## 阶段 4：Consolidate Once

- **输入**：同租户收束游标之后的冻结事件窗口、当前 Working Memory、批次幂等键。
- **输出**：同批次的 `Evidence`、`TaskCheckpoint`、`LongTermCandidate[]` 三个兄弟结果。
- **修改模块**：`backend/src/service/write/consolidate_once.py`、checkpoint/evidence/candidate Repository、UoW、checkpoint prompt。
- **数据库变更**：收束批次、窗口边界、游标、三类结果的批次外键与唯一约束。
- **测试要求**：只处理新增事件、三个兄弟结果、全部保存后推进游标、任一失败回滚且不推进、重试不重复、原始事件不被剪枝删除。
- **完成标准**：不存在“短期摘要 → 长期候选”数据路径；故障注入证明事件与游标安全；并发收束不会跨窗口或重复推进。

## 阶段 5：长期候选治理

- **输入**：`LongTermCandidate[]`、Evidence、当前同作用域长期主记录。
- **输出**：确定性的治理决定、`LongTermMemory`、`MemoryVersion`、审计和索引投影任务。
- **修改模块**：`backend/src/service/governance/candidate_governance.py`、长期主记录/版本 Repository、`JobDispatcher`。
- **数据库变更**：稳定键唯一约束、版本关系、冲突/合并引用和索引 Outbox。
- **测试要求**：价值/显式性/敏感/作用域门禁；CREATE、REFINE、CORRECT、MERGE、SUPERSEDE、DEFER、IGNORE；并发冲突；证据缺失拒绝。
- **完成标准**：LLM 建议不能直接改变状态；主记录与版本在单事务提交；索引任务失败不回滚主记录。

## 阶段 6：MemoryService.read

- **输入**：可信 `TenantContext`、`ReadMemoryRequest`、租户内 META 约束和可选 RetrievalPlan。
- **输出**：经过权限、状态、版本、去重、排序和预算控制的 `ContextPackage`。
- **修改模块**：`backend/src/service/read/retrieval_service.py`、`backend/src/service/read/context_compiler.py`、exact/vector/graph Port 与适配器。
- **数据库变更**：exact key、pgvector 索引、PostgreSQL 图节点/边、召回统计。
- **测试要求**：META、Express、Quick、Normal、Deep；精确/向量/图谱只返回 memory ID；回读 active 主记录；无效或跨租户 ID 为 NOT_FOUND。
- **完成标准**：所有候选在最终返回前按 `tenant_id + memory_id` 回读；Context Package 可解释来源与命中原因；索引不可用时按设计降级。

## 阶段 7：MemoryService.gc

- **输入**：可信 `TenantContext`、GC 策略、TTL/配额/重复/过期/删除请求。
- **输出**：降权、合并、归档或三阶段删除结果及最小审计。
- **修改模块**：`backend/src/service/lifecycle_service.py`、生命周期/配额/删除 Repository、各索引清理适配器。
- **数据库变更**：生命周期、使用统计、租户配额、删除请求和清理任务状态。
- **测试要求**：TTL、长期未使用降权、保护门禁、容量水位、重复/过时治理、用户删除全级联、清理失败重试。
- **完成标准**：只治理当前租户；未使用不会自动物理删除；`pending_delete → tombstoned → purged` 可审计且可重试；审计不含已删除正文。

## 阶段 8：LLM Adapter

- **输入**：动作专用的最小窗口、任务目标、允许作用域、Evidence 和严格输出 schema。
- **输出**：检查点、候选、RetrievalPlan 或治理建议；不输出可执行权限和状态变更。
- **修改模块**：`backend/src/ports/llm_client.py`、`backend/src/infrastructure/llm`、`backend/src/service/prompts`。
- **数据库变更**：可选的 LLM 调用审计字段，包括 model/prompt 版本、输入输出哈希、耗时与错误；不保存秘密。
- **测试要求**：确定性 `MockLLMClient`、非法 JSON、额外字段、证据伪造、tenant 注入、超时和降级。
- **完成标准**：本地测试不依赖真实模型；任何模型失败都不破坏原始写入和确定性状态机。

## 阶段 9：多租户验证

- **输入**：租户 A/B 使用完全相同业务 ID、稳定键、任务 ID 和 memory ID 的验证夹具。
- **输出**：覆盖 write/read/resume/gc/delete/rebuild/audit 的安全回归报告。
- **修改模块**：`tests/security`、`tests/fixtures`、Repository/索引/任务适配器的故障注入。
- **数据库变更**：仅测试夹具；必要时增加防止无租户查询的数据库策略。
- **测试要求**：所有检索档位不串租户、删除不越界、后台任务单租户、跨租户资源 ID 对外 NOT_FOUND、拒绝审计无正文。
- **完成标准**：双租户 Validation Harness 作为 CI 发布门禁，任何无 `tenant_id` 数据访问都失败。

## 阶段 10：Demo 和验收

- **输入**：完整服务、Compose 环境、确定性 Mock LLM、演示数据。
- **输出**：可重复运行的闭环 demo、README 命令、验收结果和已知限制。
- **修改模块**：`scripts/run_demo.py`、`README.md`、Compose、测试报告。
- **数据库变更**：演示迁移和隔离的种子数据；不得加入生产默认数据。
- **测试要求**：从原始写入到删除的端到端闭环、服务重启恢复、索引失败重建、双租户演示。
- **完成标准**：新环境按 README 一次启动；演示结果可重复；格式、静态检查、全部测试和验收矩阵通过。

## 跨阶段质量门禁

每阶段完成时都要记录实际命令、迁移版本、测试结果和未覆盖项。若某阶段引入新的 Port，必须同时提供可运行默认 Adapter 或明确的 fail-closed 绑定；不得用空实现冒充成功。
