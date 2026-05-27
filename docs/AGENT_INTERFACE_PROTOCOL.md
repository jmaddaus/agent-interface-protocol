# Agent Interface Protocol

The agent interface is the stable contract for host-to-agent handoff, agent-to-agent handoff, and agent step results. The protocol DTOs live in `agent_interface_protocol/agent_interface.py` so new work can depend on one immutable library surface instead of copying local dictionaries across agent boundaries.

Architecture decision record: `docs/ADR_AGENT_INTERFACE_PROTOCOL.md`.

## Invariants

1. Handoffs separate executable input from semantic context.

   `AgentHandoff.args` is the target agent's tool/action input.
   `AgentHandoff`'s semantic fields — `user_goal`, `source_summary`, `assumptions`, `decisions`, `constraints`, `expected_outcome`, `observations` — carry the durable meaning of the handoff. Do not put semantic summaries inside tool args. (v4 hoisted these from the v3 nested `semantic_context` to keep wire-format depth shallow for LLM consumers.)

2. Results separate meaning from tool history.

   `AgentStepResult`'s semantic fields — `action_summary`, `state_changes`, `unresolved_questions`, `followups`, `observations` — are the durable result meaning. `AgentStepResult.tool_events` is an audit/debug stream of tools called while producing the result. Consumers should not parse tool events to recover semantic meaning. (v4 hoisted these from the v3 nested `semantic_result`.)

3. Protocol objects are immutable.

   The public contract dataclasses are frozen and recursively freeze mapping/list values. Mutation requires constructing a new protocol object.

4. Public agent boundaries return `AgentStepResult`.

   Agent internals can use private helper shapes, but public step boundaries should expose protocol results. Dict-style `result["answer"]` and `result.get(...)` are intentionally unsupported at that boundary.

   Agent-specific details that are meaningful to callers belong in `AgentStepResult.result_extra`; telemetry is reserved for execution traces and token/debug accounting.

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
   monotonically increasing per producer. Consumers may rely on `seq`
   for ordering, deduplication, and resume. AIP does not require
   `seq` to be gap-free; producers MAY emit gap-free sequences as a
   stronger guarantee that enables drop detection on resume, but
   consumers must not assume it unless the producer documents it.

9. A step terminates exactly once.

    A step ends with one terminal signal — either an `AgentStepEvent`
    of kind `"final"` or an `AgentMessage` of kind `"step_result"`.
    Producers must not emit further events for the same `step_id`
    after the terminal signal. This is a producer contract; AIP
    cannot enforce it across messages from a single object.

10. Error codes are stable identifiers.

    `ErrorInfo.code` values are machine-readable. Do not parse
    `ErrorInfo.message` to recover semantics.

11. Orchestration metadata is descriptive, not transport identity.

    `OrchestrationContext` fields (`run_id`, `step_id`, `phase`,
    `capability`, `fanout_group_id`, `checkpoint_id`) describe
    execution topology. `AgentMessage.message_id` /
    `correlation_id` / `in_reply_to` describe message transport.
    Do not conflate them — they answer different questions.

12. Harness policy is an execution contract.

    `HarnessPolicy.allowed_tools`, `required_outputs`,
    `max_tool_calls`, `max_steps`, and `requires_self_evaluation`
    declare what a producer must and may do. AIP carries the
    contract; producers should emit events consistent with it, and
    consumers may reject or flag violations.

13. Phase values are open strings; reuse common labels.

    `OrchestrationContext.phase` and the `phase` field on
    `phase_started` / `phase_completed` event bodies are open
    strings, but conventional values should be reused across
    runtimes: `planner`, `handler`, `tool`, `narrator`, `evaluator`.
    Custom phases are allowed for product-specific topologies.

14. Checkpoint bodies are opaque to AIP.

    `checkpoint` event bodies carry `checkpoint_id` and `state`.
    AIP preserves `state` for resume/replay but does not interpret
    it; runtimes own the schema.

15. Cross-layer metadata is consistent; the inner value is authoritative.

    `orchestration` and `harness_policy` may appear on both an
    `AgentMessage` envelope and the `AgentStepEvent` it carries.
    Likewise `phase` may appear in `OrchestrationContext.phase` and
    in `phase_started` / `phase_completed` event bodies. Producers
    MUST keep these values consistent across layers. If they
    diverge, the inner (event-level) value is authoritative for the
    event's content; the envelope-level value is a transport-routing
    convenience. Consumers MAY treat divergence as an inconsistency
    error and reject the message.

16. Events are envelope-bound for versioning.

    `AgentStepEvent` does not carry an `agent_interface_version`.
    Events are designed to ride inside an `AgentMessage` envelope,
    which carries the version. Producers that persist bare events
    outside an envelope (event-sourcing, log replay) MUST persist
    the originating envelope's `agent_interface_version` separately,
    or wrap each persisted event in an envelope.

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
| `phase_started` | `{phase, message}` | an orchestration phase has started |
| `phase_completed` | `{phase, summary, metrics}` | a phase has finished, with optional metrics |
| `checkpoint` | `{checkpoint_id, state}` | resume/replay marker; `state` is opaque to AIP |
| `evaluation` | `{passed, score, findings, details}` | result of self- or peer-evaluation |

**Layer 3 — Content: the semantic DTOs.**
`AgentHandoff`, `AgentStepResult`, `ToolEvent`, and `ErrorInfo` are
the durable, transport-agnostic meaning of a step. As of v4,
semantic-context, semantic-result, and execution-policy fields live
directly on `AgentHandoff` and `AgentStepResult` rather than in
nested sub-objects — the wire shape is intentionally flat so
LLM-emitted JSON stays at depth 2–3.

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

## Orchestration and Harness Layer (v3)

Many agent runtimes execute a step as a sequence of orchestration
phases — for example, a planner produces a sub-plan, a handler
executes it, and an evaluator scores the output against a rubric. v3
adds two optional, descriptive DTOs and four new event kinds to
represent this without committing AIP to any particular orchestration
model.

**`OrchestrationContext`** locates a message or event inside a larger
run:

| field | meaning |
| --- | --- |
| `run_id` | stable id for the full orchestrated run |
| `root_handoff_id` | originating handoff |
| `parent_step_id` | optional parent step in a fan-out / sub-task |
| `step_id` | current logical step |
| `phase` | open string: `planner`, `handler`, `tool`, `narrator`, `evaluator`, or a custom value |
| `capability` | capability being exercised, e.g. `pd_authoring`, `messaging.send` |
| `fanout_group_id` | groups parallel child steps |
| `checkpoint_id` | optional resume/checkpoint marker |
| `extra` | extension data |

**`HarnessPolicy`** declares execution constraints and admission policy:

| field | meaning |
| --- | --- |
| `contract_id` | harness/lane contract id |
| `allowed_tools` | tools the producer is permitted to call |
| `required_outputs` | outputs the consumer expects on completion |
| `max_tool_calls` / `max_steps` | non-negative limits or `null` |
| `requires_self_evaluation` | whether the producer must emit an `evaluation` event |
| `budget` | opaque token/time/cost budget (runtime-specific) |
| `extra` | extension data |

Both are optional fields on `AgentMessage` and `AgentStepEvent`.
Simple agents that don't orchestrate or run under a harness omit them
and pay no cost.

### Multi-phase scenario

A planner/handler/evaluator step with a checkpoint mid-handler:

1. `AgentMessage{kind=handoff, message_id=m1, correlation_id=h1, payload=AgentHandoff{...}, harness_policy=HarnessPolicy{contract_id=pd_authoring_v1, requires_self_evaluation=true, ...}}`
2. `AgentMessage{kind=step_event, payload=AgentStepEvent{kind=accepted, seq=0}, orchestration=OrchestrationContext{run_id=r1, step_id=s1}}`
3. `AgentMessage{kind=step_event, payload=AgentStepEvent{kind=phase_started, seq=1, body={phase: "planner", message: "planning"}}, orchestration=OrchestrationContext{run_id=r1, step_id=s1, phase=planner}}`
4. `AgentMessage{kind=step_event, payload=AgentStepEvent{kind=phase_completed, seq=2, body={phase: "planner", summary: "3 sub-steps", metrics: {sub_steps: 3, tokens: 1200}}}}`
5. `AgentMessage{kind=step_event, payload=AgentStepEvent{kind=phase_started, seq=3, body={phase: "handler", message: ""}}, orchestration=OrchestrationContext{run_id=r1, step_id=s1, phase=handler, capability=pd_authoring}}`
6. `AgentMessage{kind=step_event, payload=AgentStepEvent{kind=tool_event, seq=4, body=ToolEvent{name=create_pd, ...}}}`
7. `AgentMessage{kind=step_event, payload=AgentStepEvent{kind=checkpoint, seq=5, body={checkpoint_id: "ck-1", state: {cursor: 42, ...}}}}`
8. `AgentMessage{kind=step_event, payload=AgentStepEvent{kind=phase_completed, seq=6, body={phase: "handler", summary: "PD drafted", metrics: {...}}}}`
9. `AgentMessage{kind=step_event, payload=AgentStepEvent{kind=phase_started, seq=7, body={phase: "evaluator", message: ""}}, orchestration=OrchestrationContext{run_id=r1, step_id=s1, phase=evaluator}}`
10. `AgentMessage{kind=step_event, payload=AgentStepEvent{kind=evaluation, seq=8, body={passed: true, score: 0.92, findings: ["matches schema"], details: {rubric_version: "v3"}}}}`
11. `AgentMessage{kind=step_result, in_reply_to=m1, payload=AgentStepResult{status=completed, ...}}`

The transport identity (`message_id`, `correlation_id`, `in_reply_to`)
and the orchestration identity (`run_id`, `step_id`, `phase`) are
independent. A router can rewrite `sender`/`recipient` without
disturbing the orchestration topology, and an orchestrator can
re-emit a step under a new `run_id` without touching transport IDs.

## JSON Schema Export

Every public DTO has a corresponding JSON Schema (Draft 2020-12) in
`agent_interface_protocol.schema`, mirroring the shape `from_payload`
accepts. The same schemas are shipped as static files under
`agent_interface_protocol/schemas/` (in the wheel and sdist) for
non-Python consumers and codegen tools.

Discriminated unions (`AgentMessage.kind`, `AgentStepEvent.kind`) use
`oneOf` with `const` on the discriminator and the corresponding payload
/body shape per branch — cross-kind payloads fail schema validation
the same way they do in Python's `from_payload`.

The schemas are *necessary, not sufficient*: they enforce types, enums,
and unknown-field rejection, but defer fully-specified semantics (e.g.
a real `handoff` needs more than just `{"kind": "handoff"}`) to the
domain layer. Non-Python consumers should treat schema validation as a
first pass and run the same domain checks `from_payload` would.

A small CLI (`python -m agent_interface_protocol.schema`) emits the
schemas as JSON for piping into other-language toolchains; no
`jsonschema` runtime dependency required.

## Conformance Suite

`agent_interface_protocol.conformance` ships reusable assertions that
encode the invariants above — strictly-increasing `seq`, exactly one
terminal `final` event, no post-terminal emissions, structural contract
on `describe`/`validate_handoff`/`cancel`. Third-party packages
implementing `StreamingAgentExecutor` or `AgentExecutor` can call
`assert_streaming_executor_conformant` / `assert_sync_executor_conformant`
from their own test suites to claim protocol conformance and stay
aligned as new versions add new kinds.

Per-invariant helpers (`assert_seq_strictly_increasing`,
`assert_exactly_one_final`, `assert_no_events_after_final`,
`assert_kinds_are_known`, `assert_final_body_is_step_result`) are
exposed for cases where downstream wants more granular assertions.

## Extension Points

- Add new semantic fields through `AgentHandoff.context_extra`, `AgentStepResult.result_extra`, or `AgentHandoff.policy_extra` first. Promote them to first-class fields only when more than one consumer needs a stable named field.
- Add product-specific routing metadata through `AgentHandoff.args`, `AgentHandoff.action`, or `AgentHandoff.policy_extra`; keep the dispatcher registry in the consuming application.
- Add a new inter-agent tool event by emitting `ToolEvent`; keep user meaning in `AgentStepResult`'s semantic fields, not in tool event prose.
- Carry transport-level metadata (auth tokens, hop counts, queue topics) outside AIP entirely; the envelope deliberately exposes only addressing/correlation/timing, not transport plumbing.
