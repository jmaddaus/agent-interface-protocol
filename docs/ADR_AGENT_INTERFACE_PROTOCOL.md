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

---

# ADR Addendum: Orchestration and Harness Layer (v3)

Status: Accepted

Date: 2026-05-26

## Context

v2 added a transport/lifecycle envelope but stopped at the boundary of
a single step. It cannot represent the inside of an orchestrated step:

- a planner phase that produces a sub-plan and a handler phase that
  executes it;
- checkpoint/resume markers within a long step;
- self- or peer-evaluation as a typed event rather than free-form
  observations;
- per-capability admission policies (allowed tools, required outputs,
  budget, max steps) that runtimes want to declare and validate
  against.

Runtimes were beginning to express these via `extra` bags on
`SemanticResult` / `OrchestrationContext`-shaped dicts under
`telemetry`, or product-specific dispatcher schemas — the same drift
v2 was meant to prevent.

## Decision

Add a small orchestration and harness vocabulary to v2's
communication layer without committing AIP to a particular
orchestration model.

1. **`OrchestrationContext`** — descriptive metadata locating a
   message/event in a larger run (`run_id`, `root_handoff_id`,
   `parent_step_id`, `step_id`, `phase`, `capability`,
   `fanout_group_id`, `checkpoint_id`, `extra`). Optional on
   `AgentMessage` and `AgentStepEvent`.
2. **`HarnessPolicy`** — execution contract (`contract_id`,
   `allowed_tools`, `required_outputs`, `max_tool_calls`,
   `max_steps`, `requires_self_evaluation`, `budget`, `extra`).
   Optional on `AgentMessage` and `AgentStepEvent`. Numeric limits
   must be non-negative or `null`.
3. **Four new `AgentStepEvent.kind`s**: `phase_started`,
   `phase_completed`, `checkpoint`, `evaluation`. Per-kind body
   shapes are validated at the parse boundary like the v2 kinds.

Phase values are open strings (`planner`, `handler`, `tool`,
`narrator`, `evaluator`, or custom) — AIP does not enforce a fixed
phase taxonomy, only documents conventional values.

`PROTOCOL_VERSION` is bumped to `3` and the supported range widens to
`1..3`. The new top-level fields and event kinds would be rejected by
v2 parsers under the strict-at-boundary policy, so this is a real
version bump, not a silent extension.

## Alternatives Considered

- **Embed orchestration fields directly into `AgentStepResult` /
  `AgentHandoff`.** Rejected — couples orchestration to semantic
  content, and forces every consumer (including ones that don't
  orchestrate) to know about run topology.
- **Put orchestration metadata inside `extra` bags.** Rejected —
  exactly the drift this commit is meant to prevent. `extra` is for
  product-specific data, not for cross-runtime conventions.
- **Standardize a phase enum.** Rejected — premature. Runtimes
  differ on phase taxonomy (planner/handler/evaluator vs.
  observe/think/act vs. roles in multi-agent debate). Open string
  with documented conventions covers more cases without locking any
  in.
- **Make orchestration/harness required fields.** Rejected — would
  force simple agents to fill in synthetic values. Optional + null
  default keeps the cost zero for non-orchestrated cases.

## Invariants (added)

- Orchestration metadata is descriptive, not transport identity.
  `run_id`/`step_id`/`phase` describe execution topology;
  `message_id`/`correlation_id` describe message transport.
- Harness policy is an execution contract. Producers should emit
  events consistent with the declared policy; consumers may reject
  or flag violations.
- `phase` values are open strings; reuse common labels (`planner`,
  `handler`, `tool`, `narrator`, `evaluator`).
- Checkpoint bodies are opaque to AIP. The `state` field is
  preserved for resume/replay but not interpreted.

## Consequences

- Planner/handler/evaluator-style runtimes can be expressed
  natively, including KKF-style harnesses, without leaking
  product-specific schemas into AIP.
- v1 and v2 consumers continue to parse unchanged. v3 producers must
  negotiate against the supported range before emitting v3-only
  fields or kinds.
- AIP still owns no orchestration engine — `OrchestrationContext`
  and `HarnessPolicy` describe topology and contract; they do not
  implement scheduling, admission, or evaluation logic. Runtimes
  own those.
