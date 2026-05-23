# Agent Interface Protocol

Agent Interface Protocol provides immutable Python DTOs for host-to-agent handoff, agent-to-agent handoff, and agent step results.

The package intentionally contains only protocol-owned contracts and documentation. Product-specific schedulers, dispatcher registries, lane orchestrators, UI bridges, and runtime adapters belong in consuming applications.

## Contents

- `contracts.agent_interface`: immutable AIP DTOs and serialization helpers.
- `docs/AGENT_INTERFACE_PROTOCOL.md`: protocol invariants.
- `docs/ADR_AGENT_INTERFACE_PROTOCOL.md`: protocol decision record.
- `tests/test_agent_interface_protocol.py`: protocol conformance tests.

## Verify

Run `python -m pytest` from the repository root.
