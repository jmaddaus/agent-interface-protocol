"""Reference implementations: sync-over-streaming adapter and in-process bus.

These are *reference* implementations — useful for tests, demos, and
single-process consumers. They are **not** part of the stable protocol
surface and may evolve faster than the core DTOs. Import them
explicitly when you want them:

    from agent_interface_protocol.reference import (
        InProcessBus,
        SyncStreamAdapter,
    )

The core protocol (envelopes, events, content DTOs) lives in
``agent_interface_protocol.agent_interface`` and is what gets pinned
across services. This module ships behavior that helps you wire those
DTOs together in-process.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Mapping

from agent_interface_protocol.agent_interface import (
    AgentExecutor,
    AgentHandoff,
    AgentMessage,
    AgentStepResult,
    StreamingAgentExecutor,
)


class SyncStreamAdapter(AgentExecutor):
    """Expose a ``StreamingAgentExecutor`` through the sync ``AgentExecutor`` API.

    Drains ``stream(handoff)`` and returns the terminal
    ``AgentStepResult`` carried by the ``final`` event. Verifies the
    invariants from the protocol doc (invariants 8 and 9):

    * ``AgentStepEvent.seq`` is strictly increasing per stream;
    * the stream terminates with exactly one ``final`` event;
    * no events are emitted after ``final``.

    Use this when a consumer expects the v1 ``AgentExecutor.step``
    contract but the underlying executor is streaming. The reverse
    direction — wrapping a sync executor as a streaming one — is
    trivially "yield one ``final`` event"; it does not need an adapter.

    Implementation notes
    --------------------
    * Handoff validation is the streaming executor's responsibility
      inside ``stream``. ``step`` does not call ``validate_handoff``
      because doing so would either double-validate (if the executor
      also validates internally) or imply that ``step`` is the only
      validation entry point. Callers who need pre-stream validation
      should invoke ``validate_handoff`` explicitly.
    * Draining is unbounded by design: to detect events emitted after
      ``final``, ``step`` must consume the iterator to exhaustion. An
      executor that yields ``final`` and then continues indefinitely
      will hang the caller. Cancel via the executor's own ``cancel``
      method or an external timeout when this is a risk.
    """

    def __init__(self, streaming: StreamingAgentExecutor) -> None:
        self._streaming = streaming

    def describe(self) -> Mapping[str, Any]:
        return self._streaming.describe()

    def validate_handoff(self, handoff: AgentHandoff) -> None:
        self._streaming.validate_handoff(handoff)

    def step(self, request: Mapping[str, Any] | AgentHandoff) -> AgentStepResult:
        if isinstance(request, AgentHandoff):
            handoff = request
        else:
            handoff = AgentHandoff.from_payload(request)
        last_seq = -1
        result: AgentStepResult | None = None
        for event in self._streaming.stream(handoff):
            if event.seq <= last_seq:
                raise ValueError(
                    f"AgentStepEvent.seq must be strictly increasing per stream; "
                    f"got {event.seq} after {last_seq}"
                )
            last_seq = event.seq
            if result is not None:
                raise ValueError(
                    "stream emitted an event after the terminal 'final' event"
                )
            if event.kind == "final":
                # AgentStepEvent.__post_init__ already re-parsed the body
                # through AgentStepResult.from_payload for kind="final",
                # so this parse is redundant for events constructed via
                # AgentStepEvent(...). Repeated intentionally: it returns
                # a fresh AgentStepResult from the body (event.body is a
                # frozen Mapping, not an AgentStepResult), and re-runs
                # the strict-at-boundary check on hand-built bodies that
                # might have skipped construction-time validation.
                result = AgentStepResult.from_payload(event.body)
        if result is None:
            raise RuntimeError(
                "stream ended without a terminal 'final' event"
            )
        return result


class InProcessBus:
    """A tiny in-memory pub/sub for ``AgentMessage`` envelopes.

    Reference transport for tests and demos. **Not** production-ready:
    no persistence, no backpressure, no delivery guarantees beyond
    "synchronous, in publish order, to all subscribers of the
    recipient."

    The bus routes purely on ``AgentMessage.recipient``. Addressing
    strings are opaque to the bus — the protocol does not prescribe a
    scheme. A subscriber that wants to reply addresses its response by
    the original message's ``sender`` and sets ``in_reply_to`` to the
    originating ``message_id``.

    The bus keeps an ordered log of every published message for test
    assertions; clear it with ``clear_log()`` between scenarios.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[AgentMessage], None]]] = (
            defaultdict(list)
        )
        self._log: list[AgentMessage] = []

    def subscribe(
        self,
        recipient: str,
        handler: Callable[[AgentMessage], None],
    ) -> None:
        """Register ``handler`` to receive every message published to ``recipient``."""
        self._subscribers[recipient].append(handler)

    def unsubscribe(
        self,
        recipient: str,
        handler: Callable[[AgentMessage], None],
    ) -> None:
        """Remove ``handler`` from ``recipient``'s subscriber list (idempotent)."""
        handlers = self._subscribers.get(recipient)
        if handlers is None:
            return
        try:
            handlers.remove(handler)
        except ValueError:
            pass

    def publish(self, message: AgentMessage) -> None:
        """Append to the log and deliver synchronously, in subscription order."""
        self._log.append(message)
        for handler in tuple(self._subscribers.get(message.recipient, ())):
            handler(message)

    @property
    def log(self) -> tuple[AgentMessage, ...]:
        """Immutable snapshot of every message published, in publish order."""
        return tuple(self._log)

    def clear_log(self) -> None:
        self._log.clear()


__all__ = ["InProcessBus", "SyncStreamAdapter"]
