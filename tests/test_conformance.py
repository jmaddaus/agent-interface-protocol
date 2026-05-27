from __future__ import annotations

from typing import Iterator

import pytest

from agent_interface_protocol import (
    AgentExecutor,
    AgentHandoff,
    AgentStepEvent,
    AgentStepResult,
    SemanticResult,
    StreamingAgentExecutor,
    ToolEvent,
)
from agent_interface_protocol.conformance import (
    assert_event_stream_conformant,
    assert_events_are_step_events,
    assert_exactly_one_final,
    assert_final_body_is_step_result,
    assert_kinds_are_known,
    assert_no_events_after_final,
    assert_seq_strictly_increasing,
    assert_streaming_executor_conformant,
    assert_sync_executor_conformant,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _final(seq: int, **kwargs) -> AgentStepEvent:
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


def _conformant_stream() -> list[AgentStepEvent]:
    return [
        AgentStepEvent(kind="accepted", handoff_id="h", step_id="s", seq=0),
        AgentStepEvent(
            kind="tool_event", handoff_id="h", step_id="s", seq=1,
            body=ToolEvent(name="lookup", result="ok").to_payload(),
        ),
        AgentStepEvent(
            kind="partial_response", handoff_id="h", step_id="s", seq=2,
            body={"text": "hello", "delta": True},
        ),
        _final(seq=3),
    ]


# ---------------------------------------------------------------------------
# Per-invariant helpers
# ---------------------------------------------------------------------------


def test_events_are_step_events_accepts_real_events():
    out = assert_events_are_step_events(_conformant_stream())
    assert len(out) == 4
    assert all(isinstance(e, AgentStepEvent) for e in out)


def test_events_are_step_events_rejects_non_event():
    with pytest.raises(AssertionError, match="not an AgentStepEvent"):
        assert_events_are_step_events([
            AgentStepEvent(kind="accepted", seq=0),
            {"kind": "accepted", "seq": 1},  # dict, not AgentStepEvent
        ])


def test_kinds_are_known_accepts_v3_kinds():
    events = [
        AgentStepEvent(
            kind="phase_started", seq=0,
            body={"phase": "planner", "message": ""},
        ),
        AgentStepEvent(
            kind="checkpoint", seq=1,
            body={"checkpoint_id": "ck", "state": {}},
        ),
    ]
    assert_kinds_are_known(events)


def test_seq_strictly_increasing_accepts_monotonic():
    assert_seq_strictly_increasing(_conformant_stream())


def test_seq_strictly_increasing_rejects_duplicate():
    events = [
        AgentStepEvent(kind="accepted", seq=0),
        _final(seq=0),
    ]
    with pytest.raises(AssertionError, match="not greater than"):
        assert_seq_strictly_increasing(events)


def test_seq_strictly_increasing_rejects_decreasing():
    events = [
        AgentStepEvent(kind="accepted", seq=2),
        _final(seq=1),
    ]
    with pytest.raises(AssertionError, match="not greater than"):
        assert_seq_strictly_increasing(events)


def test_exactly_one_final_returns_index():
    idx = assert_exactly_one_final(_conformant_stream())
    assert idx == 3


def test_exactly_one_final_rejects_zero_finals():
    events = [AgentStepEvent(kind="accepted", seq=0)]
    with pytest.raises(AssertionError, match="without a terminal 'final'"):
        assert_exactly_one_final(events)


def test_exactly_one_final_rejects_multiple_finals():
    events = [_final(seq=0), _final(seq=1)]
    with pytest.raises(AssertionError, match="contains 2 'final' events"):
        assert_exactly_one_final(events)


def test_no_events_after_final_rejects_trailing_events():
    events = [
        _final(seq=0),
        AgentStepEvent(kind="accepted", seq=1),
    ]
    with pytest.raises(AssertionError, match="emitted after terminal 'final'"):
        assert_no_events_after_final(events)


def test_final_body_is_step_result_returns_parsed_result():
    result = assert_final_body_is_step_result(_conformant_stream())
    assert isinstance(result, AgentStepResult)
    assert result.status == "completed"


# ---------------------------------------------------------------------------
# Composite stream conformance
# ---------------------------------------------------------------------------


def test_event_stream_conformant_returns_result():
    result = assert_event_stream_conformant(_conformant_stream())
    assert isinstance(result, AgentStepResult)
    assert result.status == "completed"


def test_event_stream_conformant_catches_each_violation():
    # Wrong type
    with pytest.raises(AssertionError, match="not an AgentStepEvent"):
        assert_event_stream_conformant([{"kind": "accepted"}])

    # Non-monotonic seq
    bad = [AgentStepEvent(kind="accepted", seq=2), _final(seq=1)]
    with pytest.raises(AssertionError, match="not greater than"):
        assert_event_stream_conformant(bad)

    # No final
    bad = [AgentStepEvent(kind="accepted", seq=0)]
    with pytest.raises(AssertionError, match="without a terminal"):
        assert_event_stream_conformant(bad)

    # Trailing event
    bad = [_final(seq=0), AgentStepEvent(kind="accepted", seq=1)]
    with pytest.raises(AssertionError, match="emitted after terminal"):
        assert_event_stream_conformant(bad)


# ---------------------------------------------------------------------------
# Streaming executor conformance
# ---------------------------------------------------------------------------


class _GoodStreamingExecutor(StreamingAgentExecutor):
    def __init__(self, events: list[AgentStepEvent]) -> None:
        self.events = events
        self.cancelled: list[tuple[str, str]] = []

    def describe(self):  # type: ignore[override]
        return {"name": "good", "version": "1.0"}

    def validate_handoff(self, handoff: AgentHandoff) -> None:  # type: ignore[override]
        return None

    def stream(self, handoff: AgentHandoff) -> Iterator[AgentStepEvent]:  # type: ignore[override]
        yield from self.events

    def cancel(self, handoff_id: str, reason: str) -> None:  # type: ignore[override]
        self.cancelled.append((handoff_id, reason))


def test_streaming_executor_conformance_passes_on_good_executor():
    executor = _GoodStreamingExecutor(_conformant_stream())
    sample = AgentHandoff(handoff_id="h-test", lane="x")
    result = assert_streaming_executor_conformant(executor, sample)
    assert result.status == "completed"
    assert executor.cancelled == [("h-test", "conformance-test")]


def test_streaming_executor_conformance_rejects_non_mapping_describe():
    class _BadDescribe(_GoodStreamingExecutor):
        def describe(self):  # type: ignore[override]
            return "not-a-mapping"

    executor = _BadDescribe(_conformant_stream())
    with pytest.raises(AssertionError, match="must return a Mapping"):
        assert_streaming_executor_conformant(executor, AgentHandoff(lane="x"))


def test_streaming_executor_conformance_propagates_stream_violation():
    bad_events = [
        AgentStepEvent(kind="accepted", seq=0),
        # missing final
    ]
    executor = _GoodStreamingExecutor(bad_events)
    with pytest.raises(AssertionError, match="without a terminal"):
        assert_streaming_executor_conformant(executor, AgentHandoff(lane="x"))


def test_streaming_executor_conformance_rejects_raising_validate_handoff():
    class _BadValidate(_GoodStreamingExecutor):
        def validate_handoff(self, handoff):  # type: ignore[override]
            raise ValueError("nope")

    executor = _BadValidate(_conformant_stream())
    with pytest.raises(AssertionError, match="rejected a well-formed"):
        assert_streaming_executor_conformant(executor, AgentHandoff(lane="x"))


def test_streaming_executor_conformance_rejects_raising_cancel():
    class _BadCancel(_GoodStreamingExecutor):
        def cancel(self, handoff_id, reason):  # type: ignore[override]
            raise RuntimeError("kaboom")

    executor = _BadCancel(_conformant_stream())
    with pytest.raises(AssertionError, match="cancel raised"):
        assert_streaming_executor_conformant(executor, AgentHandoff(lane="x"))


# ---------------------------------------------------------------------------
# Sync executor conformance
# ---------------------------------------------------------------------------


class _GoodSyncExecutor(AgentExecutor):
    def describe(self):  # type: ignore[override]
        return {"name": "sync"}

    def validate_handoff(self, handoff: AgentHandoff) -> None:  # type: ignore[override]
        return None

    def step(self, request):  # type: ignore[override]
        return AgentStepResult(
            status="completed",
            user_visible_response="ok",
            semantic_result=SemanticResult(action_summary="x"),
        )


def test_sync_executor_conformance_passes_on_good_executor():
    handoff = AgentHandoff(lane="x")
    result = assert_sync_executor_conformant(
        _GoodSyncExecutor(), handoff.to_payload(), handoff,
    )
    assert result.status == "completed"


def test_sync_executor_conformance_rejects_non_step_result():
    class _Bad(_GoodSyncExecutor):
        def step(self, request):  # type: ignore[override]
            return {"status": "completed"}  # plain dict, not AgentStepResult

    with pytest.raises(AssertionError, match="must return an AgentStepResult"):
        assert_sync_executor_conformant(
            _Bad(), AgentHandoff(lane="x").to_payload(),
        )


def test_sync_executor_conformance_omits_validate_when_no_handoff_provided():
    """validate_handoff is optional in the conformance check."""

    class _RaisesValidate(_GoodSyncExecutor):
        def validate_handoff(self, handoff):  # type: ignore[override]
            raise ValueError("never call me")

    result = assert_sync_executor_conformant(
        _RaisesValidate(), AgentHandoff(lane="x").to_payload(),
    )
    assert result.status == "completed"
