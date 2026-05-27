from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from agent_interface_protocol.agent_interface import (
    AGENT_STEP_EVENT_KINDS,
    AgentStepEvent,
    AgentStepResult,
    HarnessPolicy,
    OrchestrationContext,
    SemanticResult,
    ToolEvent,
)


def _round_trip(event: AgentStepEvent) -> None:
    assert AgentStepEvent.from_payload(event.to_payload()) == event


def test_known_kinds_exposed():
    assert AGENT_STEP_EVENT_KINDS == frozenset({
        "accepted",
        "progress",
        "tool_event",
        "partial_response",
        "question",
        "final",
        "phase_started",
        "phase_completed",
        "checkpoint",
        "evaluation",
    })


def test_accepted_round_trip():
    event = AgentStepEvent(
        kind="accepted",
        handoff_id="h1",
        step_id="s1",
        seq=0,
        ts="2026-05-26T10:00:00Z",
    )
    _round_trip(event)


def test_progress_round_trip():
    event = AgentStepEvent(
        kind="progress",
        handoff_id="h1",
        step_id="s1",
        seq=1,
        body={"fraction": 0.5, "message": "halfway"},
    )
    _round_trip(event)


def test_progress_allows_null_fraction():
    event = AgentStepEvent(
        kind="progress",
        seq=1,
        body={"fraction": None, "message": "ongoing"},
    )
    _round_trip(event)


def test_tool_event_round_trip():
    tool_body = ToolEvent(
        name="lookup", args={"q": "x"}, result="ok", status="ok",
    ).to_payload()
    event = AgentStepEvent(
        kind="tool_event",
        handoff_id="h1",
        step_id="s1",
        seq=2,
        body=tool_body,
    )
    _round_trip(event)


def test_partial_response_round_trip():
    event = AgentStepEvent(
        kind="partial_response",
        handoff_id="h1",
        step_id="s1",
        seq=3,
        body={"text": "hello", "delta": True},
    )
    _round_trip(event)


def test_question_round_trip():
    event = AgentStepEvent(
        kind="question",
        seq=4,
        body={
            "question": "Which environment?",
            "schema": {"type": "string", "enum": ["dev", "prod"]},
        },
    )
    _round_trip(event)


def test_final_round_trip_carries_step_result():
    result_body = AgentStepResult(
        status="completed",
        user_visible_response="Done.",
        semantic_result=SemanticResult(action_summary="x"),
    ).to_payload()
    event = AgentStepEvent(
        kind="final",
        handoff_id="h1",
        step_id="s1",
        seq=5,
        body=result_body,
    )
    _round_trip(event)


def test_event_is_immutable():
    event = AgentStepEvent(kind="accepted", seq=0)
    with pytest.raises(FrozenInstanceError):
        event.kind = "progress"  # type: ignore[misc]


def test_event_body_is_immutable():
    event = AgentStepEvent(
        kind="progress", seq=1, body={"fraction": 0.5, "message": "x"},
    )
    with pytest.raises(TypeError):
        event.body["fraction"] = 0.9  # type: ignore[index]


def test_unknown_kind_rejected():
    with pytest.raises(ValueError, match="unknown AgentStepEvent kind"):
        AgentStepEvent(kind="bogus", seq=0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unknown AgentStepEvent kind"):
        AgentStepEvent.from_payload({"kind": "bogus"})


def test_seq_must_be_non_negative_int():
    with pytest.raises(ValueError, match="non-negative"):
        AgentStepEvent(kind="accepted", seq=-1)
    with pytest.raises(ValueError, match="must be an integer"):
        AgentStepEvent(kind="accepted", seq=1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="non-negative"):
        AgentStepEvent.from_payload({"kind": "accepted", "seq": -1})
    with pytest.raises(ValueError, match="must be an integer"):
        AgentStepEvent.from_payload({"kind": "accepted", "seq": "first"})


def test_seq_rejects_bool():
    with pytest.raises(ValueError, match="must be an integer"):
        AgentStepEvent(kind="accepted", seq=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be an integer"):
        AgentStepEvent.from_payload({"kind": "accepted", "seq": True})


def test_unknown_top_level_field_rejected():
    with pytest.raises(ValueError, match="unknown AgentStepEvent field"):
        AgentStepEvent.from_payload({"kind": "accepted", "subject": "x"})


def test_wrong_typed_top_level_fields_rejected():
    with pytest.raises(ValueError, match="must be a string"):
        AgentStepEvent.from_payload({"kind": "accepted", "handoff_id": 1})
    with pytest.raises(ValueError, match="must be a mapping"):
        AgentStepEvent.from_payload({"kind": "accepted", "body": [1, 2]})


def test_accepted_body_must_be_empty():
    with pytest.raises(
        ValueError, match=r"unknown AgentStepEvent.body\[accepted\] field",
    ):
        AgentStepEvent(kind="accepted", seq=0, body={"x": 1})


def test_progress_body_rejects_unknown_keys():
    with pytest.raises(
        ValueError, match=r"unknown AgentStepEvent.body\[progress\] field",
    ):
        AgentStepEvent(
            kind="progress", seq=1,
            body={"fraction": 0.5, "speed": "fast"},
        )


def test_progress_body_rejects_wrong_types():
    with pytest.raises(ValueError, match="must be a number or null"):
        AgentStepEvent(kind="progress", seq=1, body={"fraction": "half"})
    with pytest.raises(ValueError, match="must be a string"):
        AgentStepEvent(kind="progress", seq=1, body={"message": 123})


def test_tool_event_body_rejects_malformed_tool_event():
    with pytest.raises(ValueError, match="unknown ToolEvent field"):
        AgentStepEvent(
            kind="tool_event", seq=1, body={"unknown_key": "x"},
        )


def test_partial_response_body_validates():
    with pytest.raises(
        ValueError, match=r"unknown AgentStepEvent.body\[partial_response\] field",
    ):
        AgentStepEvent(
            kind="partial_response", seq=1,
            body={"text": "x", "delta": True, "rate": 1},
        )
    with pytest.raises(ValueError, match="must be a string"):
        AgentStepEvent(kind="partial_response", seq=1, body={"text": 1})
    with pytest.raises(ValueError, match="must be a boolean"):
        AgentStepEvent(kind="partial_response", seq=1, body={"delta": "yes"})


def test_question_body_validates():
    with pytest.raises(
        ValueError, match=r"unknown AgentStepEvent.body\[question\] field",
    ):
        AgentStepEvent(
            kind="question", seq=1,
            body={"question": "q", "schema": {}, "default": "x"},
        )
    with pytest.raises(ValueError, match="must be a string"):
        AgentStepEvent(kind="question", seq=1, body={"question": 1})
    with pytest.raises(ValueError, match="must be a mapping"):
        AgentStepEvent(kind="question", seq=1, body={"schema": [1, 2]})


def test_final_body_must_be_valid_step_result():
    with pytest.raises(ValueError, match="unknown AgentStepResult field"):
        AgentStepEvent(
            kind="final", seq=1, body={"not_a_step_result_key": "x"},
        )


def test_cross_kind_body_rejected():
    # AgentHandoff fields like 'lane' are unknown to AgentStepResult, so a
    # handoff-shaped body posing as a final step result is rejected.
    with pytest.raises(ValueError, match="unknown AgentStepResult field"):
        AgentStepEvent(kind="final", seq=1, body={"lane": "x"})
    # ToolEvent fields like 'name' are not valid AgentStepResult fields.
    with pytest.raises(ValueError, match="unknown AgentStepResult field"):
        AgentStepEvent(kind="final", seq=1, body={"name": "lookup"})


# ---------------------------------------------------------------------------
# v3 orchestration event kinds
# ---------------------------------------------------------------------------


def test_phase_started_round_trip():
    event = AgentStepEvent(
        kind="phase_started",
        handoff_id="h1",
        step_id="s1",
        seq=10,
        body={"phase": "planner", "message": "planning route"},
    )
    _round_trip(event)


def test_phase_completed_round_trip():
    event = AgentStepEvent(
        kind="phase_completed",
        handoff_id="h1",
        step_id="s1",
        seq=11,
        body={
            "phase": "planner",
            "summary": "planned 3 sub-steps",
            "metrics": {"sub_steps": 3, "tokens": 1200},
        },
    )
    _round_trip(event)


def test_checkpoint_round_trip():
    event = AgentStepEvent(
        kind="checkpoint",
        handoff_id="h1",
        step_id="s1",
        seq=12,
        body={
            "checkpoint_id": "ck-1",
            "state": {"cursor": 42, "buffer": ["a", "b"]},
        },
    )
    _round_trip(event)


def test_evaluation_round_trip():
    event = AgentStepEvent(
        kind="evaluation",
        handoff_id="h1",
        step_id="s1",
        seq=13,
        body={
            "passed": True,
            "score": 0.92,
            "findings": ["matches schema", "no PII leakage"],
            "details": {"rubric_version": "v3"},
        },
    )
    _round_trip(event)


def test_evaluation_null_score_round_trip():
    event = AgentStepEvent(
        kind="evaluation",
        seq=14,
        body={"passed": False, "score": None, "findings": [], "details": {}},
    )
    _round_trip(event)


def test_phase_started_body_validation():
    with pytest.raises(
        ValueError, match=r"unknown AgentStepEvent.body\[phase_started\] field",
    ):
        AgentStepEvent(
            kind="phase_started", seq=1,
            body={"phase": "planner", "message": "x", "extra_key": 1},
        )
    with pytest.raises(ValueError, match="must be a string"):
        AgentStepEvent(kind="phase_started", seq=1, body={"phase": 1})


def test_phase_completed_body_validation():
    with pytest.raises(
        ValueError, match=r"unknown AgentStepEvent.body\[phase_completed\] field",
    ):
        AgentStepEvent(
            kind="phase_completed", seq=1,
            body={"phase": "x", "summary": "y", "metrics": {}, "extra": 1},
        )
    with pytest.raises(ValueError, match="must be a mapping"):
        AgentStepEvent(
            kind="phase_completed", seq=1,
            body={"phase": "x", "summary": "y", "metrics": [1, 2]},
        )


def test_checkpoint_body_validation():
    with pytest.raises(
        ValueError, match=r"unknown AgentStepEvent.body\[checkpoint\] field",
    ):
        AgentStepEvent(
            kind="checkpoint", seq=1,
            body={"checkpoint_id": "ck", "state": {}, "extra_key": 1},
        )
    with pytest.raises(ValueError, match="must be a string"):
        AgentStepEvent(
            kind="checkpoint", seq=1, body={"checkpoint_id": 1, "state": {}},
        )
    with pytest.raises(ValueError, match="must be a mapping"):
        AgentStepEvent(
            kind="checkpoint", seq=1,
            body={"checkpoint_id": "ck", "state": "frozen"},
        )


def test_evaluation_body_validation():
    with pytest.raises(
        ValueError, match=r"unknown AgentStepEvent.body\[evaluation\] field",
    ):
        AgentStepEvent(
            kind="evaluation", seq=1,
            body={
                "passed": True, "score": 1.0, "findings": [],
                "details": {}, "extra_key": 1,
            },
        )
    with pytest.raises(ValueError, match="must be a boolean"):
        AgentStepEvent(kind="evaluation", seq=1, body={"passed": "yes"})
    with pytest.raises(ValueError, match="must be a number or null"):
        AgentStepEvent(kind="evaluation", seq=1, body={"score": "good"})
    with pytest.raises(ValueError, match="must be a list of strings"):
        AgentStepEvent(kind="evaluation", seq=1, body={"findings": "ok"})


# ---------------------------------------------------------------------------
# Optional orchestration / harness_policy fields
# ---------------------------------------------------------------------------


def test_event_with_orchestration_round_trip():
    event = AgentStepEvent(
        kind="phase_started",
        handoff_id="h1",
        step_id="s1",
        seq=20,
        body={"phase": "handler", "message": ""},
        orchestration=OrchestrationContext(
            run_id="run-1",
            root_handoff_id="h1",
            step_id="s1",
            phase="handler",
            capability="messaging.send",
        ),
    )
    _round_trip(event)


def test_event_with_harness_policy_round_trip():
    event = AgentStepEvent(
        kind="accepted",
        handoff_id="h1",
        step_id="s1",
        seq=21,
        harness_policy=HarnessPolicy(
            contract_id="messaging_v1",
            allowed_tools=("send_message",),
            required_outputs=("message_id",),
            max_tool_calls=3,
            requires_self_evaluation=True,
        ),
    )
    _round_trip(event)


def test_event_with_orchestration_and_harness_round_trip():
    event = AgentStepEvent(
        kind="evaluation",
        handoff_id="h1",
        step_id="s1",
        seq=22,
        body={
            "passed": True, "score": 1.0,
            "findings": [], "details": {},
        },
        orchestration=OrchestrationContext(
            run_id="run-1", phase="evaluator",
        ),
        harness_policy=HarnessPolicy(contract_id="eval_v1"),
    )
    _round_trip(event)


def test_event_accepts_mapping_for_orchestration():
    """Lenient construction: a plain mapping is converted to the DTO."""
    event = AgentStepEvent(
        kind="accepted", seq=0,
        orchestration={"run_id": "r1", "phase": "planner"},  # type: ignore[arg-type]
    )
    assert isinstance(event.orchestration, OrchestrationContext)
    assert event.orchestration.run_id == "r1"


def test_orchestration_absent_serializes_as_null():
    event = AgentStepEvent(kind="accepted", seq=0)
    payload = event.to_payload()
    assert payload["orchestration"] is None
    assert payload["harness_policy"] is None
    assert AgentStepEvent.from_payload(payload) == event
