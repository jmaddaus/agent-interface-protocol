from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from agent_interface_protocol import OrchestrationContext


def test_round_trip_with_all_fields():
    ctx = OrchestrationContext(
        run_id="run-1",
        root_handoff_id="h-root",
        parent_step_id="s-parent",
        step_id="s-1",
        phase="planner",
        capability="pd_authoring",
        fanout_group_id="g-1",
        checkpoint_id="ck-1",
        extra={"trace": {"id": "t-1"}},
    )
    payload = ctx.to_payload()
    assert payload == {
        "run_id": "run-1",
        "root_handoff_id": "h-root",
        "parent_step_id": "s-parent",
        "step_id": "s-1",
        "phase": "planner",
        "capability": "pd_authoring",
        "fanout_group_id": "g-1",
        "checkpoint_id": "ck-1",
        "extra": {"trace": {"id": "t-1"}},
    }
    assert OrchestrationContext.from_payload(payload) == ctx


def test_optional_fields_default_cleanly():
    ctx = OrchestrationContext()
    assert ctx.run_id == ""
    assert ctx.root_handoff_id == ""
    assert ctx.parent_step_id == ""
    assert ctx.step_id == ""
    assert ctx.phase == ""
    assert ctx.capability == ""
    assert ctx.fanout_group_id == ""
    assert ctx.checkpoint_id == ""
    assert dict(ctx.extra) == {}
    assert OrchestrationContext.from_payload({}) == ctx


def test_is_immutable():
    ctx = OrchestrationContext(run_id="r1", extra={"a": 1})
    with pytest.raises(FrozenInstanceError):
        ctx.run_id = "r2"  # type: ignore[misc]
    with pytest.raises(TypeError):
        ctx.extra["a"] = 2  # type: ignore[index]


def test_rejects_unknown_field():
    with pytest.raises(ValueError, match="unknown OrchestrationContext field"):
        OrchestrationContext.from_payload({"run_id": "r1", "tenant": "x"})


def test_rejects_wrong_typed_fields():
    with pytest.raises(ValueError, match="must be a string"):
        OrchestrationContext.from_payload({"run_id": 1})
    with pytest.raises(ValueError, match="must be a string"):
        OrchestrationContext.from_payload({"phase": ["planner"]})
    with pytest.raises(ValueError, match="must be a mapping"):
        OrchestrationContext.from_payload({"extra": [1, 2]})
