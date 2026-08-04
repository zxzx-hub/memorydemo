# 测试矩阵

| 场景 | 层级 | 关键夹具/故障注入 | 必须断言 | 计划阶段 |
|---|---|---|---|---|
| 正常写入 | integration | 已认证 tenant A、单条用户事件 | RawEvent 不可变落库，WorkingMemory 更新，审计同租户 | write |
| 幂等写入 | integration | 同 tenant、同 idempotency key 重试 | 不重复事件；返回同一逻辑结果；不同载荷冲突为 409 | write |
| 游标推进 | integration | 游标后新增窗口 | 只处理新增事件；三结果全部保存后推进到窗口末端 | Consolidate |
| 收束失败回滚 | integration | Evidence/checkpoint/candidate 任一保存失败 | 原始事件保留、三结果无半写、游标不推进、可重试 | Consolidate |
| 短期任务恢复 | integration/security | A/B 相同 task ID 和 checkpoint_no | 只按 tenant + task 恢复；不重放另一租户 | STM |
| 长期候选治理 | unit/integration | 重复、冲突、低价值、证据缺失 | 确定性动作正确；候选源自 RawEvent/Evidence；LLM 不能落库 | Governance |
| 精确检索 | integration/security | 相同 memory key 的 A/B 记录 | exact 只返回当前租户 memory ID，随后回读 active 主记录 | read |
| 向量检索 | integration/security | 相似内容、索引含双租户 | metadata tenant 过滤；结果回读主记录；阈值/排序正确 | read |
| 图谱检索 | integration/security | 同名节点、关系和多跳边 | 每一步遍历同租户；关系 memory ID 回读 active 主记录 | read |
| Context Package | unit/integration | 重复候选、预算、过期记录 | 权限过滤、去重、排序、截断、来源和命中原因完整 | read |
| TTL | integration | 过期 TaskMemory、未过期记录 | 只释放当前租户过期 STM；保护记录不受影响 | gc |
| 用户删除 | integration/security | A/B 同 memory ID，各类投影 | A 经三阶段清理正文/证据/索引/cache；B 不变；审计无正文 | gc |
| 索引失败 | integration | vector/graph job 失败后重试 | 主记录仍提交；投影标记失败/重建；不跨租户 | governance/read |
| 双租户隔离 | security | A/B 共用所有业务 ID、内容不同 | write/read/resume/gc/rebuild 全链路不串租户 | security gate |
| 后台任务隔离 | security | 无 tenant job、伪造 tenant、A/B 重建 | 缺失 tenant 拒绝；任务只扫描冻结租户；审计安全 | jobs |
| 跨租户资源 ID 返回 NOT_FOUND | security/API | tenant A 请求 tenant B 的 memory/task ID | 对外 404，响应不暴露存在性；内部最小拒绝审计 | API |
| TenantContext 不可变 | unit | frozen context 与额外字段 | 修改失败；来源枚举合法；业务正文没有 tenant 字段 | foundation |
| 健康与就绪 | unit/integration | 成功/失败探针 | health 不访问依赖；ready 全成功为 200，任一失败为 503 | foundation |
| LLM schema 与降级 | unit | 非法 JSON、tenant 注入、超时 | 输出拒绝；状态无变化；规则/Mock 路径继续 | LLM |

## 发布门禁

每个阶段运行 unit、integration 和适用的 security 测试。MVP 发布前必须让双租户 Validation Harness、删除全级联、索引失败重建和完整闭环 demo 全部通过；禁止用 skip/xfail 掩盖架构不变量失败。
