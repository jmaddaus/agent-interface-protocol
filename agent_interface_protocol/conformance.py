"""Reusable conformance assertions for third-party AIP executors.

Downstream packages that implement ``StreamingAgentExecutor`` or
``AgentExecutor`` can import these helpers from their own test suite
to claim protocol conformance. The assertions encode the invariants
documented in the protocol spec — strictly-increasing ``seq``, exactly
one terminal event, no post-terminal emissions, structural contract
for ``describe`` / ``validate_handoff`` / ``cancel`` — so downstream
implementations and AIP itself stay aligned even as new versions add
new event kinds.

Example downstream usage::

    from agent_interface_protocol import AgentHandoff
    from agent_interface_protocol.conformance import (
        assert_streaming_executor_conformant,
    )
    from my_pkg import MyStreamingExecutor

    def test_my_executor_is_conformant():
        executor = MyStreamingExecutor(some_config)
        sample = AgentHandoff(lane="messaging", action="send")
        assert_streaming_executor_conformant(executor, sample)

The composite helpers raise ``AssertionError`` on the first invariant
violation; per-invariant helpers are exposed for cases where a
downstream wants more granular control over what they assert.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from agent_interface_protocol.agent_interface import (
    AGENT_STEP_EVENT_KINDS,
    AgentExecutor,
    AgentHandoff,
    AgentStepEvent,
    AgentStepResult,
    StreamingAgentExecutor,
)


# ---------------------------------------------------------------------------
# Per-invariant helpers
# ---------------------------------------------------------------------------


def assert_events_are_step_events(
    events: Iterable[Any],
) -> tuple[AgentStepEvent, ...]:
    """Materialize ``events`` and assert every element is an ``AgentStepEvent``.

    Returns the materialized tuple so callers can keep working with it.
    """
    materialized = tuple(events)
    for i, event in enumerate(materialized):
        if not isinstance(event, AgentStepEvent):
            raise AssertionError(
                f"event[{i}] is not an AgentStepEvent: "
                f"got {type(event).__name__}"
            )
    return materialized


def assert_kinds_are_known(events: Iterable[AgentStepEvent]) -> None:
    """Every event's ``kind`` must be in ``AGENT_STEP_EVENT_KINDS``."""
    for i, event in enumerate(events):
        if event.kind not in AGENT_STEP_EVENT_KINDS:
            raise AssertionError(
                f"event[{i}] has unknown kind {event.kind!r}; "
                f"valid kinds: {sorted(AGENT_STEP_EVENT_KINDS)}"
            )


def assert_seq_strictly_increasing(events: Iterable[AgentStepEvent]) -> None:
    """``seq`` must be non-negative and strictly increasing per stream."""
    last = -1
    for i, event in enumerate(events):
        if event.seq < 0:
            raise AssertionError(
                f"event[{i}] has negative seq {event.seq}"
            )
        if event.seq <= last:
            raise AssertionError(
                f"event[{i}] seq {event.seq} is not greater than the "
                f"previous seq {last}"
            )
        last = event.seq


def assert_exactly_one_final(events: Iterable[AgentStepEvent]) -> int:
    """Exactly one event must have ``kind == "final"``. Returns its index."""
    materialized = list(events)
    final_indices = [i for i, e in enumerate(materialized) if e.kind == "final"]
    if not final_indices:
        raise AssertionError(
            "event stream ended without a terminal 'final' event"
        )
    if len(final_indices) > 1:
        raise AssertionError(
            f"event stream contains {len(final_indices)} 'final' events "
            f"at indices {final_indices}; expected exactly one"
        )
    return final_indices[0]


def assert_no_events_after_final(events: Iterable[AgentStepEvent]) -> None:
    """No events may follow the terminal ``final`` event."""
    materialized = list(events)
    final_index = assert_exactly_one_final(materialized)
    if final_index != len(materialized) - 1:
        trailing = [e.kind for e in materialized[final_index + 1:]]
        raise AssertionError(
            f"events emitted after terminal 'final' at index {final_index}: "
            f"{trailing}"
        )


def assert_final_body_is_step_result(events: Iterable[AgentStepEvent]) -> AgentStepResult:
    """The ``final`` event body must parse as an ``AgentStepResult``."""
    materialized = list(events)
    final_index = assert_exactly_one_final(materialized)
    final = materialized[final_index]
    try:
        return AgentStepResult.from_payload(final.body)
    except (ValueError, TypeError) as exc:
        raise AssertionError(
            f"final event body did not parse as AgentStepResult: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Composite stream conformance
# ---------------------------------------------------------------------------


def assert_event_stream_conformant(
    events: Iterable[Any],
) -> AgentStepResult:
    """Drain an event stream and assert every protocol invariant on it.

    Asserts (in order):

    1. Every element is an ``AgentStepEvent``.
    2. Every ``kind`` is in ``AGENT_STEP_EVENT_KINDS``.
    3. ``seq`` is non-negative and strictly increasing.
    4. Exactly one ``final`` event terminates the stream.
    5. No events follow the ``final`` event.
    6. The ``final`` body parses as an ``AgentStepResult``.

    Returns the parsed ``AgentStepResult`` on success. Raises
    ``AssertionError`` on the first violation.
    """
    materialized = assert_events_are_step_events(events)
    assert_kinds_are_known(materialized)
    assert_seq_strictly_increasing(materialized)
    assert_no_events_after_final(materialized)
    return assert_final_body_is_step_result(materialized)


# ---------------------------------------------------------------------------
# Executor-level conformance
# ---------------------------------------------------------------------------


def assert_streaming_executor_conformant(
    executor: StreamingAgentExecutor,
    sample_handoff: AgentHandoff,
) -> AgentStepResult:
    """End-to-end conformance check against a ``StreamingAgentExecutor``.

    Asserts:

    * ``describe()`` returns a ``Mapping``.
    * ``validate_handoff(sample_handoff)`` does not raise.
    * ``stream(sample_handoff)`` yields a protocol-conformant event
      stream (see :func:`assert_event_stream_conformant`).
    * ``cancel(handoff_id, reason)`` is callable without raising.
      AIP does not require ``cancel`` to do anything observable for an
      already-completed handoff; this check only enforces the
      signature.

    Returns the terminal ``AgentStepResult`` produced by the stream.

    The sample handoff is consumed and may produce side effects in the
    executor. Use a fresh executor / sandbox per call if needed.
    """
    described = executor.describe()
    if not isinstance(described, Mapping):
        raise AssertionError(
            f"executor.describe() must return a Mapping, "
            f"got {type(described).__name__}"
        )

    try:
        executor.validate_handoff(sample_handoff)
    except Exception as exc:  # pragma: no cover — informational re-raise
        raise AssertionError(
            f"executor.validate_handoff rejected a well-formed sample "
            f"handoff: {exc!r}"
        ) from exc

    events = executor.stream(sample_handoff)
    result = assert_event_stream_conformant(events)

    try:
        executor.cancel(sample_handoff.handoff_id or "test-cancel", "conformance-test")
    except Exception as exc:  # pragma: no cover
        raise AssertionError(
            f"executor.cancel raised on a no-op invocation: {exc!r}"
        ) from exc

    return result


def assert_sync_executor_conformant(
    executor: AgentExecutor,
    sample_request: Mapping[str, Any],
    sample_handoff: AgentHandoff | None = None,
) -> AgentStepResult:
    """End-to-end conformance check against a sync ``AgentExecutor``.

    Asserts:

    * ``describe()`` returns a ``Mapping``.
    * ``validate_handoff(sample_handoff)`` does not raise if provided.
    * ``step(sample_request)`` returns an ``AgentStepResult``.

    Returns the result so the caller can inspect it.
    """
    described = executor.describe()
    if not isinstance(described, Mapping):
        raise AssertionError(
            f"executor.describe() must return a Mapping, "
            f"got {type(described).__name__}"
        )

    if sample_handoff is not None:
        try:
            executor.validate_handoff(sample_handoff)
        except Exception as exc:  # pragma: no cover
            raise AssertionError(
                f"executor.validate_handoff rejected a well-formed sample "
                f"handoff: {exc!r}"
            ) from exc

    result = executor.step(sample_request)
    if not isinstance(result, AgentStepResult):
        raise AssertionError(
            f"executor.step must return an AgentStepResult, "
            f"got {type(result).__name__}"
        )
    return result


__all__ = [
    "assert_events_are_step_events",
    "assert_kinds_are_known",
    "assert_seq_strictly_increasing",
    "assert_exactly_one_final",
    "assert_no_events_after_final",
    "assert_final_body_is_step_result",
    "assert_event_stream_conformant",
    "assert_streaming_executor_conformant",
    "assert_sync_executor_conformant",
]
