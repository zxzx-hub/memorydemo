# 领域模型

## 总体关系

```text
TenantContext
  ├─ scopes every RawEvent and WorkingMemory operation
  ├─ scopes every TaskMemory / TaskCheckpoint
  └─ scopes every LongTermMemory, index, job and AuditLog

RawEvent window
  └─ Consolidate Once
       ├─ Evidence
       ├─ TaskCheckpoint
       └─ LongTermCandidate[]

LongTermCandidate + Evidence
  └─ deterministic governance
       ├─ LongTermMemory
       └─ MemoryVersion

LongTermMemory
  ├─ MemoryUsageStats
  ├─ MemoryLifecycleState
  ├─ MemoryDeletionRequest
  └─ MemoryIndexProjection ──> memory_id only

RetrievalPlan + active LongTermMemory
  └─ ContextPackage
```

`Evidence`、`TaskCheckpoint` 和 `LongTermCandidate[]` 是同一次 Consolidate Once 对同一原始事件窗口生成的兄弟结果。它们不是前后转换关系；尤其禁止从 `TaskCheckpoint` 或恢复摘要生成长期候选。

## 对象职责

| 对象 | 职责 | 身份与关键关系 | 生命周期/约束 |
|---|---|---|---|
| `TenantContext` | 承载服务端认证产生的租户、主体、认证来源和追踪身份 | 所有服务和 Port 的第一个安全参数 | 只读；请求正文和 LLM 无权创建或覆盖；缺失时 fail closed |
| `RawEvent` | 原样保存用户消息、文件、工具结果和来源信息 | `(tenant_id, event_id)`；可关联 session/task/trace | 不可变；剪枝不删除；作为 Evidence 和候选的事实来源 |
| `WorkingMemory` | 保存当前请求/任务正在执行的可观察状态 | `(tenant_id, workspace_id)`；引用激活的 STM/LTM 和事件 | 请求级可变对象；任务结束释放；不直接转成 STM/LTM |
| `TaskMemory` | 当前任务连续性的聚合根和当前快照 | `(tenant_id, task_memory_id)`，按 `tenant_id + task_id` 恢复 | active/suspended/completed/expired；任务完成或 TTL 后释放 |
| `TaskCheckpoint` | 标记任务可恢复位置，保存阶段、恢复摘要、中间状态和未完成问题 | `(tenant_id, checkpoint_id)`；唯一 `(tenant_id, task_id, checkpoint_no)` | 历史追加；不反复摘要旧检查点；不生成 LTM |
| `Evidence` | 绑定候选或主记录到原始事件、窗口、文件/工具来源 | `(tenant_id, evidence_id)`；引用 RawEvent 范围 | 内容最小化、可追溯；删除时按当前租户清理关联 |
| `LongTermCandidate` | 从原始窗口抽取、等待确定性治理的长期素材 | `(tenant_id, candidate_id)`；引用 Evidence 和 consolidate batch | 不是主记录；可 CREATE/REFINE/CORRECT/MERGE/SUPERSEDE/DEFER/IGNORE |
| `LongTermMemory` | PostgreSQL 中长期内容的唯一事实来源 | `(tenant_id, memory_id)`；租户内稳定键唯一 | active/superseded/archived/pending_delete/tombstoned；带作用域、证据、有效期 |
| `MemoryVersion` | 保留主记录内容变更、操作和替代关系的审计版本 | `(tenant_id, memory_id, version)` | 只追加；由确定性代码递增；索引版本与其绑定 |
| `MemoryUsageStats` | 高频记录召回、实际采用、确认、纠正和检索权重 | `(tenant_id, memory_id)` | 不触发内容版本；供排序和 GC 使用 |
| `MemoryLifecycleState` | 保存记录大小、保护、保留等级和淘汰资格 | `(tenant_id, memory_id)` | GC 状态对象，不是长期内容字段 |
| `MemoryDeletionRequest` | 编排明确删除、保留到期和合规清理 | `(tenant_id, deletion_request_id)`，绑定 memory ID | pending_delete → tombstoned → purged；审计不保留正文 |
| `MemoryIndexProjection` | 记录 exact/vector/graph/cache 的派生投影状态 | `(tenant_id, memory_id, version, index_type)` | 只存访问引用；pending/ready/stale/rebuilding/deleted；可重建 |
| `ContextPackage` | 向当前 Agent 交付少量、已验证且可解释的上下文 | 包含 memory ID、内容补丁、来源、命中理由和控制元信息 | 由代码去重、排序、预算控制；不能直接返回索引原始结果 |
| `RetrievalPlan` | 表达“需要查什么”，供确定性检索器执行 | 子查询、类型、作用域、实体、关系、时间和证据需求 | 可由 LLM 建议；不能决定最终记录、tenant 或权限 |
| `AuditLog` | 记录允许/拒绝操作、主体、追踪、目标哈希和状态迁移 | `(tenant_id, audit_id)` | 最小化；不得泄露另一租户或已删除正文 |

## 三层记忆边界

- Working Memory 回答“现在做什么”，包含任务状态、对话窗口、工具/文件结果、即时指令和已排除方向。
- Short-Term Memory 回答“任务怎样继续”，由 TaskMemory 与追加的 TaskCheckpoint 表达。
- Long-Term Memory 回答“未来任务仍需记住什么”，只接受原始事件窗口产生并通过治理的候选。

## 主记录与访问路径

exact key、pgvector、PostgreSQL 图节点/边和 Redis cache 仅返回 `memory_id`。最终结果必须以 `tenant_id + memory_id` 回读 active LongTermMemory，并校验作用域、有效期、版本和权限。
