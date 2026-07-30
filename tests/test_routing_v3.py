from __future__ import annotations

from dataclasses import replace

import pytest

from history_dispatcher.classification_types import (
    AgentContext,
    ClassifiedEvent,
    ClassificationConfidence,
    HistoryKind,
)
from history_dispatcher.delivery_state import TargetDeliveryState
from history_dispatcher.routing import (
    LocalArchiveRoutingPolicy,
    ProjectFilterMode,
    RoutePlanner,
    RoutingPlanError,
    RoutingPolicy,
    TelegramRoutingPolicy,
    VaultRoutingPolicy,
    normalize_project_ids,
)
from history_dispatcher.telegram_provider import TelegramTransportBinding


def _event(
    kind: HistoryKind = HistoryKind.TASK_COMPLETION,
    *,
    project_id: str = "proj_example",
    external_dispatchable: bool = True,
) -> ClassifiedEvent:
    return ClassifiedEvent(
        history_kind=kind,
        confidence=ClassificationConfidence.AUTHORITATIVE,
        reason_code="fixture",
        source_schema_family="fixture",
        timestamp="2026-07-28T00:00:00Z",
        session_key="sess_fixture",
        turn_key="turn_fixture",
        parent_thread_key="parent_unknown",
        project_id=project_id,
        project_label="Example",
        agent_context=AgentContext.ROOT,
        source_ordinal=1,
        response_key="resp_fixture",
        text="Visible result",
        text_sha256="a" * 64,
        dedupe_key="b" * 64,
        event_id=f"evt_{kind.value}",
        external_dispatchable=external_dispatchable,
    )


def _target(plan, target_id: str):
    return next(target for target in plan.targets if target.target_id == target_id)


def test_safe_defaults_persist_all_target_decisions_without_dispatch() -> None:
    plan = RoutePlanner(RoutingPolicy()).plan(_event(), config_revision="r1")

    assert [target.target_id for target in plan.targets] == [
        "local_archive",
        "telegram",
        "vault",
    ]
    assert _target(plan, "local_archive").initial_state is TargetDeliveryState.SKIPPED_DISABLED
    assert _target(plan, "telegram").initial_state is TargetDeliveryState.SKIPPED_UNKNOWN
    assert _target(plan, "telegram").reason_code == "telegram_provider_unconfigured"
    assert _target(plan, "vault").initial_state is TargetDeliveryState.SKIPPED_DISABLED


def test_all_requested_targets_can_be_pending_with_native_telegram() -> None:
    policy = RoutingPolicy(
        local_archive=LocalArchiveRoutingPolicy(
            include_subagent_completion=True,
            include_intermediate_update=True,
        ),
        telegram=TelegramRoutingPolicy(
            include_subagent_completion=True,
            include_intermediate_update=True,
            include_task_completion=True,
            binding=TelegramTransportBinding.history_dispatcher(
                credential_ref="telegram_primary",
                recipient_refs=("status_admin",),
            ),
        ),
        vault=VaultRoutingPolicy(
            include_subagent_completion=True,
            include_intermediate_update=True,
            include_task_completion=True,
        ),
    )

    subagent = RoutePlanner(policy).plan(
        _event(HistoryKind.SUBAGENT_COMPLETION),
        config_revision="r2",
    )
    completion = RoutePlanner(policy).plan(_event(), config_revision="r2")

    assert all(
        target.initial_state is TargetDeliveryState.PENDING
        for target in subagent.targets
    )
    assert _target(completion, "telegram").initial_state is TargetDeliveryState.PENDING
    assert _target(completion, "vault").initial_state is TargetDeliveryState.PENDING
    assert _target(completion, "local_archive").initial_state is TargetDeliveryState.SKIPPED_DISABLED
    assert _target(completion, "telegram").provider_id == "history_dispatcher"


def test_blacklist_and_whitelist_use_exact_case_sensitive_project_ids() -> None:
    binding = TelegramTransportBinding.teebotus()
    blacklist = TelegramRoutingPolicy(
        include_task_completion=True,
        project_filter_mode="blacklist",
        project_ids=("proj_example",),
        binding=binding,
    )
    whitelist = replace(
        blacklist,
        project_filter_mode=ProjectFilterMode.WHITELIST,
    )

    blocked = RoutePlanner(RoutingPolicy(telegram=blacklist)).plan(
        _event(project_id="proj_example"), config_revision="r3"
    )
    substring = RoutePlanner(RoutingPolicy(telegram=blacklist)).plan(
        _event(project_id="proj_example_docs"), config_revision="r3"
    )
    case_variant = RoutePlanner(RoutingPolicy(telegram=blacklist)).plan(
        _event(project_id="PROJ_EXAMPLE"), config_revision="r3"
    )
    allowed = RoutePlanner(RoutingPolicy(telegram=whitelist)).plan(
        _event(project_id="proj_example"), config_revision="r3"
    )
    empty_whitelist = RoutePlanner(
        RoutingPolicy(
            telegram=replace(whitelist, project_ids=()),
        )
    ).plan(_event(project_id="proj_example"), config_revision="r3")

    assert _target(blocked, "telegram").initial_state is TargetDeliveryState.SKIPPED_FILTERED
    assert _target(substring, "telegram").initial_state is TargetDeliveryState.PENDING
    assert _target(case_variant, "telegram").initial_state is TargetDeliveryState.PENDING
    assert _target(allowed, "telegram").initial_state is TargetDeliveryState.PENDING
    assert _target(empty_whitelist, "telegram").initial_state is TargetDeliveryState.SKIPPED_FILTERED


def test_unknown_or_internal_events_fail_closed_for_external_targets() -> None:
    policy = RoutingPolicy(
        telegram=TelegramRoutingPolicy(
            include_task_completion=True,
            binding=TelegramTransportBinding.teebotus(),
        ),
        vault=VaultRoutingPolicy(include_task_completion=True),
    )
    internal = RoutePlanner(policy).plan(
        _event(external_dispatchable=False),
        config_revision="r4",
    )
    unknown = RoutePlanner(policy).plan(
        _event(
            HistoryKind.UNKNOWN,
            project_id="proj_unknown",
            external_dispatchable=False,
        ),
        config_revision="r4",
    )

    assert _target(internal, "telegram").initial_state is TargetDeliveryState.SKIPPED_UNKNOWN
    assert _target(internal, "vault").initial_state is TargetDeliveryState.SKIPPED_UNKNOWN
    assert all(
        target.initial_state is not TargetDeliveryState.PENDING
        for target in unknown.targets
    )


def test_provider_and_config_revision_are_part_of_deterministic_plan_hash() -> None:
    event = _event()
    teebotus = RoutingPolicy(
        telegram=TelegramRoutingPolicy(
            include_task_completion=True,
            binding=TelegramTransportBinding.teebotus(),
        )
    )
    native = RoutingPolicy(
        telegram=TelegramRoutingPolicy(
            include_task_completion=True,
            binding=TelegramTransportBinding.history_dispatcher(
                credential_ref="telegram_primary",
                recipient_refs=("status_admin",),
            ),
        )
    )

    first = RoutePlanner(teebotus).plan(event, config_revision="r5")
    repeated = RoutePlanner(teebotus).plan(event, config_revision="r5")
    provider_changed = RoutePlanner(native).plan(event, config_revision="r5")
    revision_changed = RoutePlanner(teebotus).plan(event, config_revision="r6")

    assert first.plan_hash == repeated.plan_hash
    assert first.plan_hash != provider_changed.plan_hash
    assert first.plan_hash != revision_changed.plan_hash


def test_project_filter_validation_is_bounded_and_rejects_glob_syntax() -> None:
    assert normalize_project_ids([" proj_a ", "proj_a", "proj_b"]) == (
        "proj_a",
        "proj_b",
    )
    with pytest.raises(RoutingPlanError, match="unsupported characters"):
        normalize_project_ids(["proj_*"])
    with pytest.raises(RoutingPlanError, match="too many"):
        normalize_project_ids(
            [f"proj_{index}" for index in range(201)]
        )
