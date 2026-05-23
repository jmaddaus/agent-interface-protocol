# Agent Interface Protocol

Standalone copy of the Agent Interface Protocol contracts currently used by KKF Lite.

This repo intentionally contains only protocol-owned DTOs and documentation. KKF-specific scheduler adapters, dispatcher registries, WorkItem shapes, lane orchestrators, and UI bridges stay in KKF.

## Contents

- contracts.agent_interface: immutable AIP DTOs and serialization helpers.
- docs/AGENT_INTERFACE_PROTOCOL.md: protocol invariants.
- docs/ADR_AGENT_INTERFACE_PROTOCOL.md: extraction decision record.
- tests/test_agent_interface_protocol.py: protocol conformance tests.

## Verify

Run python -m pytest from the repo root.
