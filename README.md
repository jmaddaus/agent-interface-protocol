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

- `AgentHandoff`: executable target lane/action input plus semantic context and execution policy.
- `SemanticContext`: user goal, source summary, assumptions, decisions, constraints, observations, and extension data.
- `ExecutionPolicy`: scheduler/runtime hints such as write scope, dependencies, priority, confirmation requirements, and extension data.
- `AgentStepResult`: the result of one agent step, including status, user response/question/error, semantic result, tool events, updated handoff, and telemetry.
- `SemanticResult`: durable meaning produced by an agent step: action summary, state changes, unresolved questions, followups, observations, and extension data.
- `ToolEvent`: typed audit/debug record for one tool call.
- `AgentExecutor`: minimal structural interface for target-agent implementations.

## Invariants

1. Keep executable input in `AgentHandoff.args`.
2. Keep handoff meaning in `AgentHandoff.semantic_context`.
3. Keep durable result meaning in `AgentStepResult.semantic_result`.
4. Keep tool history in `AgentStepResult.tool_events`.
5. Do not parse tool event prose to recover semantic meaning.
6. Treat protocol objects as immutable; construct a new object for changes.
7. Reject unsupported `agent_interface_version` values at application boundaries.

## Installation

This repository currently provides a source package. From a local checkout:

```bash
python -m pip install -e .
```

When published as a package, pin it like any other protocol dependency:

```bash
python -m pip install "agent-interface-protocol==0.2.*"
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
- persistence schemas.

A consuming application should adapt those implementation details into `AgentHandoff` and `AgentStepResult`.

## Development

Run tests from the repository root:

```bash
python -m pytest
```

The conformance tests cover immutability, serialization, protocol-version rejection and preservation, status validation, semantic/tool separation, non-mapping result behavior, and unknown-field and wrong-type rejection at parse boundaries.

## Versioning

Protocol payloads include `agent_interface_version`. This package emits `PROTOCOL_VERSION` and accepts any version in `SUPPORTED_PROTOCOL_VERSIONS` (an inclusive range from `MIN_SUPPORTED_PROTOCOL_VERSION` to `MAX_SUPPORTED_PROTOCOL_VERSION`). `from_payload` preserves the incoming version rather than rewriting it, so a process that supports more than one version can accept old and new payloads side by side.

When introducing a new protocol version, widen the supported range *before* any producer starts emitting it. Keeping the previous version in the supported set during a rolling deploy avoids rejecting in-flight payloads while old and new processes run concurrently. Drop a version from the range only once no producer can still emit it.

Payloads outside the supported range raise `ValueError`. Enforce this at process boundaries, queue rehydration boundaries, and network boundaries.

## License

MIT. See [`LICENSE`](LICENSE).
