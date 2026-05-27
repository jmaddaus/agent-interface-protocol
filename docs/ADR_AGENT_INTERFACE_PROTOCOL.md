# ADR: Agent Interface Protocol

Status: Accepted

Date: 2026-05-21

## Context

Agent systems often have several boundaries: host-to-agent dispatch, scheduler-to-agent execution, agent-to-tool execution, and result streaming back to users or supervising systems. Without a stable protocol, semantic summaries, executable tool args, tool traces, and user-facing responses can drift into the same payload shape.

The long-term goal is a small independent protocol package that consuming applications can pin with semantic versioning.

## Decision

Introduce an immutable Agent Interface Protocol library. Protocol DTOs live in `agent_interface_protocol/agent_interface.py`.

The protocol has three first-class surfaces:

- `AgentHandoff`: executable target lane/action args plus semantic and policy fields at the top level (originally split into separate `SemanticContext` and `ExecutionPolicy` sub-objects; flattened into the parent DTO in v4 — see addendum).
- `AgentStepResult`: status, user response/question/error, semantic-result fields at the top level (originally a nested `SemanticResult`; flattened in v4), and `ToolEvent` audit trail.
- `AgentExecutor`: minimal interface for future agent runtimes.

Dispatcher schemas, scheduler queues, thread stores, and UI adapters are implementation details for consuming applications. They should adapt to AIP instead of being part of AIP.

## Invariants

- Semantic data stays in `AgentHandoff`'s semantic fields (handoff side) or `AgentStepResult`'s semantic fields (result side); see the v4 addendum for the flattened field list.
- Tool calls stay in `AgentHandoff.args` or `ToolEvent`.
- Protocol dataclasses are immutable and serialize to plain JSON-ready payloads.
- Public agent step boundaries return `AgentStepResult`.
- Agent-specific facts live in `AgentStepResult.result_extra`, not telemetry.
- Telemetry is for traces, token accounting, and debug-only execution details.

## Consequences

New agent work should use the protocol library instead of inventing a new handoff/result dictionary. Existing runtimes can keep private helper shapes internally, but public boundaries should expose protocol objects.

For standalone use:

1. Keep protocol DTOs and conformance tests in this package.
2. Keep product-specific adapters in consuming applications.
3. Publish the package with semantic versioning.
4. Require downstream applications to pin an AIP version and reject unsupported `agent_interface_version` values.

## Follow-Ups

- Promote commonly reused `AgentStepResult.result_extra` keys to first-class protocol fields only after more than one application or agent runtime needs them.
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

---

# ADR Addendum: Wire-Format Flattening (v4)

Status: Accepted

Date: 2026-05-27

## Context

The v1–v3 wire format nested semantic data inside DTOs:
`AgentHandoff.semantic_context.user_goal`,
`AgentStepResult.semantic_result.action_summary`,
`AgentStepResult.updated_handoff.semantic_context.extra`. That shape
is fine for code consumers, but LLMs — particularly flash/lite tier
models — drop braces, miss commas, and mis-nest at depth 4+. The
deepest LLM-emitted path (`AgentStepResult` carrying an
`updated_handoff` with populated `semantic_context.extra`) reached
depth 4; the envelope-wrapped form reached depth 6. Even the routine
`AgentStepResult` path was at depth 3, on the edge of where small
models start to fail.

Consumers were beginning to work around this by feeding LLMs
stringified JSON or hand-rolled flat shadows of the AIP schema —
exactly the drift the protocol exists to prevent.

## Decision

Flatten the wire format by dissolving the nested semantic and policy
sub-objects into their parent DTOs.

1. **Remove** `SemanticContext`, `SemanticResult`, and
   `ExecutionPolicy` as separate DTOs.
2. **Hoist** their fields onto `AgentHandoff` (semantic and policy)
   and `AgentStepResult` (semantic result). Field renames where
   needed to avoid collisions across hoisted scopes:
   `SemanticContext.extra` → `AgentHandoff.context_extra`,
   `ExecutionPolicy.extra` → `AgentHandoff.policy_extra`,
   `SemanticResult.extra` → `AgentStepResult.result_extra`.
3. **Detach** `AgentStepResult.updated_handoff` (embedded DTO) →
   `AgentStepResult.next_handoff_id` (string reference).
   Re-delegation is expressed by emitting a separate `AgentHandoff`
   message rather than nesting one inside a step result.

Net effect on LLM-emitted JSON depth:

| DTO | v3 worst case | v4 worst case |
|---|---|---|
| `AgentHandoff` | 3 | 2 |
| `AgentStepResult` | 4 | 3 |
| `AgentStepEvent` | 5 | 4 |
| `AgentMessage` | 6 | 5 |

`PROTOCOL_VERSION` is bumped to `4`. `MIN_SUPPORTED_PROTOCOL_VERSION`
is also bumped to `4` — this is a hard break, not a deprecation
window. v3-shape payloads are rejected at the parse boundary because
nested keys like `semantic_context` are no longer in the allowed
top-level field set. AIP is pre-PyPI; no external consumers exist
yet, so a clean break is preferable to dragging legacy parsing
through future versions.

## Alternatives Considered

- **Keep v3 nested form, add a parallel "flat" projection for
  LLMs.** Rejected — two shapes describing the same thing drift
  apart, double the test/doc surface, and create a permanent "which
  one do I use?" FAQ. Protocol versioning is the standard answer to
  shape evolution, not parallel formats.
- **Soften the break by accepting both v3 and v4 in `from_payload`
  for a transition window.** Rejected for this specific cut because
  AIP is pre-PyPI with no external consumers. The
  `MIN_SUPPORTED_PROTOCOL_VERSION` machinery stays in place for
  future version transitions where a rollout window matters.
- **String-encode the nested objects (`"semantic_context": "<JSON
  string>"`) to satisfy OpenAI strict structured outputs without
  changing wire format.** Rejected — LLMs are notably worse at
  emitting valid JSON-in-a-string than nested JSON, and it kills
  schema validation of the encoded content.
- **Make every property required and nullable to support OpenAI
  strict mode end-to-end.** Rejected — bloats wire payloads ~3×,
  degrades TypeScript/Go type generation for non-LLM consumers, and
  optimizes the protocol for one vendor's product policy.
- **Eliminate the `payload`/`body` envelope wrappers entirely
  (per-kind top-level schemas).** Deferred — would cut envelope
  depth further (`AgentMessage` from 5 to 3) but isn't needed for
  the LLM-emission use case, since LLMs emit payloads (`AgentHandoff`
  / `AgentStepResult`), not envelopes. The harness wraps the
  envelope around the model's output. Reconsider if a future
  consumer needs LLMs to emit `AgentMessage` directly.

## Invariants (added)

- Wire-format depth at LLM-facing DTOs is capped at 2 for
  `AgentHandoff` and 3 for `AgentStepResult`. The cap is a design
  constraint; new fields that would push depth above the cap require
  an ADR addendum justifying the trade.
- Re-delegation is by reference, not by embedding. An
  `AgentStepResult` that wants to chain to a new handoff sets
  `next_handoff_id` and the runtime emits a fresh `AgentHandoff`
  message; it does not inline the next handoff inside the result.
- v4 is the first hard break in AIP. The `MIN_SUPPORTED_PROTOCOL_VERSION`
  range mechanism is preserved for future transitions, but each
  version bump is now expected to decide explicitly whether it
  warrants a rolling-deploy window or a hard cut.

## Consequences

- LLM-emitted payloads stay under depth 3 in the normal case, which
  flash/lite tier models produce reliably.
- v1–v3 producers cannot interoperate with v4 consumers without an
  application-level translation layer. None exists in this package.
- Re-delegation flows have one more message (separate `AgentHandoff`
  emission) instead of embedding the next handoff inside the step
  result. Runtimes that previously read `result.updated_handoff`
  must instead watch for the follow-up handoff keyed by
  `next_handoff_id`.
- `SemanticContext`, `SemanticResult`, and `ExecutionPolicy` no
  longer exist as importable types. Code that constructed them
  directly must construct the parent DTO with hoisted fields.
- AIP still owns no transport, scheduler, or orchestration engine.
  The flatten is a wire-format change, not a scope change.
