# Agent Interface Protocol

The agent interface is the stable contract for host-to-agent handoff,
agent-to-agent handoff, and agent step results. It lives in this repo at contracts/agent_interface.py so new work can depend
on one immutable library surface instead of copying pipeline-local dicts.

Architecture decision record: `docs/ADR_AGENT_INTERFACE_PROTOCOL.md`.

## Invariants

1. Handoffs separate executable input from semantic context.

   `AgentHandoff.args` is the target agent's tool/action input.
   `AgentHandoff.semantic_context` carries summaries, assumptions,
   decisions, constraints, and expected outcome. Do not put semantic
   summaries inside tool args.

2. Results separate meaning from tool history.

   `AgentStepResult.semantic_result` is the durable action summary,
   state-change summary, unresolved questions, followups, and
   observations. `AgentStepResult.tool_events` is an audit/debug stream
   of tools called while producing the result. Consumers should not parse
   tool events to recover semantic meaning.

3. Protocol objects are immutable.

   The public contract dataclasses are frozen and recursively freeze
   mapping/list values. Mutation requires constructing a new protocol
   object.

4. Public lane orchestrators return `AgentStepResult`.

   Lane internals can still use `LaneOutcome` while being migrated, but
   the boundary exposed by each `wizard_*.orchestrate(...)` must return a
   protocol result. Dict-style `result["answer"]` and `result.get(...)`
   are intentionally unsupported at that boundary.

   Lane-specific details that are meaningful to callers belong in
   `AgentStepResult.semantic_result.extra`; telemetry is reserved for
   execution traces and token/debug accounting.

5. Dispatcher schemas are registry-owned.

   Host dispatcher tool schemas live in
   `kkf_lite.agent.pipeline.dispatcher_registry`. `WorkItem.from_dispatch`
   validates required dispatcher args against that registry before a
   handoff enters scheduler/queue execution.

## Extension Points

- Add new semantic fields through `SemanticContext.extra`,
  `SemanticResult.extra`, or `ExecutionPolicy.extra` first. Promote them
  to first-class fields only when more than one consumer needs a stable
  named field.
- Add a new dispatcher by updating `DISPATCHER_TO_LANE`,
  `DISPATCHER_TO_ACTION`, and `dispatcher_registry.HOST_TOOL_DEFS`
  together. The guardrail tests assert that registered dispatcher names
  stay in sync.
- Add a new inter-agent tool event by emitting `ToolEvent`; keep user
  meaning in `SemanticResult`.
