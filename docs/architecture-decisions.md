# 架构决策记录

## ADR-001：TenantContext 是不可覆盖的第一身份键

- **状态**：Accepted
- **决策**：认证适配器产生 frozen `TenantContext`；服务、Repository、索引、任务和审计显式携带 tenant ID。客户端正文无 tenant 字段。
- **原因**：user/task/memory 等业务 ID 只在租户内唯一，应用层事后过滤不能提供隔离保证。
- **后果**：缺失或不一致 fail closed；跨租户资源对外 NOT_FOUND；所有测试夹具必须支持同名双租户。

## ADR-002：只保留三层记忆

- **状态**：Accepted
- **决策**：Working Memory 服务当前执行，Short-Term Memory 服务同一任务恢复，Long-Term Memory 保存治理后的跨任务信息。
- **原因**：三种生命周期与读取模式不同。
- **后果**：六个内部动作不是第四层；短期快照禁止二次压缩为长期记忆。

## ADR-003：Consolidate Once 生成三类兄弟结果

- **状态**：Accepted
- **决策**：一个租户内增量窗口只理解一次，并行形成 Evidence、TaskCheckpoint 和 LongTermCandidate 列表；全部持久化后推进游标。
- **原因**：避免重复理解和摘要链的信息损失。
- **后果**：需要批次幂等键、窗口边界、事务/UoW 与失败注入测试。

## ADR-004：PostgreSQL 长期主记录是唯一事实来源

- **状态**：Accepted
- **决策**：exact、vector、graph、cache 只保存访问投影并返回 memory ID，最终回读 active 主记录。
- **原因**：索引可丢失、延迟或重建，不应改变内容真值。
- **后果**：主记录先提交；索引通过 Outbox/JobDispatcher 异步投影；索引失败不回滚主记录。

## ADR-005：PostgreSQL 图表实现 GraphStore MVP

- **状态**：Accepted
- **决策**：第一版用租户化节点表和边表实现关系检索，同时仅依赖 `GraphStore` Port。
- **原因**：减少本地依赖和运维面，保留未来替换图数据库的边界。
- **后果**：节点、边、遍历和唯一约束均含 tenant ID；不向领域服务暴露 SQL。

## ADR-006：JobDispatcher 不绑定 Celery

- **状态**：Accepted
- **决策**：核心只依赖 `JobDispatcher`，MVP 提供同步实现或数据库 Outbox Worker。
- **原因**：保持本地可运行、事务可追踪，避免过早绑定任务框架。
- **后果**：任务载荷冻结单一 tenant ID；缺失 tenant 的任务拒绝执行。

## ADR-007：MockLLMClient 是默认 LLM Adapter

- **状态**：Accepted
- **决策**：默认适配器确定性返回严格 schema；真实模型是可选依赖。
- **原因**：测试和 demo 必须离线可重复，LLM 不能成为状态机。
- **后果**：代码验证证据、权限、版本和动作；模型错误有确定性降级。

## ADR-008：健康与就绪探针分离

- **状态**：Accepted
- **决策**：`/health` 仅证明进程存活；`/ready` 实际探测 PostgreSQL 和 Redis。
- **原因**：外部依赖故障不应误判进程死亡，但流量不能进入未就绪实例。
- **后果**：就绪响应隐藏连接细节；Compose 使用相同语义。

## ADR-009：业务骨架明确失败，不伪造成功

- **状态**：Accepted
- **决策**：本阶段注册三个 API 契约，但未绑定 `MemoryService` 时返回结构化 `501`。
- **原因**：保证路由和安全边界可检查，同时不把空实现当成业务完成。
- **后果**：后续阶段通过依赖注入替换适配器；基础验收只要求健康/就绪和应用启动。

## ADR-010：开发身份头只存在于显式开发解析器

- **状态**：Accepted
- **决策**：本地可启用 `DevelopmentTenantResolver` 从专用请求头读取测试身份，再创建不可变 TenantContext；Repository 永远只接收 TenantContext。
- **原因**：支持本地 API 调试，同时避免把普通 Header 或请求正文变成持久层租户来源。
- **后果**：默认关闭；生产环境禁止启用；缺失开发身份头时 fail closed。

## ADR-011：所有关系键使用租户复合外键

- **状态**：Accepted
- **决策**：业务表以 tenant ID 开始主键、唯一键和外键；图节点、边、向量、Outbox 和审计均保存 tenant ID。
- **原因**：数据库必须防止跨租户关系，即使业务 ID 完全相同。
- **后果**：Repository 的首个过滤条件固定为 tenant ID；索引命中后仍需 tenant + memory ID 回读主记录。
