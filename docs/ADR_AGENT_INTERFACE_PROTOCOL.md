# ADR: Agent Interface Protocol

Status: Accepted

Date: 2026-05-21

## Context

Agent systems often have several boundaries: host-to-agent dispatch, scheduler-to-agent execution, agent-to-tool execution, and result streaming back to users or supervising systems. Without a stable protocol, semantic summaries, executable tool args, tool traces, and user-facing responses can drift into the same payload shape.

The long-term goal is a small independent protocol package that consuming applications can pin with semantic versioning.

## Decision

Introduce an immutable Agent Interface Protocol library. Protocol DTOs live in `agent_interface_protocol/agent_interface.py`.

The protocol has three first-class surfaces:

- `AgentHandoff`: executable target lane/action args plus separate `SemanticContext` and `ExecutionPolicy`.
- `AgentStepResult`: status, user response/question/error, `SemanticResult`, and `ToolEvent` audit trail.
- `AgentExecutor`: minimal interface for future agent runtimes.

Dispatcher schemas, scheduler queues, thread stores, and UI adapters are implementation details for consuming applications. They should adapt to AIP instead of being part of AIP.

## Invariants

- Semantic data stays in `SemanticContext` or `SemanticResult`.
- Tool calls stay in `AgentHandoff.args` or `ToolEvent`.
- Protocol dataclasses are immutable and serialize to plain JSON-ready payloads.
- Public agent step boundaries return `AgentStepResult`.
- Agent-specific facts live in `SemanticResult.extra`, not telemetry.
- Telemetry is for traces, token accounting, and debug-only execution details.

## Consequences

New agent work should use the protocol library instead of inventing a new handoff/result dictionary. Existing runtimes can keep private helper shapes internally, but public boundaries should expose protocol objects.

For standalone use:

1. Keep protocol DTOs and conformance tests in this package.
2. Keep product-specific adapters in consuming applications.
3. Publish the package with semantic versioning.
4. Require downstream applications to pin an AIP version and reject unsupported `agent_interface_version` values.

## Follow-Ups

- Promote commonly reused `SemanticResult.extra` keys to first-class protocol fields only after more than one application or agent runtime needs them.
- Add conformance tests for third-party agent executors before external publication.
- Keep dispatcher registries outside AIP unless multiple independent implementations require a shared registry contract.
- Prefer rendering directly from `AgentStepResult.tool_events` for audit/debug surfaces.
- Maintain `SUPPORTED_PROTOCOL_VERSIONS` as an inclusive range, widening it
  before emitting a new version and narrowing it only after no producer can
  emit the old one, so rolling deploys never reject in-flight payloads.

---

# ADR Addendum: Communication Layer (v2)

Status: Accepted

Date: 2026-05-26

## Context

The v1 protocol surface was a synchronous function-call contract:
`AgentExecutor.step(request) -> AgentStepResult`. That shape is
adequate for an in-process executor but cannot express the realities
of agent-to-agent communication:

- long-running steps (no "started, check back" — `step()` must block
  until the result is final);
- streaming output (tokens, intermediate tool events, progress);
- mid-step dialogue (a clarification round-trip without terminating
  the step);
- transport identity (`source_agent`/`target_agent` are *semantic*
  actors and conflated with addressing if they double as transport
  identity — a router or queue topic is not the semantic target);
- fan-out / parallel calls (no parent/sibling correlation);
- cancellation or out-of-band control;
- subscription / replay (no per-step sequence numbers).

Consumers were beginning to invent local conventions — overloading
`telemetry`, packing transport IDs into `extra`, treating `tool_events`
as a stream — which is exactly the drift AIP was supposed to prevent.

## Decision

Introduce a transport/lifecycle layer above the existing semantic DTOs
without breaking them. Three layers, each owning one concern:

1. **Envelope (`AgentMessage`)** — addressing, correlation, timing,
   transport identity. Six discriminated `kind`s: `handoff`,
   `step_event`, `step_result`, `cancel`, `ack`, `error`.
2. **Lifecycle event (`AgentStepEvent`)** — one event in the timeline
   of a single step. Six discriminated `kind`s: `accepted`, `progress`,
   `tool_event`, `partial_response`, `question`, `final`. Per-step
   `seq` for ordering and replay.
3. **Content** — the existing v1 DTOs (`SemanticContext`,
   `SemanticResult`, `ExecutionPolicy`, `ToolEvent`, `AgentHandoff`,
   `AgentStepResult`) are unchanged and used as event/envelope bodies.

A typed `ErrorInfo { code, message, retriable, details }` is added for
structured transport-/control-plane errors. The existing
`AgentStepResult.error: str` is retained for backward compatibility.

A `StreamingAgentExecutor` interface is added alongside (not replacing)
the synchronous `AgentExecutor`. Sync remains valid and is equivalent
to draining the stream until the `final` event.

Protocol version is bumped to `2`. `MAX_SUPPORTED_PROTOCOL_VERSION` is
widened to `2`; `MIN_SUPPORTED_PROTOCOL_VERSION` stays at `1`. v1
payloads parse unchanged.

## Alternatives Considered

- **Single fat `AgentMessage` with all envelope and content fields
  flattened.** Rejected — couples transport identity to semantic
  identity, and forces every consumer to pattern-match on a sparse
  union shape rather than discriminating cleanly on `kind`.
- **Transport-specific schemas (one per queue/websocket/gRPC).**
  Rejected — defeats the purpose of a protocol package and pushes
  the same drift problem one layer down.
- **Replace `AgentExecutor.step` outright with a streaming-only
  interface.** Rejected — sync execution is a valid concrete case and
  the existing surface has consumers. Sync is preserved as the
  collapsed form of stream-then-take-final.
- **Embed `ErrorInfo` directly into `AgentStepResult.error` (typed
  field, breaking).** Deferred — would require a v3 with a real
  migration. The current `error: str` is preserved; `ErrorInfo` is
  used at the envelope layer and may be promoted into the result in a
  future major.

## Invariants (added)

- Envelope addressing (`sender`/`recipient`/`message_id`/
  `correlation_id`/`in_reply_to`) is transport-layer and distinct from
  the semantic `source_agent`/`target_agent` inside an `AgentHandoff`.
- `AgentStepEvent.seq` is monotonically increasing per
  `(handoff_id, step_id)` per producer.
- A step terminates exactly once — one `final` event or one
  `step_result` envelope. Producers must not emit further events for
  the same `step_id` after the terminal signal.
- `ErrorInfo.code` is the stable, machine-readable identifier;
  consumers must not parse `ErrorInfo.message` to recover semantics.

## Consequences

- New cross-process agent runtimes can ship `AgentMessage`s over any
  transport and remain conformant.
- Streaming and long-running steps now have a first-class shape
  instead of being approximated through `awaiting_input` +
  `retry_scheduled`.
- v1 producers continue to work unchanged during rolling deploys.
- AIP still owns no transport, no scheduler, and no ID generation.
  `message_id`/`step_id`/`sent_at`/`trace_id` are caller-supplied and
  opaque to AIP.
