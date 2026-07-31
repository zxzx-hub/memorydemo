# API 契约

## 公共约束

- 业务 API 只暴露 `write`、`read`、`gc` 三个入口，另提供 `/health` 与 `/ready`。
- `tenant_id` 来自认证中间件生成的只读 `TenantContext`。任何业务请求正文都不定义可信 `tenant_id` 字段；出现额外 `tenant_id` 时以 schema 错误或上下文不匹配拒绝。
- 客户端通过 `Authorization` 提供可验证凭证，可选通过 `X-Trace-ID` 传递追踪请求；是否采纳客户端 trace ID 由服务端策略决定。
- 所有业务 schema 使用 `extra="forbid"`。所有时间使用带时区 ISO 8601；所有 ID 是不携带租户信息的 opaque string。
- 跨租户资源 ID、已 tombstone 资源和不存在资源统一返回 `404 NOT_FOUND`，不泄露存在性。
- 错误外壳：

```json
{
  "error": {
    "code": "TENANT_CONTEXT_REQUIRED",
    "message": "A trusted tenant context is required.",
    "trace_id": "trace_..."
  }
}
```

## `POST /v1/memory/write`

提交原始事件或请求收束当前新增事件窗口。内部映射到 01 写入、02 暂存和 05 沉淀。

请求示例：

```json
{
  "idempotency_key": "req_20260731_001",
  "workspace_id": "workspace_001",
  "event": {
    "event_id": "event_001",
    "event_type": "user_message",
    "content": "以后技术方案先讲总体架构。",
    "session_id": "session_001",
    "task_id": "task_001",
    "occurred_at": "2026-07-31T10:00:00+08:00",
    "source_refs": []
  },
  "consolidate": {
    "requested": false,
    "reason": null
  }
}
```

响应 `202 Accepted`：

```json
{
  "operation_id": "op_001",
  "event_id": "event_001",
  "workspace_id": "workspace_001",
  "status": "accepted",
  "consolidation_status": "not_requested"
}
```

语义：相同 tenant 与 `idempotency_key` 必须返回同一逻辑结果；只有 Evidence、TaskCheckpoint 和 LongTermCandidate 全部成功保存后才报告游标已推进。

## `POST /v1/memory/read`

执行 META、Express、Quick、Normal 或 Deep 检索，内部映射到 03 唤回和 04 调用。

请求示例：

```json
{
  "mode": "normal",
  "query": "之前技术方案的表达偏好是什么？",
  "task_id": "task_001",
  "memory_id": null,
  "memory_key": null,
  "scope": {
    "type": "user",
    "id": "user_001"
  },
  "memory_types": ["preference"],
  "max_items": 8,
  "need_evidence": false
}
```

响应 `200 OK`：

```json
{
  "context_package": {
    "items": [
      {
        "memory_id": "memory_001",
        "memory_type": "preference",
        "content": "技术方案先讲总体架构，再展开字段和代码。",
        "confidence": 0.96,
        "source_refs": ["evidence_001"],
        "match_reason": "semantic_and_scope_match"
      }
    ],
    "retrieval_mode": "normal",
    "truncated": false
  }
}
```

索引仅返回 memory ID；响应项必须来自 `tenant_id + memory_id` 回读的 active 主记录。

## `POST /v1/memory/gc`

执行 TTL、降权、合并、归档或显式删除，内部只映射到 06 释放。

请求示例：

```json
{
  "action": "delete",
  "memory_id": "memory_001",
  "reason_code": "user_request",
  "idempotency_key": "delete_20260731_001",
  "dry_run": false
}
```

响应 `202 Accepted`：

```json
{
  "operation_id": "op_delete_001",
  "status": "accepted",
  "lifecycle_stage": "pending_delete"
}
```

用户删除只处理当前租户的主记录、版本内容、Evidence 关联、exact/vector/graph/cache；完成 tombstone 后读取统一为 NOT_FOUND。

## 运维端点

### `GET /health`

进程存活探针，不访问外部依赖。成功返回 `200`：

```json
{"status": "ok", "service": "agent-memory-service"}
```

### `GET /ready`

就绪探针，分别检查 PostgreSQL `SELECT 1` 和 Redis `PING`。全部成功返回 `200`；任一失败返回 `503`，响应只含依赖名与安全状态，不含连接串或凭证。

## 状态码

| 状态码 | 场景 |
|---|---|
| 200 | 同步读取或健康成功 |
| 202 | write/gc 已接受 |
| 401 | 缺少或无效认证，无法构造 TenantContext |
| 404 | 不存在、跨租户或已 tombstone |
| 409 | 幂等键载荷冲突、版本并发冲突 |
| 422 | 严格 schema 校验失败，包括正文中的额外 tenant ID |
| 501 | 骨架阶段端点尚未绑定业务实现 |
| 503 | 外部依赖未就绪或服务适配器未绑定 |
