from __future__ import annotations

from typing import Iterator

import pytest

from agent_interface_protocol import (
    AgentHandoff,
    AgentMessage,
    AgentStepEvent,
    AgentStepResult,
    SemanticResult,
    StreamingAgentExecutor,
    ToolEvent,
)
from agent_interface_protocol.reference import InProcessBus, SyncStreamAdapter


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _MockStreamingExecutor(StreamingAgentExecutor):
    """In-memory streaming executor that replays a canned event list."""

    def __init__(self, events: list[AgentStepEvent]) -> None:
        self.events = events
        self.cancelled: list[tuple[str, str]] = []
        self.described = 0

    def describe(self):  # type: ignore[override]
        self.described += 1
        return {"name": "mock"}

    def validate_handoff(self, handoff: AgentHandoff) -> None:  # type: ignore[override]
        return None

    def stream(self, handoff: AgentHandoff) -> Iterator[AgentStepEvent]:  # type: ignore[override]
        yield from self.events

    def cancel(self, handoff_id: str, reason: str) -> None:  # type: ignore[override]
        self.cancelled.append((handoff_id, reason))


def _final_event(seq: int, **kwargs) -> AgentStepEvent:
    body = AgentStepResult(
        status="completed",
        user_visible_response=kwargs.get("response", "ok"),
        semantic_result=SemanticResult(
            action_summary=kwargs.get("summary", "did the thing"),
        ),
    ).to_payload()
    return AgentStepEvent(
        kind="final",
        handoff_id=kwargs.get("handoff_id", "h"),
        step_id=kwargs.get("step_id", "s"),
        seq=seq,
        body=body,
    )


# ---------------------------------------------------------------------------
# SyncStreamAdapter
# ---------------------------------------------------------------------------


def test_adapter_returns_final_result():
    events = [
        AgentStepEvent(kind="accepted", handoff_id="h", step_id="s", seq=0),
        _final_event(seq=1, response="hello"),
    ]
    adapter = SyncStreamAdapter(_MockStreamingExecutor(events))
    result = adapter.step(AgentHandoff(lane="x").to_payload())
    assert result.status == "completed"
    assert result.user_visible_response == "hello"


def test_adapter_accepts_handoff_directly():
    events = [_final_event(seq=0)]
    adapter = SyncStreamAdapter(_MockStreamingExecutor(events))
    result = adapter.step(AgentHandoff(lane="x"))
    assert result.status == "completed"


def test_adapter_rejects_stream_without_final():
    events = [
        AgentStepEvent(kind="accepted", seq=0),
        AgentStepEvent(
            kind="progress", seq=1, body={"fraction": 0.5, "message": "x"},
        ),
    ]
    adapter = SyncStreamAdapter(_MockStreamingExecutor(events))
    with pytest.raises(RuntimeError, match="ended without"):
        adapter.step(AgentHandoff(lane="x"))


def test_adapter_rejects_non_monotonic_seq():
    events = [
        AgentStepEvent(kind="accepted", seq=2),
        _final_event(seq=1),
    ]
    adapter = SyncStreamAdapter(_MockStreamingExecutor(events))
    with pytest.raises(ValueError, match="strictly increasing"):
        adapter.step(AgentHandoff(lane="x"))


def test_adapter_rejects_duplicate_seq():
    events = [
        AgentStepEvent(kind="accepted", seq=0),
        _final_event(seq=0),
    ]
    adapter = SyncStreamAdapter(_MockStreamingExecutor(events))
    with pytest.raises(ValueError, match="strictly increasing"):
        adapter.step(AgentHandoff(lane="x"))


def test_adapter_rejects_events_after_final():
    events = [
        _final_event(seq=0),
        AgentStepEvent(
            kind="progress", seq=1, body={"fraction": 1.0, "message": "x"},
        ),
    ]
    adapter = SyncStreamAdapter(_MockStreamingExecutor(events))
    with pytest.raises(ValueError, match="after the terminal"):
        adapter.step(AgentHandoff(lane="x"))


def test_adapter_delegates_describe_and_validate():
    mock = _MockStreamingExecutor([])
    adapter = SyncStreamAdapter(mock)
    assert adapter.describe() == {"name": "mock"}
    assert mock.described == 1
    adapter.validate_handoff(AgentHandoff(lane="x"))  # does not raise


def test_adapter_propagates_streaming_executor_exceptions():
    class _Boom(_MockStreamingExecutor):
        def stream(self, handoff):
            raise RuntimeError("boom")
            yield  # pragma: no cover — unreachable, keeps it a generator

    adapter = SyncStreamAdapter(_Boom([]))
    with pytest.raises(RuntimeError, match="boom"):
        adapter.step(AgentHandoff(lane="x"))


# ---------------------------------------------------------------------------
# InProcessBus
# ---------------------------------------------------------------------------


def _ack(recipient: str, sender: str = "host@svc") -> AgentMessage:
    return AgentMessage(
        kind="ack",
        sender=sender,
        recipient=recipient,
        payload={"accepted": True, "reason": ""},
    )


def test_bus_delivers_to_recipient():
    bus = InProcessBus()
    received: list[AgentMessage] = []
    bus.subscribe("alice@bus", received.append)

    msg = _ack("alice@bus")
    bus.publish(msg)
    assert received == [msg]


def test_bus_delivers_to_multiple_subscribers_in_subscription_order():
    bus = InProcessBus()
    log: list[tuple[str, AgentMessage]] = []
    bus.subscribe("alice@bus", lambda m: log.append(("h1", m)))
    bus.subscribe("alice@bus", lambda m: log.append(("h2", m)))

    msg = _ack("alice@bus")
    bus.publish(msg)
    assert log == [("h1", msg), ("h2", msg)]


def test_bus_does_not_deliver_to_other_recipients():
    bus = InProcessBus()
    received: list[AgentMessage] = []
    bus.subscribe("alice@bus", received.append)

    bus.publish(_ack("bob@bus"))
    assert received == []


def test_bus_logs_messages_in_publish_order():
    bus = InProcessBus()
    msgs = [_ack("a"), _ack("b"), _ack("c")]
    for m in msgs:
        bus.publish(m)
    assert bus.log == tuple(msgs)


def test_bus_clear_log_drops_history_but_keeps_subscribers():
    bus = InProcessBus()
    received: list[AgentMessage] = []
    bus.subscribe("alice@bus", received.append)

    bus.publish(_ack("alice@bus"))
    bus.clear_log()
    assert bus.log == ()

    bus.publish(_ack("alice@bus"))
    assert len(received) == 2  # subscriber survived clear_log
    assert len(bus.log) == 1


def test_bus_unsubscribe_stops_delivery():
    bus = InProcessBus()
    received: list[AgentMessage] = []
    handler = received.append
    bus.subscribe("alice@bus", handler)
    bus.publish(_ack("alice@bus"))
    assert len(received) == 1

    bus.unsubscribe("alice@bus", handler)
    bus.publish(_ack("alice@bus"))
    assert len(received) == 1  # second publish not delivered


def test_bus_unsubscribe_unknown_handler_is_noop():
    bus = InProcessBus()
    bus.unsubscribe("alice@bus", lambda m: None)  # no error
    bus.subscribe("alice@bus", lambda m: None)
    bus.unsubscribe("alice@bus", lambda m: None)  # different lambda, no error


def test_bus_publish_during_delivery_is_safe():
    """A subscriber that publishes another message must not corrupt the
    in-flight delivery of the current one."""
    bus = InProcessBus()
    received: list[str] = []

    def relay(msg: AgentMessage) -> None:
        received.append(f"relay:{msg.recipient}")
        if msg.recipient == "alice@bus":
            bus.publish(_ack("bob@bus"))

    def bob(msg: AgentMessage) -> None:
        received.append(f"bob:{msg.recipient}")

    bus.subscribe("alice@bus", relay)
    bus.subscribe("bob@bus", bob)

    bus.publish(_ack("alice@bus"))
    assert received == ["relay:alice@bus", "bob:bob@bus"]


# ---------------------------------------------------------------------------
# Integration: streaming executor publishing through the bus
# ---------------------------------------------------------------------------


def test_streaming_executor_publishes_through_bus_to_observer():
    """A streaming executor's events, wrapped as envelopes, are delivered
    to a bus subscriber in `seq` order, terminating with `step_result`."""
    bus = InProcessBus()
    received: list[AgentMessage] = []
    bus.subscribe("host@svc", received.append)

    handoff = AgentHandoff(handoff_id="h1", lane="x")
    events = [
        AgentStepEvent(
            kind="accepted", handoff_id="h1", step_id="s1", seq=0,
        ),
        AgentStepEvent(
            kind="tool_event", handoff_id="h1", step_id="s1", seq=1,
            body=ToolEvent(name="lookup", result="ok").to_payload(),
        ),
        _final_event(seq=2, handoff_id="h1", step_id="s1"),
    ]
    executor = _MockStreamingExecutor(events)

    for i, event in enumerate(executor.stream(handoff)):
        envelope_kind = "step_result" if event.kind == "final" else "step_event"
        payload = (
            AgentStepResult.from_payload(event.body).to_payload()
            if event.kind == "final"
            else event.to_payload()
        )
        bus.publish(AgentMessage(
            kind=envelope_kind,
            message_id=f"m{i}",
            correlation_id="h1",
            sender="agent@svc",
            recipient="host@svc",
            payload=payload,
        ))

    kinds = [m.kind for m in received]
    assert kinds == ["step_event", "step_event", "step_result"]
    # seq order preserved across envelope/event layers
    seqs = [
        AgentStepEvent.from_payload(m.payload).seq
        for m in received[:2]
    ]
    assert seqs == [0, 1]
    final_result = AgentStepResult.from_payload(received[-1].payload)
    assert final_result.status == "completed"


def test_sync_adapter_drives_streaming_executor_end_to_end():
    """Sanity check: the adapter and a realistic event stream compose."""
    events = [
        AgentStepEvent(kind="accepted", seq=0),
        AgentStepEvent(
            kind="tool_event", seq=1,
            body=ToolEvent(name="lookup", result="ok").to_payload(),
        ),
        AgentStepEvent(
            kind="partial_response", seq=2,
            body={"text": "thinking...", "delta": True},
        ),
        _final_event(seq=3, response="done", summary="found it"),
    ]
    adapter = SyncStreamAdapter(_MockStreamingExecutor(events))
    result = adapter.step(AgentHandoff(lane="x"))
    assert result.status == "completed"
    assert result.user_visible_response == "done"
    assert result.semantic_result.action_summary == "found it"
