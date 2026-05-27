from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from agent_interface_protocol.agent_interface import (
    AGENT_MESSAGE_KINDS,
    PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    AgentHandoff,
    AgentMessage,
    AgentStepEvent,
    AgentStepResult,
    ErrorInfo,
    SemanticContext,
    SemanticResult,
    ToolEvent,
)


def _round_trip(msg: AgentMessage) -> None:
    assert AgentMessage.from_payload(msg.to_payload()) == msg


def test_known_kinds_exposed():
    assert AGENT_MESSAGE_KINDS == frozenset({
        "handoff",
        "step_event",
        "step_result",
        "cancel",
        "ack",
        "error",
    })


def test_handoff_envelope_round_trip():
    handoff = AgentHandoff(
        lane="billing",
        action="create_invoice",
        args={"customer_id": "cust_123", "amount": 1250},
        semantic_context=SemanticContext(user_goal="invoice approved work"),
    )
    msg = AgentMessage(
        kind="handoff",
        message_id="m1",
        correlation_id="c1",
        sender="host@svc",
        recipient="billing@svc",
        sent_at="2026-05-26T10:00:00Z",
        trace_id="trace-1",
        payload=handoff.to_payload(),
    )
    _round_trip(msg)


def test_step_event_envelope_round_trip():
    event_body = AgentStepEvent(
        kind="tool_event",
        handoff_id="h1",
        step_id="s1",
        seq=1,
        body=ToolEvent(name="lookup", args={}, result="ok").to_payload(),
    ).to_payload()
    msg = AgentMessage(
        kind="step_event",
        message_id="m2",
        correlation_id="h1",
        sender="billing@svc",
        recipient="host@svc",
        payload=event_body,
    )
    _round_trip(msg)


def test_step_result_envelope_round_trip():
    result = AgentStepResult(
        status="completed",
        user_visible_response="Created invoice.",
        semantic_result=SemanticResult(action_summary="Created inv_456."),
    )
    msg = AgentMessage(
        kind="step_result",
        message_id="m3",
        correlation_id="h1",
        in_reply_to="m1",
        payload=result.to_payload(),
    )
    _round_trip(msg)


def test_cancel_envelope_round_trip():
    msg = AgentMessage(
        kind="cancel",
        message_id="m4",
        correlation_id="h1",
        sender="host@svc",
        recipient="billing@svc",
        payload={"handoff_id": "h1", "reason": "user aborted"},
    )
    _round_trip(msg)


def test_ack_envelope_round_trip():
    msg = AgentMessage(
        kind="ack",
        message_id="m5",
        correlation_id="h1",
        in_reply_to="m1",
        payload={"accepted": True, "reason": ""},
    )
    _round_trip(msg)


def test_error_envelope_round_trip():
    err = ErrorInfo(code="timeout", message="agent timed out", retriable=True)
    msg = AgentMessage(
        kind="error",
        message_id="m6",
        correlation_id="h1",
        in_reply_to="m1",
        payload=err.to_payload(),
    )
    _round_trip(msg)


def test_envelope_is_immutable():
    msg = AgentMessage(kind="ack", payload={"accepted": True, "reason": ""})
    with pytest.raises(FrozenInstanceError):
        msg.kind = "error"  # type: ignore[misc]
    with pytest.raises(TypeError):
        msg.payload["accepted"] = False  # type: ignore[index]


def test_unknown_kind_rejected():
    with pytest.raises(ValueError, match="unknown AgentMessage kind"):
        AgentMessage(kind="weird")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unknown AgentMessage kind"):
        AgentMessage.from_payload({"kind": "weird"})


def test_unknown_top_level_field_rejected():
    with pytest.raises(ValueError, match="unknown AgentMessage field"):
        AgentMessage.from_payload({
            "kind": "ack",
            "payload": {"accepted": True, "reason": ""},
            "extra_field": "x",
        })


def test_wrong_typed_top_level_fields_rejected():
    with pytest.raises(ValueError, match="must be a string"):
        AgentMessage.from_payload({
            "kind": "ack", "message_id": 1,
            "payload": {"accepted": True, "reason": ""},
        })
    with pytest.raises(ValueError, match="must be a mapping"):
        AgentMessage.from_payload({"kind": "ack", "payload": [1, 2]})


def test_unsupported_protocol_version_rejected():
    with pytest.raises(ValueError, match="unsupported agent_interface_version"):
        AgentMessage.from_payload({
            "agent_interface_version": max(SUPPORTED_PROTOCOL_VERSIONS) + 1,
            "kind": "ack",
            "payload": {"accepted": True, "reason": ""},
        })


def test_supported_protocol_versions_preserved():
    for version in SUPPORTED_PROTOCOL_VERSIONS:
        msg = AgentMessage.from_payload({
            "agent_interface_version": version,
            "kind": "ack",
            "payload": {"accepted": True, "reason": ""},
        })
        assert msg.protocol_version == version
        assert msg.to_payload()["agent_interface_version"] == version


def test_default_protocol_version_is_current():
    msg = AgentMessage(kind="ack", payload={"accepted": True, "reason": ""})
    assert msg.protocol_version == PROTOCOL_VERSION


def test_cross_kind_payload_rejected_handoff_vs_error():
    # ErrorInfo-shaped payload as kind="handoff" — "code" is unknown to AgentHandoff.
    with pytest.raises(ValueError, match="unknown AgentHandoff field"):
        AgentMessage(kind="handoff", payload={"code": "x"})
    # Handoff-shaped payload as kind="error" — "lane" is unknown to ErrorInfo.
    with pytest.raises(ValueError, match="unknown ErrorInfo field"):
        AgentMessage(kind="error", payload={"lane": "billing"})


def test_cross_kind_payload_rejected_step_event_vs_result():
    # AgentStepEvent shape carried as step_result — AgentStepResult does not
    # know fields like "kind"/"seq"/"body".
    with pytest.raises(ValueError, match="unknown AgentStepResult field"):
        AgentMessage(
            kind="step_result",
            payload={"kind": "accepted", "seq": 0, "body": {}},
        )


def test_cancel_payload_rejects_unknown_keys_and_wrong_types():
    with pytest.raises(
        ValueError, match=r"unknown AgentMessage.payload\[cancel\] field",
    ):
        AgentMessage(
            kind="cancel",
            payload={"handoff_id": "h", "reason": "x", "extra": "x"},
        )
    with pytest.raises(ValueError, match="must be a string"):
        AgentMessage(kind="cancel", payload={"handoff_id": 1, "reason": "x"})


def test_ack_payload_rejects_unknown_keys_and_wrong_types():
    with pytest.raises(
        ValueError, match=r"unknown AgentMessage.payload\[ack\] field",
    ):
        AgentMessage(
            kind="ack",
            payload={"accepted": True, "reason": "ok", "extra": 1},
        )
    with pytest.raises(ValueError, match="must be a boolean"):
        AgentMessage(kind="ack", payload={"accepted": "yes", "reason": ""})


def test_envelope_addressing_is_distinct_from_semantic_agents():
    """Envelope sender/recipient are transport identity; the semantic
    source_agent and target_agent live inside the handoff payload."""
    handoff = AgentHandoff(
        source_agent="billing_bot",
        target_agent="invoice_agent",
        lane="billing",
    )
    msg = AgentMessage(
        kind="handoff",
        sender="router@svc",
        recipient="worker-pool@svc",
        payload=handoff.to_payload(),
    )
    assert msg.sender == "router@svc"
    assert msg.recipient == "worker-pool@svc"
    inner = AgentHandoff.from_payload(dict(msg.payload))
    assert inner.source_agent == "billing_bot"
    assert inner.target_agent == "invoice_agent"
