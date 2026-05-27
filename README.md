# Agent Interface Protocol

Agent Interface Protocol (AIP) is a small Python contract package for passing work between hosts, agents, tools, and agent runtimes without blurring semantic meaning, executable inputs, and audit traces.

The package centers on immutable DTOs that serialize to plain JSON-ready payloads. It intentionally does not prescribe a scheduler, dispatcher registry, queue, model provider, UI, or tool runtime. Those pieces belong in consuming applications.

## Why AIP Exists

Agent systems often pass around loosely shaped dictionaries. That works early, but it tends to mix concerns:

- executable tool arguments get mixed with summaries and assumptions;
- user-facing answers get inferred from tool logs;
- debugging traces become accidental business state;
- downstream agents depend on product-specific payload details.

AIP gives those concerns explicit places to live. Consumers can build any orchestration layer they want while keeping handoffs and step results stable.

## Core Concepts

**Content DTOs** (the semantic layer — unchanged since v1):

- `AgentHandoff`: executable target lane/action input plus semantic context and execution policy.
- `SemanticContext`: user goal, source summary, assumptions, decisions, constraints, observations, and extension data.
- `ExecutionPolicy`: scheduler/runtime hints such as write scope, dependencies, priority, confirmation requirements, and extension data.
- `AgentStepResult`: the result of one agent step, including status, user response/question/error, semantic result, tool events, updated handoff, and telemetry.
- `SemanticResult`: durable meaning produced by an agent step: action summary, state changes, unresolved questions, followups, observations, and extension data.
- `ToolEvent`: typed audit/debug record for one tool call.
- `AgentExecutor`: minimal structural interface for synchronous target-agent implementations.

**Communication DTOs** (added in v2 — see [Communication Layer](#communication-layer)):

- `AgentMessage`: transport envelope. Owns addressing (`sender`/`recipient`), correlation (`message_id`/`correlation_id`/`in_reply_to`), and timing. Carries one of six payload kinds (`handoff`, `step_event`, `step_result`, `cancel`, `ack`, `error`).
- `AgentStepEvent`: one event in the timeline of a single step. v2 kinds: `accepted`, `progress`, `tool_event`, `partial_response`, `question`, `final`. v3 adds `phase_started`, `phase_completed`, `checkpoint`, `evaluation`. Per-step `seq` enables ordering and replay.
- `ErrorInfo`: typed transport-/control-plane error (`code`, `message`, `retriable`, `details`).
- `StreamingAgentExecutor`: streaming-oriented executor interface alongside `AgentExecutor`.

**Orchestration DTOs** (added in v3 — optional, see [Orchestration and Harness Layer](#orchestration-and-harness-layer)):

- `OrchestrationContext`: descriptive metadata locating a message/event in a larger run — `run_id`, `step_id`, `phase` (`planner`/`handler`/`tool`/`narrator`/`evaluator`/custom), `capability`, `fanout_group_id`, `checkpoint_id`.
- `HarnessPolicy`: execution contract — `allowed_tools`, `required_outputs`, `max_tool_calls`, `max_steps`, `requires_self_evaluation`, `budget`.

## Invariants

1. Keep executable input in `AgentHandoff.args`.
2. Keep handoff meaning in `AgentHandoff.semantic_context`.
3. Keep durable result meaning in `AgentStepResult.semantic_result`.
4. Keep tool history in `AgentStepResult.tool_events`.
5. Do not parse tool event prose to recover semantic meaning.
6. Treat protocol objects as immutable; construct a new object for changes.
7. Reject unsupported `agent_interface_version` values at application boundaries.
8. Envelope addressing (`AgentMessage.sender`/`recipient`/`message_id`/`correlation_id`) is transport-layer and distinct from the semantic `source_agent`/`target_agent` inside `AgentHandoff`. Do not conflate them.
9. Within one `(handoff_id, step_id)`, `AgentStepEvent.seq` is monotonically increasing per producer. Use it for ordering, deduplication, and resume. AIP does not require `seq` to be gap-free; producers MAY emit gap-free sequences as a stronger guarantee, but consumers must not assume it unless the producer documents it.
10. A step terminates exactly once — one `AgentStepEvent` of kind `final` or one `AgentMessage` of kind `step_result`. Do not emit further events for the same `step_id` after termination. Producer contract; AIP cannot enforce it across messages.
11. `ErrorInfo.code` values are stable identifiers; do not parse `ErrorInfo.message` to recover semantics.
12. Orchestration identity (`run_id`, `step_id`, `phase`) is descriptive of execution topology and is distinct from transport identity (`message_id`, `correlation_id`). Do not conflate them.
13. `HarnessPolicy` is an execution contract: producers should emit events consistent with the declared policy, and consumers may reject or flag violations. AIP carries the policy but does not enforce it.
14. `phase` is an open string; reuse common labels (`planner`, `handler`, `tool`, `narrator`, `evaluator`) before inventing new ones.
15. `checkpoint` event `state` is opaque to AIP — preserved for resume/replay but not interpreted.
16. When `orchestration`, `harness_policy`, or `phase` appears on both an envelope and its inner event, producers MUST keep the values consistent across layers; the inner (event-level) value is authoritative for the event's content; consumers MAY treat divergence as an inconsistency error.
17. `AgentStepEvent` does not carry an `agent_interface_version`. Events are envelope-bound: producers that persist bare events outside an `AgentMessage` MUST persist the originating envelope's version separately, or wrap each persisted event in an envelope.

## Installation

This repository currently provides a source package. From a local checkout:

```bash
python -m pip install -e .
```

When published as a package, pin it like any other protocol dependency:

```bash
python -m pip install "agent-interface-protocol==0.4.*"
```

## Quick Example

```python
from agent_interface_protocol.agent_interface import (
    AgentHandoff,
    AgentStepResult,
    ExecutionPolicy,
    SemanticContext,
    SemanticResult,
    ToolEvent,
)

handoff = AgentHandoff(
    source_agent="host",
    target_agent="billing_agent",
    lane="billing",
    action="create_invoice",
    args={"customer_id": "cust_123", "amount": 1250},
    semantic_context=SemanticContext(
        user_goal="Create an invoice for the approved work.",
        source_summary="The customer approved the estimate for 1250.",
        expected_outcome="Draft an invoice and return the invoice id.",
    ),
    execution_policy=ExecutionPolicy(
        write_scope=("billing:invoices",),
        requires_confirmation=False,
    ),
)

payload = handoff.to_payload()
rebuilt = AgentHandoff.from_payload(payload)

result = AgentStepResult(
    status="completed",
    user_visible_response="Draft invoice inv_456 is ready.",
    semantic_result=SemanticResult(
        action_summary="Created draft invoice inv_456.",
        state_changes=("invoice:inv_456:draft",),
    ),
    tool_events=(
        ToolEvent(
            name="create_invoice",
            args={"customer_id": "cust_123", "amount": 1250},
            result='{"invoice_id": "inv_456"}',
            status="ok",
        ),
    ),
)
```

## Communication Layer

The content DTOs above describe *what* a step means. The communication
DTOs added in v2 describe *how* messages carrying that content move
between agents over time, without coupling AIP to any specific
transport.

Three layers:

1. **Envelope** — `AgentMessage` owns addressing, correlation, and timing. One envelope carries one payload across a transport (queue, websocket, gRPC stream, in-process bus).
2. **Lifecycle** — `AgentStepEvent` describes one event in a single step's timeline. Multiple events make up a step; the terminal `final` event carries an `AgentStepResult`. `seq` is producer-assigned and monotonically increasing per `(handoff_id, step_id)`.
3. **Content** — the v1 DTOs (`AgentHandoff`, `AgentStepResult`, etc.) ride inside envelopes and event bodies unchanged.

A typical streamed step looks like this on the wire:

```
AgentMessage(kind=handoff, message_id=m1, correlation_id=h1, payload=<AgentHandoff>)
AgentMessage(kind=ack, in_reply_to=m1, payload={accepted: true, reason: ""})
AgentMessage(kind=step_event, correlation_id=h1, payload=<AgentStepEvent kind=accepted seq=0>)
AgentMessage(kind=step_event, correlation_id=h1, payload=<AgentStepEvent kind=tool_event seq=1>)
AgentMessage(kind=step_event, correlation_id=h1, payload=<AgentStepEvent kind=partial_response seq=2>)
AgentMessage(kind=step_result, correlation_id=h1, in_reply_to=m1, payload=<AgentStepResult>)
```

In Python, the same exchange — dispatch, acceptance, one tool event,
and a terminal result — composes from the existing DTOs:

```python
from agent_interface_protocol import (
    AgentMessage,
    AgentStepEvent,
    AgentStepResult,
    SemanticResult,
    ToolEvent,
)

dispatch = AgentMessage(
    kind="handoff",
    message_id="m1",
    correlation_id="h1",
    sender="host@svc",
    recipient="billing@svc",
    payload=handoff.to_payload(),
)

accepted = AgentMessage(
    kind="step_event",
    correlation_id="h1",
    payload=AgentStepEvent(
        kind="accepted", handoff_id="h1", step_id="s1", seq=0,
    ).to_payload(),
)

tool_event = AgentMessage(
    kind="step_event",
    correlation_id="h1",
    payload=AgentStepEvent(
        kind="tool_event",
        handoff_id="h1", step_id="s1", seq=1,
        body=ToolEvent(
            name="create_invoice",
            args={"customer_id": "cust_123", "amount": 1250},
            result='{"invoice_id": "inv_456"}',
        ).to_payload(),
    ).to_payload(),
)

terminal = AgentMessage(
    kind="step_result",
    correlation_id="h1",
    in_reply_to="m1",
    payload=AgentStepResult(
        status="completed",
        user_visible_response="Draft invoice inv_456 is ready.",
        semantic_result=SemanticResult(
            action_summary="Created draft invoice inv_456.",
            state_changes=("invoice:inv_456:draft",),
        ),
    ).to_payload(),
)
```

`AgentMessage` owns transport identity (`sender`/`recipient`/
`message_id`/`correlation_id`/`in_reply_to`). The semantic
`source_agent`/`target_agent` stay inside the handoff — a router can
sit between the sender and the semantic target without losing meaning.

Synchronous executors are still supported. `AgentExecutor.step` returns
the terminal `AgentStepResult` directly — equivalent to draining
`StreamingAgentExecutor.stream(handoff)` until the `final` event.

Cross-kind payloads are rejected at the parse boundary: e.g. an
`ErrorInfo`-shaped body sent as `kind="handoff"` raises `ValueError`
because `AgentHandoff.from_payload` does not recognize `code` as a
top-level field.

v1 and v2 payloads parse unchanged under v3. `SUPPORTED_PROTOCOL_VERSIONS`
covers `1..3` for the duration of the v3 release.

## Orchestration and Harness Layer

v3 adds two optional, descriptive DTOs and four new event kinds for
runtimes that execute a step as a sequence of orchestration phases
(planner / handler / evaluator, observe / think / act, multi-agent
debate roles, etc.). Simple agents that don't orchestrate can ignore
this layer entirely — the fields default to `None` and the new kinds
are only emitted when needed.

```python
from agent_interface_protocol import (
    AgentMessage,
    AgentStepEvent,
    HarnessPolicy,
    OrchestrationContext,
)

planner_started = AgentMessage(
    kind="step_event",
    correlation_id="h1",
    payload=AgentStepEvent(
        kind="phase_started",
        handoff_id="h1", step_id="s1", seq=1,
        body={"phase": "planner", "message": "planning"},
    ).to_payload(),
    orchestration=OrchestrationContext(
        run_id="run-1",
        root_handoff_id="h1",
        step_id="s1",
        phase="planner",
        capability="pd_authoring",
    ),
    harness_policy=HarnessPolicy(
        contract_id="pd_authoring_v1",
        allowed_tools=("create_pd", "update_pd"),
        required_outputs=("pd_id",),
        max_tool_calls=12,
        max_steps=4,
        requires_self_evaluation=True,
        budget={"tokens": 50000, "wall_seconds": 60},
    ),
)
```

**Phase labels** are open strings, but reuse common values where they
fit: `planner`, `handler`, `tool`, `narrator`, `evaluator`. Custom
labels are allowed for product-specific topologies.

**Orchestration identity is distinct from transport identity.**
`run_id`/`step_id`/`phase` describe execution topology; `message_id`/
`correlation_id`/`in_reply_to` describe message transport. A router
can rewrite `sender`/`recipient` without disturbing the orchestration
topology, and an orchestrator can re-emit a step under a new `run_id`
without touching transport IDs.

**Harness policy is descriptive, not enforced by AIP.** Producers
should emit events consistent with the declared policy (don't call
disallowed tools, don't exceed limits, emit an `evaluation` event when
`requires_self_evaluation=True`). Consumers may reject or flag
violations. AIP carries the contract; runtimes own enforcement.

See [`docs/AGENT_INTERFACE_PROTOCOL.md`](docs/AGENT_INTERFACE_PROTOCOL.md)
for a worked multi-phase scenario (planner → handler → checkpoint →
evaluator → final).

## Serialization

All public DTOs provide `to_payload()` and `from_payload(...)` helpers. Payloads are plain dictionaries containing JSON-ready values. Nested mappings and sequences are recursively frozen in memory and thawed back to normal JSON-like structures during serialization.

```python
payload = result.to_payload()
round_tripped = AgentStepResult.from_payload(payload)
assert round_tripped == result
```

## Parsing at Trust Boundaries

Constructing a DTO in Python is lenient: values are normalized to the declared types for ergonomics. Parsing an external payload with `from_payload` is strict, because that is the trust boundary:

- unknown top-level fields raise `ValueError` (this catches typos such as `dispatch_args` instead of `args`, and forward-compatible fields emitted by a newer producer);
- wrong-typed fields raise `ValueError` instead of being silently coerced or dropped.

Put arbitrary or product-specific data inside an `extra` field rather than as new top-level keys, so it survives parsing instead of being rejected.

## Status Values

`AgentStepResult.status` must be one of:

- `completed`
- `awaiting_input`
- `failed`
- `retry_scheduled`
- `noop`

Unknown statuses raise `ValueError`.

## Extension Data

Use `.extra` fields before adding protocol-level fields:

- `SemanticContext.extra` for handoff-side semantic metadata.
- `SemanticResult.extra` for result-side semantic metadata.
- `ExecutionPolicy.extra` for scheduler/runtime policy metadata.

Promote an extension key to a first-class field only when multiple independent consumers need a stable named field.

## What AIP Does Not Own

AIP does not own:

- product-specific dispatcher tool schemas;
- queue or scheduler implementation;
- prompt formats;
- model-provider integrations;
- UI rendering;
- business-domain DTOs;
- persistence schemas;
- orchestration engines, admission controllers, or evaluators (AIP carries `OrchestrationContext` and `HarnessPolicy` but does not implement them);
- transport implementations (queues, websockets, gRPC bindings);
- ID minting (`message_id`, `run_id`, `step_id`, `checkpoint_id` are caller-supplied).

A consuming application should adapt those implementation details into `AgentHandoff` and `AgentStepResult`.

## JSON Schema Export

Every public DTO has a JSON Schema (Draft 2020-12) describing the same
shape its `from_payload` accepts. Use them to validate AIP payloads
from non-Python consumers (JavaScript, Go, Rust, schema-driven UI
tools) or to generate types in other languages.

Two ways to consume them:

```python
# At runtime — always in sync with the installed AIP version.
from agent_interface_protocol.schema import (
    agent_message_schema,
    json_schemas,
)

schema = agent_message_schema()  # one DTO
all_schemas = json_schemas()     # {"AgentMessage": {...}, "AgentHandoff": {...}, ...}
```

```bash
# Static files committed under schemas/ — for non-Python consumers
# reading the repo on GitHub.
ls schemas/
# AgentHandoff.json   AgentMessage.json     AgentStepEvent.json
# AgentStepResult.json  ErrorInfo.json      ExecutionPolicy.json
# HarnessPolicy.json    OrchestrationContext.json
# SemanticContext.json  SemanticResult.json  ToolEvent.json
```

Each schema is self-contained with its own `$defs` for nested types,
pruned to only those reachable from `$ref` in the schema body.
Discriminated unions (`AgentMessage.kind`, `AgentStepEvent.kind`) use
`oneOf` with `const` on the kind and the corresponding payload/body
shape per branch — cross-kind payloads fail validation the same way
they do in Python's `from_payload`.

**Necessary, not sufficient.** The schemas are a structural gate
matching `from_payload` at the trust boundary (type checking, enum
validation, unknown-field rejection). They do **not** require fields
that the Python DTOs default — for example, `{"kind": "handoff"}`
passes envelope validation because `kind` is the only required field,
even though a real handoff needs `payload` to be meaningful.
Non-Python consumers should treat schema validation as a necessary
first pass and run the same domain checks AIP's `from_payload` would
apply.

The schemas reflect *this* build of AIP — the protocol version range
and the event/message kind sets are pinned to what this version
accepts. Regenerate the static files after editing the schema module:

```bash
python scripts/generate_schemas.py
```

A test asserts the committed JSON files match the code output, so
forgotten regeneration surfaces on the next `pytest` run.

## Reference Implementations

The package ships a small `agent_interface_protocol.reference` module
with helpers for wiring the DTOs together in a single process. These
are **not** part of the stable protocol surface — they are reference
behavior for tests, demos, and simple single-process consumers, and
may evolve faster than the core DTOs. Import them explicitly:

```python
from agent_interface_protocol.reference import (
    InProcessBus,
    SyncStreamAdapter,
)
```

**`SyncStreamAdapter`** exposes a `StreamingAgentExecutor` through the
sync `AgentExecutor.step` contract. It drains `stream(handoff)`,
enforces invariants 9 and 10 (strictly-increasing `seq`, exactly one
terminal `final` event, no post-`final` events), and returns the
`AgentStepResult` from the `final` event:

```python
adapter = SyncStreamAdapter(streaming_executor)
result = adapter.step(handoff)  # or handoff.to_payload()
```

**`InProcessBus`** is a tiny in-memory pub/sub for `AgentMessage`
envelopes. Synchronous, in-publish-order delivery to all subscribers
of the recipient address; logs every published message for test
assertions:

```python
bus = InProcessBus()
bus.subscribe("host@svc", received.append)
bus.publish(AgentMessage(kind="ack", recipient="host@svc", ...))
assert bus.log == (...)
```

Production transports (queues, websockets, gRPC streams) are not in
scope for this package — see "What AIP Does Not Own."

## Development

Run tests from the repository root:

```bash
python -m pytest
```

The conformance tests cover immutability, serialization, protocol-version rejection and preservation, status validation, semantic/tool separation, non-mapping result behavior, and unknown-field and wrong-type rejection at parse boundaries. The v2 communication layer adds round-trip coverage per envelope/event `kind`, cross-kind payload rejection, `seq` ordering invariants, and v1 backwards-compatibility checks. v3 adds round-trip coverage for `OrchestrationContext`, `HarnessPolicy`, the four new event kinds, optional-field defaults, harness numeric-limit validation, and the orchestration/transport identity separation.

## Versioning

Protocol payloads include `agent_interface_version`. This package emits `PROTOCOL_VERSION` and accepts any version in `SUPPORTED_PROTOCOL_VERSIONS` (an inclusive range from `MIN_SUPPORTED_PROTOCOL_VERSION` to `MAX_SUPPORTED_PROTOCOL_VERSION`). `from_payload` preserves the incoming version rather than rewriting it, so a process that supports more than one version can accept old and new payloads side by side.

When introducing a new protocol version, widen the supported range *before* any producer starts emitting it. Keeping the previous version in the supported set during a rolling deploy avoids rejecting in-flight payloads while old and new processes run concurrently. Drop a version from the range only once no producer can still emit it.

Payloads outside the supported range raise `ValueError`. Enforce this at process boundaries, queue rehydration boundaries, and network boundaries.

## License

MIT. See [`LICENSE`](LICENSE).
