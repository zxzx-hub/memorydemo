# AGENTS.md

本文件适用于仓库根目录及其全部子目录。所有 Agent、开发者、脚本和后台任务都必须遵守。

## 1. 事实来源与规则优先级

- `docs/agent-memory-design.html` 是本项目的领域架构事实来源。开始任何开发、评审或修复前，必须阅读本文件和与任务相关的设计文档章节。
- 若代码、测试、注释或其他文档与领域设计冲突，以 `docs/agent-memory-design.html` 和本文件中的架构不变量为准；不得通过降低测试要求来保留冲突实现。
- 本文件只固化工程约束，不取代领域设计中的对象定义、状态机、检索路由、生命周期规则和验收标准。

## 2. 项目目标与范围

实现一个可在本地运行和测试的多租户 Agent Memory Service MVP。

MVP 必须完成以下闭环：

```text
原始事件写入
→ 工作记忆更新
→ Consolidate Once
→ 并行形成 Evidence、TaskCheckpoint、LongTermCandidate[]
→ 长期候选治理
→ 长期主记录
→ 精确检索、语义检索和关系检索
→ Context Package
→ 生命周期治理和删除
```

第一版只开发后端服务、数据库、测试和演示脚本，不开发前端管理页面。

## 3. 架构不变量

以下规则是硬约束。任何实现、迁移、测试夹具、缓存、索引和后台任务都不得绕过。

### 3.1 TenantContext 不变量

- `tenant_id` 必须由服务端认证中间件从已验证的 JWT、mTLS 或服务账号中派生，并封装在只读、不可覆盖的 `TenantContext` 中。
- `MemoryService.write(ctx, request)`、`MemoryService.read(ctx, request)`、`MemoryService.gc(ctx, request)` 及其调用的全部内部函数、存储 Port、后台任务都必须显式接收可信 `TenantContext` 或从中取得 `tenant_id`。
- 请求正文、query 参数、Prompt 和 LLM 输出都不是 `tenant_id` 的可信来源。请求若携带 `tenant_id`，不得以其覆盖服务端值；显式不一致必须拒绝。
- 禁止 Agent 或 LLM 创建、修改、选择或覆盖 `tenant_id`。
- 禁止任何不带 `tenant_id` 的数据库查询、更新、删除、恢复、扫描、索引检索或重建。
- 禁止只使用 `user_id`、`task_id`、`memory_id`、`workspace_id`、`project_id`、`normalized_key` 等业务标识访问数据。这些标识只在租户内有意义。
- 每一个数据库主键、唯一键、外键关联、缓存键、exact key、向量元数据、图谱节点、图谱边、Outbox/后台任务和审计记录都必须包含或可靠绑定 `tenant_id`。
- SQL、KV、向量和图谱隔离必须在数据访问条件中生效，禁止先做跨租户读取或全表扫描、再在应用层过滤。
- 后台任务必须在创建时冻结单一 `tenant_id`，只扫描该租户范围；缺少租户信息时不得继续执行。
- 任何租户信息缺失、覆盖不匹配或资源归属不一致都必须 fail closed：不读、不写、不覆盖、不删除、不泄露目标是否存在。跨租户资源对外统一表现为 `NOT_FOUND`，内部只记录不含对方正文的最小拒绝审计。

推荐的租户内复合定位至少包括：

- Working Memory：`(tenant_id, workspace_id)`
- Short-Term Memory：`(tenant_id, task_memory_id)`
- Task Checkpoint 唯一键：`(tenant_id, task_id, checkpoint_no)`
- Long-Term Memory：`(tenant_id, memory_id)`
- 稳定键唯一性：`(tenant_id, scope, memory_type, normalized_key)`
- 短期恢复：`tenant_id + task_id`
- 派生索引版本：`tenant_id + memory_id + version`

### 3.2 三层记忆不变量

- **Working Memory**：当前请求和当前任务的可观察、可执行运行状态，生命周期为请求级或任务执行期。
- **Short-Term Memory**：当前任务的可恢复检查点和连续性视图，按任务精确恢复，不是工作记忆溢出区。
- **Long-Term Memory**：经过证据绑定与治理、可跨任务复用的稳定信息。
- 三层可以引用同一原始事件，但 Short-Term Memory 不能转换、二次摘要或压缩为 Long-Term Memory。
- 长期候选必须直接来源于同一租户的原始事件窗口及其 Evidence；不得从 TaskCheckpoint、`resume_context` 或其他短期摘要派生。
- 普通过程日志、临时状态和未确认推断不得直接进入长期主记录。

### 3.3 Consolidate Once 不变量

- Consolidate Once 只处理当前 `tenant_id` 下、收束游标之后的新增事件；不得重复扫描全部历史，也不得处理其他租户事件。
- 每个冻结的增量窗口只理解一次，并行产生三个兄弟结果：
  - `Evidence`
  - `TaskCheckpoint`
  - `LongTermCandidate[]`
- 三个结果来自同一个原始事件窗口并保留窗口边界、事件引用和批次身份；不得实现为“工作记忆 → 短期摘要 → 长期摘要”的串行转换。
- 只有三个结果全部成功保存后，才能推进收束游标。
- 任一分支失败时不得丢失原始事件、不得推进游标。重试必须可恢复且幂等，不能产生重复检查点、候选或证据。
- 原始事件不可因剪枝、切块或低价值判断而删除；剪枝只影响候选生成输入。

### 3.4 MemoryService 接口不变量

上层业务只允许调用：

```python
MemoryService.write(ctx, request)
MemoryService.read(ctx, request)
MemoryService.gc(ctx, request)
```

内部动作映射固定为：

- `write` → `01 原始写入`、`02 暂存`、`05 沉淀`
- `read` → `03 唤回`、`04 调用`
- `gc` → `06 释放`

六个动作是内部执行语义，不是外部 API，也不能被设计成第四层记忆。

### 3.5 LLM 权限不变量

LLM 只能返回经过 schema 约束的候选、计划或建议。

LLM 可以参与：

- 任务检查点与恢复摘要生成
- 对话剪枝和切块建议
- 长期候选抽取、类型与作用域建议
- 检索计划、子查询、实体和关系建议
- 重复、冲突、可合并或低价值建议

LLM 不得：

- 直接执行 SQL、KV、向量或图谱写操作
- 直接修改任何记忆状态
- 直接删除、归档、合并、替代或纠正记忆
- 决定租户身份、权限或隔离范围
- 直接选择最终返回的数据库记录
- 直接修改版本号或版本关系
- 绕过 schema、权限、证据存在性、状态、版本、冲突和作用域校验

最终写入、检索结果选择、合并、替代、归档和删除必须由确定性代码执行。模型失败时应降级到规则、原始存档或普通检索，不能破坏主链路。

### 3.6 主记录与派生索引不变量

- PostgreSQL 中的 active Long-Term Memory 主记录是长期内容的唯一事实来源。
- exact key、vector index、graph projection 和 cache 都是派生访问路径，不是独立内容真值。
- 派生索引只保存或返回 `memory_id` 及必要的租户/版本定位信息，不复制长期内容真值。
- 每次索引命中后，最终结果必须使用 `tenant_id + memory_id` 重新读取状态为 `active`、版本与作用域有效的长期主记录。
- 长期主记录和版本审计成功提交后，再建立或派发派生索引。索引构建失败不能回滚已成功保存的主记录；索引必须能够按 `tenant_id + memory_id + version` 重试和重建。
- 图谱 MVP 使用 PostgreSQL 节点表和边表实现，但必须通过 `GraphStore` Port 抽象；节点、边和每一步遍历均需绑定同一 `tenant_id`。

### 3.7 检索与 Context Package 不变量

- `read` 先绑定可信 `TenantContext`，再在该租户内应用 META 的 user/project/agent 权限与作用域；META 不能替代租户隔离。
- 精确检索使用租户分区的 key 定位 `memory_id`；语义检索使用带 `tenant_id` 元数据过滤的向量索引；关系检索使用租户分区的图节点和边。
- 无论候选来自 exact、vector、graph 或 cache，必须回读同租户 active 主记录后才能进入结果。
- 最终只把当前 Agent 和任务需要的少量、去重、排序、权限过滤后的记录组装为 `ContextPackage`，并保留 `memory_id`、来源和命中理由。

### 3.8 生命周期与删除不变量

- 生命周期治理只处理当前 `TenantContext` 对应租户的数据。
- 长期未使用默认先 `DOWNRANK`，再考虑归档；未使用不等于事实错误，也不能自动物理删除。
- 自动治理必须尊重 `pinned`、`protected`、`reference_count`、`retention_until` 和 `legal_hold` 等保护门禁。
- 用户明确删除时，必须只处理当前租户内的：
  - 长期主记录及版本内容
  - Evidence 和来源关联
  - exact key
  - vector index
  - graph projection 的节点与边
  - cache
  - 相关派生索引/重建任务状态
- 删除流程采用可审计、可重试的 `pending_delete → tombstoned → purged` 阶段；进入 tombstone 后对外表现为 `NOT_FOUND`。
- 删除后可以保留最小审计凭证，但不得保留已删除正文、可还原正文的载荷或其他租户内容。
- 任一清理步骤失败不得影响其他租户，且必须能够在原租户范围内安全重试。

## 4. 技术栈与适配器边界

推荐并默认采用：

- Python 3.12
- FastAPI
- Pydantic v2
- SQLAlchemy 2.x async
- PostgreSQL 16
- pgvector
- Redis
- Alembic
- pytest
- pytest-asyncio
- httpx
- Docker Compose

适配器约束：

- 图谱使用 `GraphStore` Port；MVP 默认适配器为 PostgreSQL 节点表和边表。
- 后台任务使用 `JobDispatcher` Port；MVP 提供可运行的同步适配器或数据库 Outbox Worker。核心业务不得直接依赖 Celery。
- LLM 使用 `LLMClient` Port；默认提供可运行、确定性的 `MockLLMClient`。真实模型适配器必须是可选依赖，不能成为本地测试的前提。
- 需要延后实现的外部能力必须由明确的 Port/Adapter 隔离，并提供可运行的默认实现。禁止在核心业务中用无意义的 `TODO`、`pass`、空返回或伪成功冒充实现。

## 5. Python 与 Conda 环境

- 本项目必须在名为 `memory` 的 conda 环境中运行。
- 所有项目 Python 命令必须在该环境内执行，优先使用非交互形式：

```powershell
conda run -n memory python --version
conda run -n memory python -m pytest
```

- 格式检查、静态检查、Alembic、演示脚本和服务启动也必须通过 `conda run -n memory ...` 或在明确激活 `memory` 后执行。
- 开始涉及 Python 的任务时先确认环境存在且 Python 主版本符合 3.12。环境缺失或版本不符时应明确报告，不得静默改用系统 Python。
- 依赖和命令以仓库内的 `pyproject.toml`、锁文件、Compose 配置和任务脚本为准；不得把仅存在于全局环境的包当作项目依赖。

## 6. 工程执行流程

每次开始任务时必须按顺序执行：

1. 阅读根目录 `AGENTS.md`。
2. 阅读与任务相关的设计文档；涉及领域语义时以 `docs/agent-memory-design.html` 为必读来源。
3. 检查已有代码、迁移、测试、夹具和配置，避免创建重复模块或第二套概念命名。
4. 在修改前给出本次计划和影响范围。
5. 以小步、局部修改完成任务，不一次重写整个项目，不顺手改动无关代码。
6. 为所有重要逻辑增加或更新测试。
7. 在 `memory` conda 环境中运行仓库配置的格式检查、静态检查和测试；涉及数据库或 API 时运行相应集成测试。
8. 修复本次修改导致的失败。不得删除、跳过或放宽测试来制造通过结果。
9. 最后报告修改文件、实际执行的检查命令与结果、未运行项目及原因、遗留问题。

文档或纯配置修改若没有适用的 Python 测试，也必须执行与变更相称的校验（例如格式、配置解析或 diff 检查），并明确说明未运行测试的原因。

## 7. 代码与数据建模规则

- 使用 async SQLAlchemy 2.x 的显式事务边界；跨 Evidence、TaskCheckpoint、LongTermCandidate 和游标推进的操作必须体现原子性或可证明的幂等恢复语义。
- API/领域对象可以使用 `owner: {type, id}`、`scope: {type, id}`、`quality: {...}` 等嵌套结构；数据库列按设计展平。禁止为同一概念引入第三套字段名。
- 使用 Pydantic v2 对所有 API、LLM 输出、任务载荷和 Context Package 做严格 schema 校验；额外字段、非法枚举和租户覆盖应被明确处理。
- 状态迁移、版本递增、唯一性、TTL、权限、证据存在性和删除门禁由确定性领域服务控制。
- 审计记录必须带 `tenant_id`、operation、可信 principal、trace_id、结果和必要原因；目标只保存安全标识或哈希，不记录其他租户正文。
- 记录日志时不得输出秘密、完整敏感正文、跨租户候选内容或可还原已删除正文的数据。
- 任何派生系统不可用时，主记录链路应按设计降级或重试，不能把派生系统升级成事实来源。

## 8. 测试与发布门禁

所有重要逻辑必须有测试。至少覆盖：

- 正常的原始事件写入、Working Memory 更新和增量游标处理。
- Consolidate Once 的三兄弟结果、全部成功后推进游标、任一失败不推进、重试幂等。
- Short-Term Memory 按 `tenant_id + task_id` 保存和恢复。
- 长期候选直接来自原始事件与 Evidence，而不是短期摘要。
- 候选治理与 `CREATE`、`REFINE`、`CORRECT`、`MERGE`、`SUPERSEDE` 等确定性状态操作。
- exact、vector、graph 三类检索只返回 `memory_id`，最终回读同租户 active 主记录并生成 Context Package。
- 主记录成功、索引失败时主记录不回滚，且索引可重建。
- GC 降权、合并、归档、保护门禁和显式删除的完整级联。
- LLM 输出 schema 校验、越权建议拒绝和 Mock 降级路径。

多租户隔离是发布门禁。必须建立双租户 Validation Harness：租户 A 与 B 使用完全相同的 `user_id`、`task_id`、`project_id`、`workspace_id`、`memory_id` 或 `normalized_key`，但内容不同，并断言：

- write 不互相覆盖；
- META、Express、Quick、Normal、Deep 和 Context Package 不串租户；
- resume 不恢复另一租户检查点；
- gc/delete 只清理当前租户的主记录、Evidence、exact、vector、graph 和 cache；
- index rebuild 固定单一租户，缺少 `tenant_id` 的 job 被拒绝；
- 缺失、覆盖不匹配和跨租户资源访问 fail closed，并生成不泄露正文的最小审计。

任何绕过这些隔离测试、使用不带 `tenant_id` 的存储接口，或让 LLM 直接改变持久化状态的实现，都不得合并。
