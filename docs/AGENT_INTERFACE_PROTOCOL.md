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

## Extension Points

- Add new semantic fields through `SemanticContext.extra`, `SemanticResult.extra`, or `ExecutionPolicy.extra` first. Promote them to first-class fields only when more than one consumer needs a stable named field.
- Add product-specific routing metadata through `AgentHandoff.args`, `AgentHandoff.action`, or `ExecutionPolicy.extra`; keep the dispatcher registry in the consuming application.
- Add a new inter-agent tool event by emitting `ToolEvent`; keep user meaning in `SemanticResult`.
