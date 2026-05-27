# Agent Interface Protocol

The agent interface is the stable contract for host-to-agent handoff, agent-to-agent handoff, and agent step results. The protocol DTOs live in `agent_interface_protocol/agent_interface.py` so new work can depend on one immutable library surface instead of copying local dictionaries across agent boundaries.

Architecture decision record: `docs/ADR_AGENT_INTERFACE_PROTOCOL.md`.

## Invariants

1. Handoffs separate executable input from semantic context.

   `AgentHandoff.args` is the target agent's tool/action input.
   `AgentHandoff.semantic_context` carries summaries, assumptions, decisions, constraints, and expected outcome. Do not put semantic summaries inside tool args.

2. Results separate meaning from tool history.

   `AgentStepResult.semantic_result` is the durable action summary, state-change summary, unresolved questions, followups, and observations. `AgentStepResult.tool_events` is an audit/debug stream of tools called while producing the result. Consumers should not parse tool events to recover semantic meaning.

3. Protocol objects are immutable.

   The public contract dataclasses are frozen and recursively freeze mapping/list values. Mutation requires constructing a new protocol object.

4. Public agent boundaries return `AgentStepResult`.

   Agent internals can use private helper shapes, but public step boundaries should expose protocol results. Dict-style `result["answer"]` and `result.get(...)` are intentionally unsupported at that boundary.

   Agent-specific details that are meaningful to callers belong in `AgentStepResult.semantic_result.extra`; telemetry is reserved for execution traces and token/debug accounting.

5. Dispatcher schemas are implementation-owned.

   Product-specific dispatcher tools and routing schemas belong to consuming applications. AIP owns the generic handoff/result envelope and does not prescribe scheduler, queue, dispatcher, or lane registry implementation details.

6. Parsing is strict at trust boundaries.

   `from_payload` rejects unknown top-level fields and wrong-typed values
   rather than coercing or dropping them. In-process construction stays
   lenient. Carry product-specific data in an `extra` field. The library
   emits `PROTOCOL_VERSION` and accepts any version in
   `SUPPORTED_PROTOCOL_VERSIONS`, preserving the incoming version on parse.

7. Transport identity is distinct from semantic identity.

   `AgentMessage.sender` / `recipient` are transport-layer routing
   identities (a queue topic, a service address, a router). They are
   intentionally separate from `AgentHandoff.source_agent` /
   `target_agent`, which are the semantic actors. Do not conflate them
   — a router may sit between sender and the semantic target.

8. Step events are ordered per producer.

   Within one `(handoff_id, step_id)` pair, `AgentStepEvent.seq` is
   monotonically increasing and gap-free per producer. Consumers may
   rely on `seq` for ordering, deduplication, and resume.

9. A step terminates exactly once.

   A step ends with one terminal signal — either an `AgentStepEvent` of
   kind `"final"` or an `AgentMessage` of kind `"step_result"`.
   Producers must not emit further events for the same `step_id` after
   the terminal signal.

10. Error codes are stable identifiers.

    `ErrorInfo.code` values are machine-readable. Do not parse
    `ErrorInfo.message` to recover semantics.

## Communication Layer

The contract has three layers. Each owns one concern; they are
designed to compose without leaking into each other.

**Layer 1 — Envelope: `AgentMessage`.**
Addressing, correlation, timing, transport identity. One envelope
carries one payload across a transport (queue, websocket, gRPC stream,
in-process bus). AIP defines the envelope shape but does not implement
any transport.

Envelope kinds (`AgentMessage.kind`):

| kind | payload | meaning |
| --- | --- | --- |
| `handoff` | `AgentHandoff` | dispatch a handoff to a target agent |
| `step_event` | `AgentStepEvent` | one event in an in-progress step |
| `step_result` | `AgentStepResult` | terminal step result (equivalent to a `step_event` of kind `final`) |
| `cancel` | `{handoff_id, reason}` | request cancellation of an in-flight handoff |
| `ack` | `{accepted, reason}` | acknowledge receipt of a prior message |
| `error` | `ErrorInfo` | transport- or control-plane-level error |

Cross-kind payloads (e.g. a `cancel`-shaped body sent as `kind="handoff"`)
are rejected at the parse boundary.

**Layer 2 — Lifecycle: `AgentStepEvent`.**
One event in the timeline of a single step. Multiple events make up a
step; the final event of a step carries an `AgentStepResult`. Each
event has a per-step `seq` for ordering/replay.

Event kinds (`AgentStepEvent.kind`):

| kind | body | meaning |
| --- | --- | --- |
| `accepted` | `{}` | the step has been acknowledged and is running |
| `progress` | `{fraction, message}` | advisory progress signal |
| `tool_event` | `ToolEvent` | one tool invocation in the trace |
| `partial_response` | `{text, delta}` | streamed user-visible text; `delta=True` appends, `False` replaces |
| `question` | `{question, schema}` | mid-step clarification request; `schema` is opaque to AIP |
| `final` | `AgentStepResult` | terminal event for the step |

**Layer 3 — Content: the existing semantic DTOs.**
`SemanticContext`, `SemanticResult`, `ExecutionPolicy`, `ToolEvent`,
`AgentHandoff`, and `AgentStepResult` are unchanged from v1. They
remain the durable, transport-agnostic meaning of a step.

### Example timeline

A handoff dispatched through an envelope, accepted, streaming one tool
event and one partial response, then terminating with a step result:

1. `AgentMessage{kind=handoff, message_id=m1, correlation_id=h1, payload=AgentHandoff{...}}`
2. `AgentMessage{kind=ack, in_reply_to=m1, payload={accepted: true, reason: ""}}`
3. `AgentMessage{kind=step_event, correlation_id=h1, payload=AgentStepEvent{kind=accepted, handoff_id=h1, step_id=s1, seq=0}}`
4. `AgentMessage{kind=step_event, correlation_id=h1, payload=AgentStepEvent{kind=tool_event, ..., seq=1, body=ToolEvent{...}}}`
5. `AgentMessage{kind=step_event, correlation_id=h1, payload=AgentStepEvent{kind=partial_response, ..., seq=2, body={text: "...", delta: true}}}`
6. `AgentMessage{kind=step_result, correlation_id=h1, in_reply_to=m1, payload=AgentStepResult{status=completed, ...}}`

Sync executors are still supported via `AgentExecutor.step` — they
return the terminal `AgentStepResult` directly, equivalent to draining
a `StreamingAgentExecutor.stream(handoff)` until the `final` event.

## Extension Points

- Add new semantic fields through `SemanticContext.extra`, `SemanticResult.extra`, or `ExecutionPolicy.extra` first. Promote them to first-class fields only when more than one consumer needs a stable named field.
- Add product-specific routing metadata through `AgentHandoff.args`, `AgentHandoff.action`, or `ExecutionPolicy.extra`; keep the dispatcher registry in the consuming application.
- Add a new inter-agent tool event by emitting `ToolEvent`; keep user meaning in `SemanticResult`.
- Carry transport-level metadata (auth tokens, hop counts, queue topics) outside AIP entirely; the envelope deliberately exposes only addressing/correlation/timing, not transport plumbing.
