from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from agent_interface_protocol.agent_interface import (
    AGENT_STEP_EVENT_KINDS,
    AgentStepEvent,
    AgentStepResult,
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
