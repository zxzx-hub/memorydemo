# 实施计划入口

详细分阶段计划见 [`docs/implementation-plan.md`](docs/implementation-plan.md)。

## 阶段顺序

1. TenantContext 和基础设施
2. 领域模型与数据库
3. MemoryService.write
4. Consolidate Once
5. 长期候选治理
6. MemoryService.read
7. MemoryService.gc
8. LLM Adapter
9. 多租户验证
10. Demo 和验收

## 当前阶段

当前只交付阶段 1 的工程骨架：可启动 FastAPI、环境配置、PostgreSQL/Redis 就绪探针、三个业务入口的安全失败式契约骨架、开发环境与基础测试。没有实现完整记忆业务或数据库表。

相关说明：

- [领域模型](docs/domain-model.md)
- [API 契约](docs/api-contract.md)
- [架构决策](docs/architecture-decisions.md)
- [测试矩阵](docs/test-matrix.md)

下一阶段从领域模型和 Alembic 业务迁移开始，不得绕过 TenantContext 或提前把派生索引作为内容来源。
