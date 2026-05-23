# ADR: Agent Interface Protocol

Status: Accepted

Date: 2026-05-21

## Context

KKF Lite has several agent boundaries: host-to-lane dispatch,
scheduler-to-thread execution, lane-to-tool execution, and result
streaming back to the UI. Before AIP, those boundaries were mostly
pipeline-local dicts. That made interoperation easy to start but hard
to preserve: semantic summaries, executable tool args, tool traces, and
UI-facing responses could drift into the same payload shape.

The long-term goal is to extract this contract as an independent Agent
Interface Protocol repository. KKF Lite should consume it as a normal
library once that repo exists.

## Decision

Introduce an immutable Agent Interface Protocol library and wire the current
agent pipeline through it. In this standalone repo, the protocol DTOs live in
contracts/agent_interface.py.

The protocol has three first-class surfaces:

- `AgentHandoff`: executable target lane/action args plus separate
  `SemanticContext` and `ExecutionPolicy`.
- `AgentStepResult`: status, user response/question/error,
  `SemanticResult`, and `ToolEvent` audit trail.
- `AgentExecutor`: minimal interface for future agent runtimes.

Host dispatcher schemas live in
`kkf_lite.agent.pipeline.dispatcher_registry`, and `WorkItem` validates
dispatcher args before queue/scheduler execution.

## Invariants

- Semantic data stays in `SemanticContext` or `SemanticResult`.
- Tool calls stay in `AgentHandoff.args` or `ToolEvent`.
- Protocol dataclasses are immutable and serialize to plain JSON-ready
  payloads.
- Public lane orchestrators return `AgentStepResult`.
- Lane-specific facts live in `SemanticResult.extra`, not telemetry.
- Telemetry is for traces, token accounting, and debug-only execution
  details.

## Consequences

New agent work must use the protocol library instead of inventing a new
handoff/result dict. Existing lane internals can keep private helper
dicts while being migrated, but public boundaries must expose protocol
objects.

For standalone use:

1. Keep protocol DTOs and conformance tests in this repo.
2. Keep only KKF-specific adapters in `kkf_lite.agent.pipeline`.
3. Publish the package with semantic versioning.
4. Require downstream apps to pin an AIP version and reject unsupported
   `agent_interface_version` values.

## Follow-Ups

- Promote commonly reused `SemanticResult.extra` keys to first-class
  protocol fields only after another app or agent runtime needs them.
- Add conformance tests for third-party agent executors before external
  publication.
- Split dispatcher registries by product domain if non-KKF agents adopt
  the protocol.
- Retire the temporary `telemetry["inline_tools"]` UI bridge once the
  stream/UI layer renders directly from `AgentStepResult.tool_events`.
