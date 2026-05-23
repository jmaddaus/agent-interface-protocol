# ADR: Agent Interface Protocol

Status: Accepted

Date: 2026-05-21

## Context

Agent systems often have several boundaries: host-to-agent dispatch, scheduler-to-agent execution, agent-to-tool execution, and result streaming back to users or supervising systems. Without a stable protocol, semantic summaries, executable tool args, tool traces, and user-facing responses can drift into the same payload shape.

The long-term goal is a small independent protocol package that consuming applications can pin with semantic versioning.

## Decision

Introduce an immutable Agent Interface Protocol library. Protocol DTOs live in `contracts/agent_interface.py`.

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
