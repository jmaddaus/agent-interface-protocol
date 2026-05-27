"""JSON Schema export for AIP DTOs.

Each public DTO has a JSON Schema (Draft 2020-12) describing the same
shape its ``from_payload`` accepts. Use these schemas to validate AIP
payloads from non-Python consumers, or to generate types in other
languages.

The schemas reflect *this* build of AIP — the protocol version range
and event/kind sets are pinned to what this version accepts. When AIP
widens its supported version range or adds new kinds, the schemas
change; regenerate the static files under ``schemas/`` with
``python scripts/generate_schemas.py``.

Necessary-but-not-sufficient
----------------------------
The schemas are a structural gate, not a semantic one. They enforce
type, enum, and unknown-field rejection — matching ``from_payload`` at
the trust boundary — but they intentionally do not require fields that
the Python DTOs default. For example, ``{"kind": "handoff"}`` with no
``payload`` passes schema validation because the envelope's only
required field is ``kind``; a real handoff still needs ``payload`` to
be meaningful. Non-Python consumers should treat schema validation as
a necessary first pass and run the same domain checks AIP's
``from_payload`` would apply.

Usage::

    from agent_interface_protocol.schema import (
        agent_message_schema,
        agent_step_event_schema,
        agent_step_result_schema,
        agent_handoff_schema,
        json_schemas,
    )

    schema = agent_message_schema()
    # → ready to feed to jsonschema, ajv, gojsonschema, etc.

    all_schemas = json_schemas()
    # → {"AgentMessage": {...}, "AgentStepEvent": {...}, ...}
"""
from __future__ import annotations

from typing import Any

from agent_interface_protocol.agent_interface import (
    AGENT_MESSAGE_KINDS,
    AGENT_STEP_EVENT_KINDS,
    AGENT_STEP_STATUSES,
    MAX_SUPPORTED_PROTOCOL_VERSION,
    MIN_SUPPORTED_PROTOCOL_VERSION,
)

SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


# ---------------------------------------------------------------------------
# Small builders
# ---------------------------------------------------------------------------


def _string_array() -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}}


def _open_object() -> dict[str, Any]:
    return {"type": "object"}


def _protocol_version_field() -> dict[str, Any]:
    return {
        "type": "integer",
        "minimum": MIN_SUPPORTED_PROTOCOL_VERSION,
        "maximum": MAX_SUPPORTED_PROTOCOL_VERSION,
        "description": (
            "Protocol version. This build accepts versions in "
            f"[{MIN_SUPPORTED_PROTOCOL_VERSION}, "
            f"{MAX_SUPPORTED_PROTOCOL_VERSION}]; widening the range will "
            "be reflected in updated schemas."
        ),
    }


# ---------------------------------------------------------------------------
# Nested DTO definitions (used as $defs in every top-level schema)
# ---------------------------------------------------------------------------


def _semantic_context_def() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "user_goal": {"type": "string"},
            "source_summary": {"type": "string"},
            "assumptions": _string_array(),
            "decisions": _string_array(),
            "constraints": _string_array(),
            "expected_outcome": {"type": "string"},
            "observations": _string_array(),
            "extra": _open_object(),
        },
    }


def _semantic_result_def() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action_summary": {"type": "string"},
            "state_changes": _string_array(),
            "unresolved_questions": _string_array(),
            "followups": _string_array(),
            "observations": _string_array(),
            "extra": _open_object(),
        },
    }


def _execution_policy_def() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "write_scope": _string_array(),
            "dependency_keys": _string_array(),
            "priority": {"type": "integer"},
            "requires_confirmation": {"type": "boolean"},
            "max_steps": {"type": "integer"},
            "extra": _open_object(),
        },
    }


def _tool_event_def() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string"},
            "args": _open_object(),
            "result": {"type": "string"},
            "status": {"type": "string"},
            "ui_preview": {"type": "string"},
            "error": {"type": "string"},
        },
    }


def _error_info_def() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "code": {"type": "string"},
            "message": {"type": "string"},
            "retriable": {"type": "boolean"},
            "details": _open_object(),
        },
    }


def _orchestration_context_def() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "run_id": {"type": "string"},
            "root_handoff_id": {"type": "string"},
            "parent_step_id": {"type": "string"},
            "step_id": {"type": "string"},
            "phase": {"type": "string"},
            "capability": {"type": "string"},
            "fanout_group_id": {"type": "string"},
            "checkpoint_id": {"type": "string"},
            "extra": _open_object(),
        },
    }


def _harness_policy_def() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "contract_id": {"type": "string"},
            "allowed_tools": _string_array(),
            "required_outputs": _string_array(),
            "max_tool_calls": {"type": ["integer", "null"], "minimum": 0},
            "max_steps": {"type": ["integer", "null"], "minimum": 0},
            "requires_self_evaluation": {"type": "boolean"},
            "budget": _open_object(),
            "extra": _open_object(),
        },
    }


def _agent_handoff_def() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "agent_interface_version": _protocol_version_field(),
            "handoff_id": {"type": "string"},
            "source_agent": {"type": "string"},
            "target_agent": {"type": "string"},
            "lane": {"type": "string"},
            "action": {"type": "string"},
            "args": _open_object(),
            "semantic_context": {"$ref": "#/$defs/SemanticContext"},
            "execution_policy": {"$ref": "#/$defs/ExecutionPolicy"},
            "warnings": _string_array(),
        },
    }


def _agent_step_result_def() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "agent_interface_version": _protocol_version_field(),
            "status": {
                "type": "string",
                "enum": sorted(AGENT_STEP_STATUSES),
            },
            "user_visible_response": {"type": "string"},
            "semantic_result": {"$ref": "#/$defs/SemanticResult"},
            "tool_events": {
                "type": "array",
                "items": {"$ref": "#/$defs/ToolEvent"},
            },
            "question": {"type": "string"},
            "error": {"type": "string"},
            "updated_handoff": {
                "oneOf": [
                    {"$ref": "#/$defs/AgentHandoff"},
                    {"type": "null"},
                ],
            },
            "telemetry": _open_object(),
        },
    }


def _agent_step_event_def() -> dict[str, Any]:
    """AgentStepEvent inside $defs (used by AgentMessage.payload[step_event])."""
    return _build_agent_step_event_schema(include_defs=False)


def _all_definitions() -> dict[str, dict[str, Any]]:
    """Every nested type schema, keyed by name.

    A fresh dict each call so callers can mutate freely.
    """
    return {
        "SemanticContext": _semantic_context_def(),
        "SemanticResult": _semantic_result_def(),
        "ExecutionPolicy": _execution_policy_def(),
        "ToolEvent": _tool_event_def(),
        "ErrorInfo": _error_info_def(),
        "OrchestrationContext": _orchestration_context_def(),
        "HarnessPolicy": _harness_policy_def(),
        "AgentHandoff": _agent_handoff_def(),
        "AgentStepResult": _agent_step_result_def(),
        "AgentStepEvent": _agent_step_event_def(),
    }


# ---------------------------------------------------------------------------
# Per-kind body / payload shapes for discriminated unions
# ---------------------------------------------------------------------------


def _step_event_body_branches() -> list[dict[str, Any]]:
    """One ``oneOf`` branch per AgentStepEvent.kind."""
    bodies: list[tuple[str, dict[str, Any]]] = [
        ("accepted", {"type": "object", "additionalProperties": False}),
        (
            "progress",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "fraction": {"type": ["number", "null"]},
                    "message": {"type": "string"},
                },
            },
        ),
        ("tool_event", {"$ref": "#/$defs/ToolEvent"}),
        (
            "partial_response",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "text": {"type": "string"},
                    "delta": {"type": "boolean"},
                },
            },
        ),
        (
            "question",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "question": {"type": "string"},
                    "schema": _open_object(),
                },
            },
        ),
        ("final", {"$ref": "#/$defs/AgentStepResult"}),
        (
            "phase_started",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "phase": {"type": "string"},
                    "message": {"type": "string"},
                },
            },
        ),
        (
            "phase_completed",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "phase": {"type": "string"},
                    "summary": {"type": "string"},
                    "metrics": _open_object(),
                },
            },
        ),
        (
            "checkpoint",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "checkpoint_id": {"type": "string"},
                    "state": _open_object(),
                },
            },
        ),
        (
            "evaluation",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "passed": {"type": "boolean"},
                    "score": {"type": ["number", "null"]},
                    "findings": _string_array(),
                    "details": _open_object(),
                },
            },
        ),
    ]
    return [
        {
            "properties": {
                "kind": {"const": kind},
                "body": body_schema,
            },
        }
        for kind, body_schema in bodies
    ]


def _agent_message_payload_branches() -> list[dict[str, Any]]:
    """One ``oneOf`` branch per AgentMessage.kind."""
    payloads: list[tuple[str, dict[str, Any]]] = [
        ("handoff", {"$ref": "#/$defs/AgentHandoff"}),
        ("step_event", {"$ref": "#/$defs/AgentStepEvent"}),
        ("step_result", {"$ref": "#/$defs/AgentStepResult"}),
        (
            "cancel",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "handoff_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        ),
        (
            "ack",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "accepted": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
            },
        ),
        ("error", {"$ref": "#/$defs/ErrorInfo"}),
    ]
    return [
        {
            "properties": {
                "kind": {"const": kind},
                "payload": payload_schema,
            },
        }
        for kind, payload_schema in payloads
    ]


# ---------------------------------------------------------------------------
# Reachability: include only the ``$defs`` that a given schema actually
# references (transitively). Validators ignore unused ``$defs`` so this
# is purely cosmetic, but committed JSON files are smaller and easier
# to read on GitHub when each schema carries only what it needs.
# ---------------------------------------------------------------------------

_REF_PREFIX = "#/$defs/"


def _collect_refs(node: Any, found: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if (
                key == "$ref"
                and isinstance(value, str)
                and value.startswith(_REF_PREFIX)
            ):
                found.add(value[len(_REF_PREFIX):])
            else:
                _collect_refs(value, found)
    elif isinstance(node, list):
        for item in node:
            _collect_refs(item, found)


def _reachable_defs(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Transitive closure of ``$defs`` reachable from ``body`` via ``$ref``.

    Walks the schema body, collects every ``$ref`` target, and follows
    each target's own refs until the closure is stable.
    """
    all_defs = _all_definitions()
    seen: set[str] = set()
    frontier: set[str] = set()
    _collect_refs(body, frontier)
    while frontier:
        nxt: set[str] = set()
        for name in frontier:
            if name in seen or name not in all_defs:
                continue
            seen.add(name)
            inner: set[str] = set()
            _collect_refs(all_defs[name], inner)
            nxt.update(inner - seen)
        frontier = nxt
    return {name: all_defs[name] for name in sorted(seen)}


# ---------------------------------------------------------------------------
# Top-level builders
# ---------------------------------------------------------------------------


def _build_agent_step_event_schema(*, include_defs: bool) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "title": "AgentStepEvent",
        "description": "One event in the timeline of a single agent step.",
        "type": "object",
        "additionalProperties": False,
        "required": ["kind"],
        "properties": {
            "kind": {
                "type": "string",
                "enum": sorted(AGENT_STEP_EVENT_KINDS),
            },
            "handoff_id": {"type": "string"},
            "step_id": {"type": "string"},
            "seq": {"type": "integer", "minimum": 0},
            "ts": {"type": "string"},
            "body": _open_object(),
            "orchestration": {
                "oneOf": [
                    {"$ref": "#/$defs/OrchestrationContext"},
                    {"type": "null"},
                ],
            },
            "harness_policy": {
                "oneOf": [
                    {"$ref": "#/$defs/HarnessPolicy"},
                    {"type": "null"},
                ],
            },
        },
        "oneOf": _step_event_body_branches(),
    }
    if include_defs:
        body = {k: v for k, v in schema.items()}
        schema = {
            "$schema": SCHEMA_DIALECT,
            **schema,
            "$defs": _reachable_defs(body),
        }
    return schema


def agent_handoff_schema() -> dict[str, Any]:
    body = _agent_handoff_def()
    return {
        "$schema": SCHEMA_DIALECT,
        "title": "AgentHandoff",
        "description": (
            "Immutable handoff between agents. Carries executable args, "
            "semantic context, and execution policy."
        ),
        **body,
        "$defs": _reachable_defs(body),
    }


def agent_step_result_schema() -> dict[str, Any]:
    body = _agent_step_result_def()
    return {
        "$schema": SCHEMA_DIALECT,
        "title": "AgentStepResult",
        "description": "Immutable result of one target-agent step.",
        **body,
        "$defs": _reachable_defs(body),
    }


def agent_step_event_schema() -> dict[str, Any]:
    return _build_agent_step_event_schema(include_defs=True)


def agent_message_schema() -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind"],
        "properties": {
            "agent_interface_version": _protocol_version_field(),
            "kind": {
                "type": "string",
                "enum": sorted(AGENT_MESSAGE_KINDS),
            },
            "message_id": {"type": "string"},
            "correlation_id": {"type": "string"},
            "in_reply_to": {"type": "string"},
            "sender": {"type": "string"},
            "recipient": {"type": "string"},
            "sent_at": {"type": "string"},
            "trace_id": {"type": "string"},
            "payload": _open_object(),
            "orchestration": {
                "oneOf": [
                    {"$ref": "#/$defs/OrchestrationContext"},
                    {"type": "null"},
                ],
            },
            "harness_policy": {
                "oneOf": [
                    {"$ref": "#/$defs/HarnessPolicy"},
                    {"type": "null"},
                ],
            },
        },
        "oneOf": _agent_message_payload_branches(),
    }
    return {
        "$schema": SCHEMA_DIALECT,
        "title": "AgentMessage",
        "description": (
            "Transport envelope carrying one AIP payload between agents. "
            "Owns addressing, correlation, and timing; the payload is "
            "discriminated by kind."
        ),
        **body,
        "$defs": _reachable_defs(body),
    }


def semantic_context_schema() -> dict[str, Any]:
    return {
        "$schema": SCHEMA_DIALECT,
        "title": "SemanticContext",
        **_semantic_context_def(),
    }


def semantic_result_schema() -> dict[str, Any]:
    return {
        "$schema": SCHEMA_DIALECT,
        "title": "SemanticResult",
        **_semantic_result_def(),
    }


def execution_policy_schema() -> dict[str, Any]:
    return {
        "$schema": SCHEMA_DIALECT,
        "title": "ExecutionPolicy",
        **_execution_policy_def(),
    }


def tool_event_schema() -> dict[str, Any]:
    return {
        "$schema": SCHEMA_DIALECT,
        "title": "ToolEvent",
        **_tool_event_def(),
    }


def error_info_schema() -> dict[str, Any]:
    return {
        "$schema": SCHEMA_DIALECT,
        "title": "ErrorInfo",
        **_error_info_def(),
    }


def orchestration_context_schema() -> dict[str, Any]:
    return {
        "$schema": SCHEMA_DIALECT,
        "title": "OrchestrationContext",
        **_orchestration_context_def(),
    }


def harness_policy_schema() -> dict[str, Any]:
    return {
        "$schema": SCHEMA_DIALECT,
        "title": "HarnessPolicy",
        **_harness_policy_def(),
    }


def json_schemas() -> dict[str, dict[str, Any]]:
    """Return every public DTO's JSON Schema keyed by class name.

    Each value is a self-contained JSON Schema Draft 2020-12 document
    with its own ``$defs`` for any nested types. A fresh dict each call.
    """
    return {
        "AgentHandoff": agent_handoff_schema(),
        "AgentStepResult": agent_step_result_schema(),
        "AgentStepEvent": agent_step_event_schema(),
        "AgentMessage": agent_message_schema(),
        "SemanticContext": semantic_context_schema(),
        "SemanticResult": semantic_result_schema(),
        "ExecutionPolicy": execution_policy_schema(),
        "ToolEvent": tool_event_schema(),
        "ErrorInfo": error_info_schema(),
        "OrchestrationContext": orchestration_context_schema(),
        "HarnessPolicy": harness_policy_schema(),
    }


__all__ = [
    "SCHEMA_DIALECT",
    "agent_handoff_schema",
    "agent_message_schema",
    "agent_step_event_schema",
    "agent_step_result_schema",
    "semantic_context_schema",
    "semantic_result_schema",
    "execution_policy_schema",
    "tool_event_schema",
    "error_info_schema",
    "orchestration_context_schema",
    "harness_policy_schema",
    "json_schemas",
]


# ---------------------------------------------------------------------------
# CLI: python -m agent_interface_protocol.schema [NAME] [--all] [--list]
# ---------------------------------------------------------------------------


def _cli(argv: list[str] | None = None) -> int:
    """Print a schema (or list of schema names) to stdout.

    No dependency on ``jsonschema`` — just emits the schema dict as
    JSON. Useful in CI pipelines that feed schemas to non-Python
    codegen or validation tools.
    """
    import argparse
    import json as _json
    import sys

    parser = argparse.ArgumentParser(
        prog="python -m agent_interface_protocol.schema",
        description=(
            "Print a JSON Schema for an AIP DTO. With no arguments, "
            "lists the available DTO names."
        ),
    )
    parser.add_argument(
        "name",
        nargs="?",
        help="DTO name (e.g. AgentMessage). Omit with --list to enumerate.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available DTO names and exit.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Dump every schema as one JSON object keyed by DTO name.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indent (default: 2). Use 0 for a single line.",
    )

    args = parser.parse_args(argv)
    schemas = json_schemas()
    indent: int | None = args.indent if args.indent > 0 else None

    if args.all:
        print(_json.dumps(schemas, indent=indent, sort_keys=True))
        return 0

    if args.list or args.name is None:
        for name in sorted(schemas):
            print(name)
        return 0

    if args.name not in schemas:
        print(f"unknown schema: {args.name!r}", file=sys.stderr)
        print(
            f"available: {', '.join(sorted(schemas))}", file=sys.stderr,
        )
        return 2

    print(_json.dumps(schemas[args.name], indent=indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
