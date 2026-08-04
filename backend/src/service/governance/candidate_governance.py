"""Deterministic long-term candidate governance and canonical writes."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from hashlib import sha256

from domain.enums import GovernanceAction, IndexStatus, IndexType, MemoryStatus
from domain.models import (
    AuditLog,
    GovernanceChecks,
    GovernanceSuggestion,
    LongTermCandidate,
    LongTermMemory,
    MemoryVersion,
    Scope,
)
from domain.results import GovernanceResult
from ports.governance_advisor import GovernanceAdvisor
from ports.governance_store import (
    GovernanceTransaction,
    GovernanceUnitOfWorkFactory,
)
from service.auth.tenant_context import TenantContext
from service.core.clock import Clock
from service.core.errors import ResourceNotFoundError
from service.governance.projection_planner import ProjectionPlanner


def _stable_id(prefix: str, *parts: str) -> str:
    digest = sha256("\x1f".join(parts).encode()).hexdigest()[:32]
    return f"{prefix}_{digest}"


def _content_hash(content: str) -> str:
    return sha256(content.strip().encode()).hexdigest()


def _target_hash(*parts: str) -> str:
    return sha256("\x1f".join(parts).encode()).hexdigest()


def _ordered_union(*groups: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for group in groups for value in group))


@dataclass(frozen=True, slots=True)
class GovernancePolicy:
    minimum_confidence: float = 0.6
    minimum_future_value: float = 0.5
    minimum_explicitness: float = 0.5
    maximum_staleness: float = 0.95
    blocked_sensitivities: tuple[str, ...] = ("sensitive", "restricted")
    allowed_scope_types: tuple[str, ...] = (
        "user",
        "project",
        "workspace",
        "agent",
    )


class CandidateGovernanceService:
    """Revalidate suggestions and apply legal canonical state transitions."""

    _TERMINAL_STATUSES = frozenset({"governed", "deferred", "ignored"})

    def __init__(
        self,
        unit_of_work_factory: GovernanceUnitOfWorkFactory,
        advisor: GovernanceAdvisor,
        policy: GovernancePolicy,
        projection_planner: ProjectionPlanner,
        clock: Clock,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._advisor = advisor
        self._policy = policy
        self._projection_planner = projection_planner
        self._clock = clock

    async def govern(
        self,
        ctx: TenantContext,
        candidate_id: str,
    ) -> GovernanceResult:
        async with self._unit_of_work_factory.open(ctx) as transaction:
            state = await transaction.get_candidate_for_update(ctx, candidate_id)
            if state is None:
                raise ResourceNotFoundError
            candidate = state.candidate
            suggestion = await self._advisor.suggest(ctx, candidate)
            evidence = await transaction.existing_evidence_ids(
                ctx,
                candidate.evidence_ids,
            )
            exact = await transaction.find_exact_active(ctx, candidate)
            semantic = tuple(await transaction.find_semantic_active(ctx, candidate))
            checks = self._checks(
                ctx,
                candidate,
                evidence,
                exact,
                semantic,
            )

            if state.governance_status in self._TERMINAL_STATUSES:
                action = state.governance_action or GovernanceAction.DEFER
                index_types: tuple[IndexType, ...] = ()
                if (
                    state.governed_memory_id is not None
                    and state.governed_memory_version is not None
                ):
                    index_types = await transaction.list_projection_types(
                        ctx,
                        state.governed_memory_id,
                        state.governed_memory_version,
                    )
                return GovernanceResult(
                    candidate_id=candidate_id,
                    action=action,
                    status=state.governance_status,
                    reason=state.governance_reason or "already_governed",
                    checks=checks,
                    memory_id=state.governed_memory_id,
                    version=state.governed_memory_version,
                    index_types=index_types,
                    idempotent=True,
                )

            invalid_result = await self._quality_gate(
                ctx,
                transaction,
                candidate,
                checks,
                suggestion,
            )
            if invalid_result is not None:
                return invalid_result

            duplicate_targets = await self._validate_targets(
                ctx,
                transaction,
                candidate,
                suggestion.possible_duplicates,
                "duplicate",
            )
            conflict_targets = await self._validate_targets(
                ctx,
                transaction,
                candidate,
                suggestion.possible_conflicts,
                "conflict",
            )
            action = suggestion.suggested_action

            if action is GovernanceAction.CREATE:
                if exact is not None and exact.content_hash == _content_hash(
                    candidate.content
                ):
                    return await self._finish_without_memory(
                        ctx,
                        transaction,
                        candidate,
                        GovernanceAction.IGNORE,
                        "exact_duplicate",
                        checks,
                    )
                if exact is not None:
                    return await self._finish_without_memory(
                        ctx,
                        transaction,
                        candidate,
                        GovernanceAction.DEFER,
                        "exact_conflict_requires_resolution",
                        checks,
                    )
                if semantic:
                    return await self._finish_without_memory(
                        ctx,
                        transaction,
                        candidate,
                        GovernanceAction.DEFER,
                        "semantic_duplicate_requires_resolution",
                        checks,
                    )
                return await self._create(
                    ctx,
                    transaction,
                    candidate,
                    checks,
                    GovernanceAction.CREATE,
                )

            if action in (GovernanceAction.DEFER, GovernanceAction.IGNORE):
                return await self._finish_without_memory(
                    ctx,
                    transaction,
                    candidate,
                    action,
                    suggestion.reason,
                    checks,
                )

            target = self._select_target(
                action,
                exact,
                semantic,
                duplicate_targets,
                conflict_targets,
            )
            if target is None:
                return await self._finish_without_memory(
                    ctx,
                    transaction,
                    candidate,
                    GovernanceAction.DEFER,
                    "active_target_required",
                    checks,
                )
            checks = checks.model_copy(update={"active_version": target.version})

            if action is GovernanceAction.SUPERSEDE:
                return await self._supersede(
                    ctx,
                    transaction,
                    candidate,
                    target,
                    checks,
                )
            return await self._update_existing(
                ctx,
                transaction,
                candidate,
                target,
                action,
                checks,
            )

    async def _quality_gate(
        self,
        ctx: TenantContext,
        transaction: GovernanceTransaction,
        candidate: LongTermCandidate,
        checks: GovernanceChecks,
        suggestion: GovernanceSuggestion,
    ) -> GovernanceResult | None:
        if not checks.evidence_valid:
            return await self._finish_without_memory(
                ctx,
                transaction,
                candidate,
                GovernanceAction.DEFER,
                "evidence_not_found",
                checks,
            )
        if not checks.scope_valid:
            return await self._finish_without_memory(
                ctx,
                transaction,
                candidate,
                GovernanceAction.IGNORE,
                "scope_not_allowed",
                checks,
            )
        if candidate.sensitivity in self._policy.blocked_sensitivities:
            return await self._finish_without_memory(
                ctx,
                transaction,
                candidate,
                GovernanceAction.IGNORE,
                "sensitivity_blocked",
                checks,
            )
        if not checks.validity_valid or (
            checks.staleness_score >= self._policy.maximum_staleness
        ):
            return await self._finish_without_memory(
                ctx,
                transaction,
                candidate,
                GovernanceAction.IGNORE,
                "candidate_stale_or_invalid",
                checks,
            )
        if checks.future_value < self._policy.minimum_future_value:
            return await self._finish_without_memory(
                ctx,
                transaction,
                candidate,
                GovernanceAction.IGNORE,
                "insufficient_future_value",
                checks,
            )
        if (
            candidate.confidence < self._policy.minimum_confidence
            or checks.explicitness < self._policy.minimum_explicitness
            or suggestion.confidence < self._policy.minimum_confidence
        ):
            return await self._finish_without_memory(
                ctx,
                transaction,
                candidate,
                GovernanceAction.DEFER,
                "insufficient_confidence_or_explicitness",
                checks,
            )
        return None

    def _checks(
        self,
        ctx: TenantContext,
        candidate: LongTermCandidate,
        evidence: frozenset[str],
        exact: LongTermMemory | None,
        semantic: Sequence[LongTermMemory],
    ) -> GovernanceChecks:
        now = self._clock.now()
        scope_valid = candidate.scope.type in self._policy.allowed_scope_types
        if candidate.scope.type == "user":
            scope_valid = scope_valid and candidate.scope.id == ctx.principal_id
        validity_valid = (
            candidate.valid_from is None or candidate.valid_from <= now
        ) and (candidate.valid_to is None or candidate.valid_to > now)
        semantic_ids = tuple(
            item.memory_id
            for item in semantic
            if exact is None or item.memory_id != exact.memory_id
        )
        conflict_ids: tuple[str, ...] = ()
        if exact is not None and exact.content_hash != _content_hash(candidate.content):
            conflict_ids = (exact.memory_id,)
        return GovernanceChecks(
            schema_valid=True,
            evidence_valid=evidence == frozenset(candidate.evidence_ids),
            future_value=candidate.importance,
            explicitness=candidate.explicitness,
            sensitivity=candidate.sensitivity,
            scope_valid=scope_valid,
            exact_duplicate_id=exact.memory_id if exact is not None else None,
            semantic_duplicate_ids=semantic_ids,
            conflict_ids=conflict_ids,
            validity_valid=validity_valid,
            staleness_score=candidate.staleness_score,
            active_version=exact.version if exact is not None else None,
        )

    async def _validate_targets(
        self,
        ctx: TenantContext,
        transaction: GovernanceTransaction,
        candidate: LongTermCandidate,
        target_ids: Sequence[str],
        relation: str,
    ) -> tuple[LongTermMemory, ...]:
        targets = []
        for memory_id in dict.fromkeys(target_ids):
            target = await transaction.get_memory_for_update(ctx, memory_id)
            if target is None:
                await self._append_audit(
                    ctx,
                    transaction,
                    candidate.candidate_id,
                    f"REJECT_{relation.upper()}_TARGET",
                    "rejected",
                    f"{relation}_target_not_found",
                )
                await transaction.commit()
                raise ResourceNotFoundError
            if (
                target.status is not MemoryStatus.ACTIVE
                or target.memory_type is not candidate.memory_type
                or target.scope != candidate.scope
            ):
                await self._append_audit(
                    ctx,
                    transaction,
                    candidate.candidate_id,
                    f"REJECT_{relation.upper()}_TARGET",
                    "rejected",
                    f"{relation}_target_invalid",
                )
                await transaction.commit()
                raise ResourceNotFoundError
            if relation == "duplicate" and not (
                target.content_hash == _content_hash(candidate.content)
                or (
                    candidate.semantic_fingerprint is not None
                    and target.semantic_fingerprint == candidate.semantic_fingerprint
                )
                or target.normalized_key == candidate.normalized_key
            ):
                return ()
            targets.append(target)
        return tuple(targets)

    @staticmethod
    def _select_target(
        action: GovernanceAction,
        exact: LongTermMemory | None,
        semantic: Sequence[LongTermMemory],
        duplicate_targets: Sequence[LongTermMemory],
        conflict_targets: Sequence[LongTermMemory],
    ) -> LongTermMemory | None:
        if action is GovernanceAction.MERGE:
            candidates = (*duplicate_targets, *semantic, exact)
        elif action is GovernanceAction.SUPERSEDE:
            candidates = (*conflict_targets, exact)
        else:
            candidates = (*conflict_targets, *duplicate_targets, exact, *semantic)
        return next((item for item in candidates if item is not None), None)

    async def _create(
        self,
        ctx: TenantContext,
        transaction: GovernanceTransaction,
        candidate: LongTermCandidate,
        checks: GovernanceChecks,
        action: GovernanceAction,
        *,
        supersedes_id: str | None = None,
        commit: bool = True,
    ) -> GovernanceResult:
        now = self._clock.now()
        memory = LongTermMemory(
            memory_id=_stable_id(
                "memory",
                ctx.tenant_id,
                candidate.candidate_id,
            ),
            memory_type=candidate.memory_type,
            owner=candidate.owner or Scope(type="user", id=ctx.principal_id),
            scope=candidate.scope,
            content=candidate.content.strip(),
            normalized_key=candidate.normalized_key,
            evidence_ids=candidate.evidence_ids,
            confidence=candidate.confidence,
            importance=candidate.importance,
            explicitness=candidate.explicitness,
            version=1,
            status=MemoryStatus.ACTIVE,
            valid_from=candidate.valid_from or now,
            valid_to=candidate.valid_to,
            type_payload=candidate.type_payload,
            content_hash=_content_hash(candidate.content),
            source_event_ids=candidate.source_event_ids,
            semantic_fingerprint=candidate.semantic_fingerprint,
            language=candidate.language,
            last_verified_at=now,
            staleness_score=candidate.staleness_score,
            supersedes_id=supersedes_id,
            conflict_ids=candidate.possible_conflicts,
        )
        await transaction.create_memory(ctx, memory)
        await transaction.add_version(
            ctx,
            memory,
            self._version(memory, action, now),
        )
        index_types = await self._queue_projections(ctx, transaction, memory)
        await transaction.set_candidate_result(
            ctx,
            candidate.candidate_id,
            "governed",
            action,
            action.value,
            memory.memory_id,
            memory.version,
        )
        await self._append_audit(
            ctx,
            transaction,
            candidate.candidate_id,
            f"GOVERNANCE_{action.value.upper()}",
            "success",
            action.value,
            memory.memory_id,
        )
        if commit:
            await transaction.commit()
        return GovernanceResult(
            candidate_id=candidate.candidate_id,
            action=action,
            status="governed",
            reason=action.value,
            checks=checks,
            memory_id=memory.memory_id,
            version=memory.version,
            index_types=index_types,
        )

    async def _update_existing(
        self,
        ctx: TenantContext,
        transaction: GovernanceTransaction,
        candidate: LongTermCandidate,
        target: LongTermMemory,
        action: GovernanceAction,
        checks: GovernanceChecks,
    ) -> GovernanceResult:
        now = self._clock.now()
        content = candidate.content.strip()
        if action in (GovernanceAction.REFINE, GovernanceAction.MERGE):
            if content not in target.content:
                content = f"{target.content.rstrip()}\n{content}"
            else:
                content = target.content
        updated = target.model_copy(
            update={
                "content": content,
                "content_hash": _content_hash(content),
                "evidence_ids": _ordered_union(
                    target.evidence_ids,
                    candidate.evidence_ids,
                ),
                "source_event_ids": _ordered_union(
                    target.source_event_ids,
                    candidate.source_event_ids,
                ),
                "confidence": max(target.confidence, candidate.confidence),
                "importance": max(target.importance, candidate.importance),
                "explicitness": max(
                    target.explicitness,
                    candidate.explicitness,
                ),
                "semantic_fingerprint": candidate.semantic_fingerprint
                or target.semantic_fingerprint,
                "type_payload": {
                    **target.type_payload,
                    **candidate.type_payload,
                },
                "version": target.version + 1,
                "last_verified_at": now,
                "staleness_score": min(
                    target.staleness_score,
                    candidate.staleness_score,
                ),
            }
        )
        await self._stale_old_projections(ctx, transaction, target)
        await transaction.update_memory(
            ctx,
            updated,
            expected_version=target.version,
        )
        await transaction.add_version(
            ctx,
            updated,
            self._version(updated, action, now),
        )
        index_types = await self._queue_projections(ctx, transaction, updated)
        await transaction.set_candidate_result(
            ctx,
            candidate.candidate_id,
            "governed",
            action,
            action.value,
            updated.memory_id,
            updated.version,
        )
        await self._append_audit(
            ctx,
            transaction,
            candidate.candidate_id,
            f"GOVERNANCE_{action.value.upper()}",
            "success",
            action.value,
            updated.memory_id,
        )
        await transaction.commit()
        return GovernanceResult(
            candidate_id=candidate.candidate_id,
            action=action,
            status="governed",
            reason=action.value,
            checks=checks,
            memory_id=updated.memory_id,
            version=updated.version,
            index_types=index_types,
        )

    async def _supersede(
        self,
        ctx: TenantContext,
        transaction: GovernanceTransaction,
        candidate: LongTermCandidate,
        target: LongTermMemory,
        checks: GovernanceChecks,
    ) -> GovernanceResult:
        now = self._clock.now()
        retired_key = (f"{target.normalized_key}#superseded:{target.memory_id}")[:512]
        retired = target.model_copy(
            update={
                "status": MemoryStatus.SUPERSEDED,
                "version": target.version + 1,
                "valid_to": now,
                "normalized_key": retired_key,
            }
        )
        await self._stale_old_projections(ctx, transaction, target)
        await transaction.update_memory(
            ctx,
            retired,
            expected_version=target.version,
        )
        await transaction.add_version(
            ctx,
            retired,
            self._version(retired, GovernanceAction.SUPERSEDE, now),
        )
        result = await self._create(
            ctx,
            transaction,
            candidate,
            checks,
            GovernanceAction.SUPERSEDE,
            supersedes_id=target.memory_id,
            commit=False,
        )
        if result.memory_id is None:
            raise RuntimeError("Supersede did not create a canonical record.")
        await transaction.link_superseded(
            ctx,
            target.memory_id,
            result.memory_id,
            retired.version,
        )
        await transaction.commit()
        return result

    async def _finish_without_memory(
        self,
        ctx: TenantContext,
        transaction: GovernanceTransaction,
        candidate: LongTermCandidate,
        action: GovernanceAction,
        reason: str,
        checks: GovernanceChecks,
    ) -> GovernanceResult:
        status = "ignored" if action is GovernanceAction.IGNORE else "deferred"
        await transaction.set_candidate_result(
            ctx,
            candidate.candidate_id,
            status,
            action,
            reason,
            None,
            None,
        )
        await self._append_audit(
            ctx,
            transaction,
            candidate.candidate_id,
            f"GOVERNANCE_{action.value.upper()}",
            status,
            reason,
        )
        await transaction.commit()
        return GovernanceResult(
            candidate_id=candidate.candidate_id,
            action=action,
            status=status,
            reason=reason,
            checks=checks,
        )

    async def _queue_projections(
        self,
        ctx: TenantContext,
        transaction: GovernanceTransaction,
        memory: LongTermMemory,
    ) -> tuple[IndexType, ...]:
        index_types = self._projection_planner.plan(memory)
        for index_type in index_types:
            await transaction.add_projection(
                ctx,
                memory.memory_id,
                memory.version,
                index_type,
                IndexStatus.PENDING,
            )
            await transaction.add_outbox_job(
                ctx,
                _stable_id(
                    "job",
                    ctx.tenant_id,
                    memory.memory_id,
                    str(memory.version),
                    index_type.value,
                ),
                "build_memory_index",
                {
                    "tenant_id": ctx.tenant_id,
                    "memory_id": memory.memory_id,
                    "version": memory.version,
                    "index_type": index_type.value,
                },
            )
        return index_types

    async def _stale_old_projections(
        self,
        ctx: TenantContext,
        transaction: GovernanceTransaction,
        memory: LongTermMemory,
    ) -> None:
        index_types = await transaction.list_projection_types(
            ctx,
            memory.memory_id,
            memory.version,
        )
        for index_type in index_types:
            await transaction.set_projection_status(
                ctx,
                memory.memory_id,
                memory.version,
                index_type,
                IndexStatus.STALE,
            )

    @staticmethod
    def _version(
        memory: LongTermMemory,
        action: GovernanceAction,
        created_at: object,
    ) -> MemoryVersion:
        from datetime import datetime

        if not isinstance(created_at, datetime):
            raise TypeError("Version timestamp must be a datetime.")
        return MemoryVersion(
            memory_id=memory.memory_id,
            version=memory.version,
            content_hash=memory.content_hash,
            operation=action.value,
            created_at=created_at,
            snapshot=memory.model_dump(mode="json"),
        )

    async def _append_audit(
        self,
        ctx: TenantContext,
        transaction: GovernanceTransaction,
        candidate_id: str,
        operation: str,
        result: str,
        reason: str,
        memory_id: str | None = None,
    ) -> None:
        target = [ctx.tenant_id, candidate_id]
        if memory_id is not None:
            target.append(memory_id)
        await transaction.append_audit(
            ctx,
            AuditLog(
                audit_id=_stable_id(
                    "audit",
                    ctx.tenant_id,
                    candidate_id,
                    operation,
                ),
                operation=operation,
                result=result,
                principal_id=ctx.principal_id,
                trace_id=ctx.trace_id,
                target_hash=_target_hash(*target),
                reason_code=reason,
            ),
        )
