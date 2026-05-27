"""Immutable Agent Interface Protocol DTOs.

The protocol separates semantic state from execution state:

* semantic context/result describe what the agent believes happened
  and what should happen next;
* tool events describe what was invoked and what came back.

Tool calls are an execution trace, not the source of semantic meaning.

Construction vs. parsing
------------------------
Constructing a DTO directly in Python is treated as trusted: inputs are
normalized (coerced to the declared types) for ergonomics. Parsing an
external payload with ``from_payload`` is treated as a trust boundary: it
rejects unknown fields and wrong-typed values instead of silently
coercing or dropping them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterator, Literal, Mapping


# Version this build emits when serializing freshly-constructed objects.
PROTOCOL_VERSION = 2

# Inclusive range of protocol versions this build can parse. Widen this
# (not just PROTOCOL_VERSION) when adding a new version so that services
# deploying on a rolling basis can accept both the old and the new payload
# during the rollout window.
MIN_SUPPORTED_PROTOCOL_VERSION = 1
MAX_SUPPORTED_PROTOCOL_VERSION = 2
SUPPORTED_PROTOCOL_VERSIONS: frozenset[int] = frozenset(
    range(MIN_SUPPORTED_PROTOCOL_VERSION, MAX_SUPPORTED_PROTOCOL_VERSION + 1)
)

AgentStepStatus = Literal[
    "completed",
    "awaiting_input",
    "failed",
    "retry_scheduled",
    "noop",
]

AGENT_STEP_STATUSES: frozenset[str] = frozenset({
    "completed",
    "awaiting_input",
    "failed",
    "retry_scheduled",
    "noop",
})


# ---------------------------------------------------------------------------
# Normalization helpers (trusted, in-process construction path)
# ---------------------------------------------------------------------------

def _freeze_value(value: Any) -> Any:
    if isinstance(value, MappingProxyType):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({
            str(k): _freeze_value(v)
            for k, v in value.items()
        })
    if isinstance(value, tuple):
        return tuple(_freeze_value(v) for v in value)
    if isinstance(value, list):
        return tuple(_freeze_value(v) for v in value)
    if isinstance(value, set):
        return tuple(_freeze_value(v) for v in sorted(value, key=str))
    return value


def _thaw_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(k): _thaw_value(v)
            for k, v in value.items()
        }
    if isinstance(value, tuple):
        return [_thaw_value(v) for v in value]
    return value


def _tuple_of_str(values: Any) -> tuple[str, ...]:
    return tuple(str(v) for v in (values or ()) if str(v))


def _frozen_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return _freeze_value(dict(value or {}))


def _validate_protocol_version(value: Any) -> int:
    raw = PROTOCOL_VERSION if value in (None, "") else value
    if isinstance(raw, bool):
        raise ValueError(f"unparseable agent_interface_version {value!r}")
    try:
        version = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"unparseable agent_interface_version {value!r}")
    if version not in SUPPORTED_PROTOCOL_VERSIONS:
        raise ValueError(
            f"unsupported agent_interface_version {version} "
            f"(supported: {sorted(SUPPORTED_PROTOCOL_VERSIONS)})"
        )
    return version


# ---------------------------------------------------------------------------
# Strict parsing helpers (untrusted payload boundary path)
# ---------------------------------------------------------------------------

def _require_mapping(payload: Any, where: str) -> dict[str, Any]:
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise ValueError(
            f"{where} payload must be a mapping, got {type(payload).__name__}"
        )
    return dict(payload)


def _reject_unknown_keys(
    data: Mapping[str, Any], allowed: frozenset[str], where: str,
) -> None:
    unknown = sorted(str(k) for k in data if k not in allowed)
    if unknown:
        raise ValueError(f"unknown {where} field(s): {unknown}")


def _parse_str(data: Mapping[str, Any], key: str, where: str) -> str:
    value = data.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(
            f"{where} field {key!r} must be a string, "
            f"got {type(value).__name__}"
        )
    return value


def _parse_str_tuple(
    data: Mapping[str, Any], key: str, where: str,
) -> tuple[str, ...]:
    value = data.get(key)
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise ValueError(f"{where} field {key!r} must be a list of strings")
    out: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(
                f"{where} field {key!r}[{index}] must be a string, "
                f"got {type(item).__name__}"
            )
        out.append(item)
    return tuple(out)


def _parse_mapping(
    data: Mapping[str, Any], key: str, where: str,
) -> Mapping[str, Any]:
    value = data.get(key)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(
            f"{where} field {key!r} must be a mapping, "
            f"got {type(value).__name__}"
        )
    return value


def _parse_mapping_tuple(
    data: Mapping[str, Any], key: str, where: str,
) -> tuple[Mapping[str, Any], ...]:
    value = data.get(key)
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise ValueError(f"{where} field {key!r} must be a list")
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise ValueError(
                f"{where} field {key!r}[{index}] must be a mapping, "
                f"got {type(item).__name__}"
            )
    return tuple(value)


def _parse_int(
    data: Mapping[str, Any], key: str, where: str, default: int,
) -> int:
    value = data.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"{where} field {key!r} must be an integer, "
            f"got {type(value).__name__}"
        )
    return value


def _parse_bool(
    data: Mapping[str, Any], key: str, where: str, default: bool,
) -> bool:
    value = data.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(
            f"{where} field {key!r} must be a boolean, "
            f"got {type(value).__name__}"
        )
    return value


def _parse_optional_number(
    data: Mapping[str, Any], key: str, where: str,
) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"{where} field {key!r} must be a number or null, "
            f"got {type(value).__name__}"
        )
    return float(value)


_SEMANTIC_CONTEXT_KEYS: frozenset[str] = frozenset({
    "user_goal",
    "source_summary",
    "assumptions",
    "decisions",
    "constraints",
    "expected_outcome",
    "observations",
    "extra",
})


@dataclass(frozen=True)
class SemanticContext:
    """Meaning passed to the receiving agent.

    This is deliberately independent from tool-call transcripts. A peer
    agent should be able to understand the user's goal, constraints, and
    decisions without replaying or parsing low-level tool invocations.
    """

    user_goal: str = ""
    source_summary: str = ""
    assumptions: tuple[str, ...] = field(default_factory=tuple)
    decisions: tuple[str, ...] = field(default_factory=tuple)
    constraints: tuple[str, ...] = field(default_factory=tuple)
    expected_outcome: str = ""
    observations: tuple[str, ...] = field(default_factory=tuple)
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_goal", str(self.user_goal or ""))
        object.__setattr__(
            self, "source_summary", str(self.source_summary or ""),
        )
        object.__setattr__(self, "assumptions", _tuple_of_str(self.assumptions))
        object.__setattr__(self, "decisions", _tuple_of_str(self.decisions))
        object.__setattr__(self, "constraints", _tuple_of_str(self.constraints))
        object.__setattr__(
            self, "expected_outcome", str(self.expected_outcome or ""),
        )
        object.__setattr__(
            self, "observations", _tuple_of_str(self.observations),
        )
        object.__setattr__(self, "extra", _frozen_mapping(self.extra))

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> "SemanticContext":
        data = _require_mapping(payload, "SemanticContext")
        _reject_unknown_keys(data, _SEMANTIC_CONTEXT_KEYS, "SemanticContext")
        return cls(
            user_goal=_parse_str(data, "user_goal", "SemanticContext"),
            source_summary=_parse_str(data, "source_summary", "SemanticContext"),
            assumptions=_parse_str_tuple(data, "assumptions", "SemanticContext"),
            decisions=_parse_str_tuple(data, "decisions", "SemanticContext"),
            constraints=_parse_str_tuple(data, "constraints", "SemanticContext"),
            expected_outcome=_parse_str(
                data, "expected_outcome", "SemanticContext",
            ),
            observations=_parse_str_tuple(data, "observations", "SemanticContext"),
            extra=_parse_mapping(data, "extra", "SemanticContext"),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "user_goal": self.user_goal,
            "source_summary": self.source_summary,
            "assumptions": list(self.assumptions),
            "decisions": list(self.decisions),
            "constraints": list(self.constraints),
            "expected_outcome": self.expected_outcome,
            "observations": list(self.observations),
            "extra": _thaw_value(self.extra),
        }


_SEMANTIC_RESULT_KEYS: frozenset[str] = frozenset({
    "action_summary",
    "state_changes",
    "unresolved_questions",
    "followups",
    "observations",
    "extra",
})


@dataclass(frozen=True)
class SemanticResult:
    """Meaning produced by an agent step.

    This is the durable, interoperable summary. Tool events remain
    available for audit/debugging, but consumers should not infer the
    semantic result by parsing them.
    """

    action_summary: str = ""
    state_changes: tuple[str, ...] = field(default_factory=tuple)
    unresolved_questions: tuple[str, ...] = field(default_factory=tuple)
    followups: tuple[str, ...] = field(default_factory=tuple)
    observations: tuple[str, ...] = field(default_factory=tuple)
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_summary", str(self.action_summary or ""))
        object.__setattr__(
            self, "state_changes", _tuple_of_str(self.state_changes),
        )
        object.__setattr__(
            self, "unresolved_questions",
            _tuple_of_str(self.unresolved_questions),
        )
        object.__setattr__(self, "followups", _tuple_of_str(self.followups))
        object.__setattr__(
            self, "observations", _tuple_of_str(self.observations),
        )
        object.__setattr__(self, "extra", _frozen_mapping(self.extra))

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> "SemanticResult":
        data = _require_mapping(payload, "SemanticResult")
        _reject_unknown_keys(data, _SEMANTIC_RESULT_KEYS, "SemanticResult")
        return cls(
            action_summary=_parse_str(data, "action_summary", "SemanticResult"),
            state_changes=_parse_str_tuple(data, "state_changes", "SemanticResult"),
            unresolved_questions=_parse_str_tuple(
                data, "unresolved_questions", "SemanticResult",
            ),
            followups=_parse_str_tuple(data, "followups", "SemanticResult"),
            observations=_parse_str_tuple(data, "observations", "SemanticResult"),
            extra=_parse_mapping(data, "extra", "SemanticResult"),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "action_summary": self.action_summary,
            "state_changes": list(self.state_changes),
            "unresolved_questions": list(self.unresolved_questions),
            "followups": list(self.followups),
            "observations": list(self.observations),
            "extra": _thaw_value(self.extra),
        }


_EXECUTION_POLICY_KEYS: frozenset[str] = frozenset({
    "write_scope",
    "dependency_keys",
    "priority",
    "requires_confirmation",
    "max_steps",
    "extra",
})


@dataclass(frozen=True)
class ExecutionPolicy:
    """Scheduler and execution constraints for a handoff."""

    write_scope: tuple[str, ...] = field(default_factory=tuple)
    dependency_keys: tuple[str, ...] = field(default_factory=tuple)
    priority: int = 100
    requires_confirmation: bool = False
    max_steps: int = 1
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "write_scope", _tuple_of_str(self.write_scope))
        object.__setattr__(
            self, "dependency_keys", _tuple_of_str(self.dependency_keys),
        )
        object.__setattr__(self, "priority", int(self.priority))
        object.__setattr__(
            self, "requires_confirmation", bool(self.requires_confirmation),
        )
        object.__setattr__(self, "max_steps", int(self.max_steps))
        object.__setattr__(self, "extra", _frozen_mapping(self.extra))

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> "ExecutionPolicy":
        data = _require_mapping(payload, "ExecutionPolicy")
        _reject_unknown_keys(data, _EXECUTION_POLICY_KEYS, "ExecutionPolicy")
        return cls(
            write_scope=_parse_str_tuple(data, "write_scope", "ExecutionPolicy"),
            dependency_keys=_parse_str_tuple(
                data, "dependency_keys", "ExecutionPolicy",
            ),
            priority=_parse_int(data, "priority", "ExecutionPolicy", 100),
            requires_confirmation=_parse_bool(
                data, "requires_confirmation", "ExecutionPolicy", False,
            ),
            max_steps=_parse_int(data, "max_steps", "ExecutionPolicy", 1),
            extra=_parse_mapping(data, "extra", "ExecutionPolicy"),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "write_scope": list(self.write_scope),
            "dependency_keys": list(self.dependency_keys),
            "priority": self.priority,
            "requires_confirmation": self.requires_confirmation,
            "max_steps": self.max_steps,
            "extra": _thaw_value(self.extra),
        }


_TOOL_EVENT_KEYS: frozenset[str] = frozenset({
    "name",
    "args",
    "result",
    "status",
    "ui_preview",
    "error",
})


@dataclass(frozen=True)
class ToolEvent:
    """One tool invocation/result in the execution trace."""

    name: str
    args: Mapping[str, Any] = field(default_factory=dict)
    result: str = ""
    status: str = "ok"
    ui_preview: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", str(self.name or ""))
        object.__setattr__(self, "args", _frozen_mapping(self.args))
        object.__setattr__(self, "result", str(self.result or ""))
        object.__setattr__(self, "status", str(self.status or "ok"))
        object.__setattr__(self, "ui_preview", str(self.ui_preview or ""))
        object.__setattr__(self, "error", str(self.error or ""))

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ToolEvent":
        data = _require_mapping(payload, "ToolEvent")
        _reject_unknown_keys(data, _TOOL_EVENT_KEYS, "ToolEvent")
        return cls(
            name=_parse_str(data, "name", "ToolEvent"),
            args=_parse_mapping(data, "args", "ToolEvent"),
            result=_parse_str(data, "result", "ToolEvent"),
            status=_parse_str(data, "status", "ToolEvent") or "ok",
            ui_preview=_parse_str(data, "ui_preview", "ToolEvent"),
            error=_parse_str(data, "error", "ToolEvent"),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "args": _thaw_value(self.args),
            "result": self.result,
            "status": self.status,
            "ui_preview": self.ui_preview,
            "error": self.error,
        }


_AGENT_HANDOFF_KEYS: frozenset[str] = frozenset({
    "agent_interface_version",
    "handoff_id",
    "source_agent",
    "target_agent",
    "lane",
    "action",
    "args",
    "semantic_context",
    "execution_policy",
    "warnings",
})


@dataclass(frozen=True)
class AgentHandoff:
    """Immutable handoff between agents.

    `args` are executable input to the target lane/action.
    `semantic_context` is the interoperable meaning attached to that
    input. Keep both; do not hide semantic summaries inside tool args.
    """

    lane: str
    action: str = ""
    args: Mapping[str, Any] = field(default_factory=dict)
    semantic_context: SemanticContext = field(default_factory=SemanticContext)
    execution_policy: ExecutionPolicy = field(default_factory=ExecutionPolicy)
    protocol_version: int = PROTOCOL_VERSION
    handoff_id: str = ""
    source_agent: str = "host"
    target_agent: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "lane", str(self.lane or ""))
        object.__setattr__(self, "action", str(self.action or ""))
        object.__setattr__(self, "args", _frozen_mapping(self.args))
        if not isinstance(self.semantic_context, SemanticContext):
            object.__setattr__(
                self,
                "semantic_context",
                SemanticContext.from_payload(self.semantic_context),  # type: ignore[arg-type]
            )
        if not isinstance(self.execution_policy, ExecutionPolicy):
            object.__setattr__(
                self,
                "execution_policy",
                ExecutionPolicy.from_payload(self.execution_policy),  # type: ignore[arg-type]
            )
        object.__setattr__(
            self,
            "protocol_version",
            _validate_protocol_version(self.protocol_version),
        )
        object.__setattr__(self, "handoff_id", str(self.handoff_id or ""))
        object.__setattr__(self, "source_agent", str(self.source_agent or ""))
        target = self.target_agent or self.lane
        object.__setattr__(self, "target_agent", str(target or ""))
        object.__setattr__(self, "warnings", _tuple_of_str(self.warnings))

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "AgentHandoff":
        data = _require_mapping(payload, "AgentHandoff")
        _reject_unknown_keys(data, _AGENT_HANDOFF_KEYS, "AgentHandoff")
        return cls(
            protocol_version=_validate_protocol_version(
                data.get("agent_interface_version", PROTOCOL_VERSION),
            ),
            handoff_id=_parse_str(data, "handoff_id", "AgentHandoff"),
            source_agent=_parse_str(data, "source_agent", "AgentHandoff") or "host",
            target_agent=_parse_str(data, "target_agent", "AgentHandoff"),
            lane=_parse_str(data, "lane", "AgentHandoff"),
            action=_parse_str(data, "action", "AgentHandoff"),
            args=_parse_mapping(data, "args", "AgentHandoff"),
            semantic_context=SemanticContext.from_payload(
                _parse_mapping(data, "semantic_context", "AgentHandoff"),
            ),
            execution_policy=ExecutionPolicy.from_payload(
                _parse_mapping(data, "execution_policy", "AgentHandoff"),
            ),
            warnings=_parse_str_tuple(data, "warnings", "AgentHandoff"),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "agent_interface_version": self.protocol_version,
            "handoff_id": self.handoff_id,
            "source_agent": self.source_agent,
            "target_agent": self.target_agent,
            "lane": self.lane,
            "action": self.action,
            "args": _thaw_value(self.args),
            "semantic_context": self.semantic_context.to_payload(),
            "execution_policy": self.execution_policy.to_payload(),
            "warnings": list(self.warnings),
        }


_AGENT_STEP_RESULT_KEYS: frozenset[str] = frozenset({
    "agent_interface_version",
    "status",
    "user_visible_response",
    "semantic_result",
    "tool_events",
    "question",
    "error",
    "updated_handoff",
    "telemetry",
})


@dataclass(frozen=True)
class AgentStepResult:
    """Immutable result of one target-agent step."""

    status: AgentStepStatus
    user_visible_response: str = ""
    semantic_result: SemanticResult = field(default_factory=SemanticResult)
    tool_events: tuple[ToolEvent, ...] = field(default_factory=tuple)
    question: str = ""
    error: str = ""
    updated_handoff: AgentHandoff | None = None
    telemetry: Mapping[str, Any] = field(default_factory=dict)
    protocol_version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if self.status not in AGENT_STEP_STATUSES:
            raise ValueError(f"unknown AgentStepResult status: {self.status!r}")
        object.__setattr__(
            self, "user_visible_response", str(self.user_visible_response or ""),
        )
        if not isinstance(self.semantic_result, SemanticResult):
            object.__setattr__(
                self,
                "semantic_result",
                SemanticResult.from_payload(self.semantic_result),  # type: ignore[arg-type]
            )
        object.__setattr__(
            self,
            "tool_events",
            tuple(
                ev if isinstance(ev, ToolEvent) else ToolEvent.from_payload(ev)
                for ev in (self.tool_events or ())
            ),
        )
        object.__setattr__(self, "question", str(self.question or ""))
        object.__setattr__(self, "error", str(self.error or ""))
        if self.updated_handoff is not None and not isinstance(
            self.updated_handoff, AgentHandoff,
        ):
            object.__setattr__(
                self,
                "updated_handoff",
                AgentHandoff.from_payload(self.updated_handoff),  # type: ignore[arg-type]
            )
        object.__setattr__(self, "telemetry", _frozen_mapping(self.telemetry))
        object.__setattr__(
            self,
            "protocol_version",
            _validate_protocol_version(self.protocol_version),
        )

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "AgentStepResult":
        data = _require_mapping(payload, "AgentStepResult")
        _reject_unknown_keys(data, _AGENT_STEP_RESULT_KEYS, "AgentStepResult")
        status = _parse_str(data, "status", "AgentStepResult") or "completed"
        if status not in AGENT_STEP_STATUSES:
            raise ValueError(f"unknown AgentStepResult status: {status!r}")
        updated = data.get("updated_handoff")
        return cls(
            status=status,  # type: ignore[arg-type]
            user_visible_response=_parse_str(
                data, "user_visible_response", "AgentStepResult",
            ),
            semantic_result=SemanticResult.from_payload(
                _parse_mapping(data, "semantic_result", "AgentStepResult"),
            ),
            tool_events=tuple(
                ToolEvent.from_payload(ev)
                for ev in _parse_mapping_tuple(
                    data, "tool_events", "AgentStepResult",
                )
            ),
            question=_parse_str(data, "question", "AgentStepResult"),
            error=_parse_str(data, "error", "AgentStepResult"),
            updated_handoff=(
                AgentHandoff.from_payload(updated)
                if updated is not None
                else None
            ),
            telemetry=_parse_mapping(data, "telemetry", "AgentStepResult"),
            protocol_version=_validate_protocol_version(
                data.get("agent_interface_version", PROTOCOL_VERSION),
            ),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "agent_interface_version": self.protocol_version,
            "status": self.status,
            "user_visible_response": self.user_visible_response,
            "semantic_result": self.semantic_result.to_payload(),
            "tool_events": [ev.to_payload() for ev in self.tool_events],
            "question": self.question,
            "error": self.error,
            "updated_handoff": (
                self.updated_handoff.to_payload()
                if self.updated_handoff is not None
                else None
            ),
            "telemetry": _thaw_value(self.telemetry),
        }


_ERROR_INFO_KEYS: frozenset[str] = frozenset({
    "code",
    "message",
    "retriable",
    "details",
})


@dataclass(frozen=True)
class ErrorInfo:
    """Typed error for transport/control-plane failures.

    Use at the envelope layer (an ``AgentMessage`` of kind ``"error"``)
    or anywhere a structured, machine-readable error is more useful than
    the freeform ``error: str`` field on ``AgentStepResult``.
    """

    code: str = ""
    message: str = ""
    retriable: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", str(self.code or ""))
        object.__setattr__(self, "message", str(self.message or ""))
        object.__setattr__(self, "retriable", bool(self.retriable))
        object.__setattr__(self, "details", _frozen_mapping(self.details))

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> "ErrorInfo":
        data = _require_mapping(payload, "ErrorInfo")
        _reject_unknown_keys(data, _ERROR_INFO_KEYS, "ErrorInfo")
        return cls(
            code=_parse_str(data, "code", "ErrorInfo"),
            message=_parse_str(data, "message", "ErrorInfo"),
            retriable=_parse_bool(data, "retriable", "ErrorInfo", False),
            details=_parse_mapping(data, "details", "ErrorInfo"),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retriable": self.retriable,
            "details": _thaw_value(self.details),
        }


AgentStepEventKind = Literal[
    "accepted",
    "progress",
    "tool_event",
    "partial_response",
    "question",
    "final",
]

AGENT_STEP_EVENT_KINDS: frozenset[str] = frozenset({
    "accepted",
    "progress",
    "tool_event",
    "partial_response",
    "question",
    "final",
})


_AGENT_STEP_EVENT_KEYS: frozenset[str] = frozenset({
    "handoff_id",
    "step_id",
    "seq",
    "ts",
    "kind",
    "body",
})


_STEP_EVENT_PROGRESS_KEYS: frozenset[str] = frozenset({"fraction", "message"})
_STEP_EVENT_PARTIAL_RESPONSE_KEYS: frozenset[str] = frozenset({"text", "delta"})
_STEP_EVENT_QUESTION_KEYS: frozenset[str] = frozenset({"question", "schema"})


def _validate_step_event_body(kind: str, body: Mapping[str, Any]) -> None:
    """Strict per-kind body shape validation.

    Called by both ``__post_init__`` (to keep construction honest) and
    ``from_payload`` (the trust boundary). Re-parses DTO-typed bodies via
    their own ``from_payload`` so cross-kind payloads are rejected.
    """
    where = f"AgentStepEvent.body[{kind}]"
    if kind == "accepted":
        _reject_unknown_keys(body, frozenset(), where)
    elif kind == "progress":
        _reject_unknown_keys(body, _STEP_EVENT_PROGRESS_KEYS, where)
        _parse_optional_number(body, "fraction", where)
        _parse_str(body, "message", where)
    elif kind == "tool_event":
        ToolEvent.from_payload(body)
    elif kind == "partial_response":
        _reject_unknown_keys(body, _STEP_EVENT_PARTIAL_RESPONSE_KEYS, where)
        _parse_str(body, "text", where)
        _parse_bool(body, "delta", where, False)
    elif kind == "question":
        _reject_unknown_keys(body, _STEP_EVENT_QUESTION_KEYS, where)
        _parse_str(body, "question", where)
        _parse_mapping(body, "schema", where)
    elif kind == "final":
        AgentStepResult.from_payload(body)
    else:
        raise ValueError(f"unknown AgentStepEvent kind: {kind!r}")


@dataclass(frozen=True)
class AgentStepEvent:
    """One event in the timeline of a single agent step.

    Multiple events make up a step. The final event of a step carries
    an ``AgentStepResult`` payload (``kind="final"``); transports may
    alternatively emit a separate ``AgentMessage`` of kind
    ``"step_result"`` to deliver the terminal result.

    ``seq`` is a producer-assigned monotonically increasing number per
    ``(handoff_id, step_id)`` pair. Consumers may use it for ordering,
    deduplication, and resume.
    """

    kind: AgentStepEventKind
    handoff_id: str = ""
    step_id: str = ""
    seq: int = 0
    ts: str = ""
    body: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        kind = str(self.kind or "")
        if kind not in AGENT_STEP_EVENT_KINDS:
            raise ValueError(f"unknown AgentStepEvent kind: {self.kind!r}")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "handoff_id", str(self.handoff_id or ""))
        object.__setattr__(self, "step_id", str(self.step_id or ""))
        if isinstance(self.seq, bool) or not isinstance(self.seq, int):
            raise ValueError(
                f"AgentStepEvent.seq must be an integer, "
                f"got {type(self.seq).__name__}"
            )
        if self.seq < 0:
            raise ValueError(
                f"AgentStepEvent.seq must be non-negative, got {self.seq}"
            )
        object.__setattr__(self, "ts", str(self.ts or ""))
        object.__setattr__(self, "body", _frozen_mapping(self.body))
        _validate_step_event_body(self.kind, self.body)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "AgentStepEvent":
        data = _require_mapping(payload, "AgentStepEvent")
        _reject_unknown_keys(data, _AGENT_STEP_EVENT_KEYS, "AgentStepEvent")
        kind = _parse_str(data, "kind", "AgentStepEvent")
        if kind not in AGENT_STEP_EVENT_KINDS:
            raise ValueError(f"unknown AgentStepEvent kind: {kind!r}")
        seq_value = data.get("seq", 0)
        if isinstance(seq_value, bool) or not isinstance(seq_value, int):
            raise ValueError(
                f"AgentStepEvent field 'seq' must be an integer, "
                f"got {type(seq_value).__name__}"
            )
        if seq_value < 0:
            raise ValueError(
                f"AgentStepEvent field 'seq' must be non-negative, got {seq_value}"
            )
        body = _parse_mapping(data, "body", "AgentStepEvent")
        return cls(
            kind=kind,  # type: ignore[arg-type]
            handoff_id=_parse_str(data, "handoff_id", "AgentStepEvent"),
            step_id=_parse_str(data, "step_id", "AgentStepEvent"),
            seq=seq_value,
            ts=_parse_str(data, "ts", "AgentStepEvent"),
            body=body,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "handoff_id": self.handoff_id,
            "step_id": self.step_id,
            "seq": self.seq,
            "ts": self.ts,
            "body": _thaw_value(self.body),
        }


AgentMessageKind = Literal[
    "handoff",
    "step_event",
    "step_result",
    "cancel",
    "ack",
    "error",
]

AGENT_MESSAGE_KINDS: frozenset[str] = frozenset({
    "handoff",
    "step_event",
    "step_result",
    "cancel",
    "ack",
    "error",
})


_AGENT_MESSAGE_KEYS: frozenset[str] = frozenset({
    "agent_interface_version",
    "message_id",
    "correlation_id",
    "in_reply_to",
    "sender",
    "recipient",
    "sent_at",
    "trace_id",
    "kind",
    "payload",
})


_MESSAGE_CANCEL_KEYS: frozenset[str] = frozenset({"handoff_id", "reason"})
_MESSAGE_ACK_KEYS: frozenset[str] = frozenset({"accepted", "reason"})


def _validate_message_payload(kind: str, payload: Mapping[str, Any]) -> None:
    """Strict per-kind envelope payload validation.

    Re-parses DTO-typed payloads via their ``from_payload`` so that a
    cross-kind payload (e.g. a step-event-shaped body sent as
    ``kind="handoff"``) is rejected at the boundary.
    """
    where = f"AgentMessage.payload[{kind}]"
    if kind == "handoff":
        AgentHandoff.from_payload(payload)
    elif kind == "step_event":
        AgentStepEvent.from_payload(payload)
    elif kind == "step_result":
        AgentStepResult.from_payload(payload)
    elif kind == "cancel":
        _reject_unknown_keys(payload, _MESSAGE_CANCEL_KEYS, where)
        _parse_str(payload, "handoff_id", where)
        _parse_str(payload, "reason", where)
    elif kind == "ack":
        _reject_unknown_keys(payload, _MESSAGE_ACK_KEYS, where)
        _parse_bool(payload, "accepted", where, False)
        _parse_str(payload, "reason", where)
    elif kind == "error":
        ErrorInfo.from_payload(payload)
    else:
        raise ValueError(f"unknown AgentMessage kind: {kind!r}")


@dataclass(frozen=True)
class AgentMessage:
    """Transport envelope carrying one AIP payload between agents.

    The envelope owns addressing (``sender``/``recipient``), correlation
    (``message_id``/``correlation_id``/``in_reply_to``), and timing
    (``sent_at``/``trace_id``). These are transport-layer identities and
    are deliberately separate from the semantic ``source_agent`` and
    ``target_agent`` carried inside an ``AgentHandoff``.

    The ``kind`` discriminator selects which AIP type ``payload`` carries:

    * ``"handoff"`` → ``AgentHandoff``
    * ``"step_event"`` → ``AgentStepEvent``
    * ``"step_result"`` → ``AgentStepResult`` (terminal; equivalent to a
      ``step_event`` of kind ``"final"`` for transports that prefer a
      distinct terminal message)
    * ``"cancel"`` → ``{"handoff_id": str, "reason": str}``
    * ``"ack"`` → ``{"accepted": bool, "reason": str}``
    * ``"error"`` → ``ErrorInfo``

    AIP does not implement a transport. Queues, websockets, gRPC streams,
    and in-process buses each decide how to ship ``AgentMessage``
    payloads. ``sent_at`` is kept as an opaque RFC3339 string; AIP does
    not parse timestamps.
    """

    kind: AgentMessageKind
    message_id: str = ""
    correlation_id: str = ""
    in_reply_to: str = ""
    sender: str = ""
    recipient: str = ""
    sent_at: str = ""
    trace_id: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    protocol_version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        kind = str(self.kind or "")
        if kind not in AGENT_MESSAGE_KINDS:
            raise ValueError(f"unknown AgentMessage kind: {self.kind!r}")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "message_id", str(self.message_id or ""))
        object.__setattr__(
            self, "correlation_id", str(self.correlation_id or ""),
        )
        object.__setattr__(self, "in_reply_to", str(self.in_reply_to or ""))
        object.__setattr__(self, "sender", str(self.sender or ""))
        object.__setattr__(self, "recipient", str(self.recipient or ""))
        object.__setattr__(self, "sent_at", str(self.sent_at or ""))
        object.__setattr__(self, "trace_id", str(self.trace_id or ""))
        object.__setattr__(self, "payload", _frozen_mapping(self.payload))
        object.__setattr__(
            self,
            "protocol_version",
            _validate_protocol_version(self.protocol_version),
        )
        _validate_message_payload(self.kind, self.payload)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "AgentMessage":
        data = _require_mapping(payload, "AgentMessage")
        _reject_unknown_keys(data, _AGENT_MESSAGE_KEYS, "AgentMessage")
        kind = _parse_str(data, "kind", "AgentMessage")
        if kind not in AGENT_MESSAGE_KINDS:
            raise ValueError(f"unknown AgentMessage kind: {kind!r}")
        body = _parse_mapping(data, "payload", "AgentMessage")
        return cls(
            kind=kind,  # type: ignore[arg-type]
            message_id=_parse_str(data, "message_id", "AgentMessage"),
            correlation_id=_parse_str(data, "correlation_id", "AgentMessage"),
            in_reply_to=_parse_str(data, "in_reply_to", "AgentMessage"),
            sender=_parse_str(data, "sender", "AgentMessage"),
            recipient=_parse_str(data, "recipient", "AgentMessage"),
            sent_at=_parse_str(data, "sent_at", "AgentMessage"),
            trace_id=_parse_str(data, "trace_id", "AgentMessage"),
            payload=body,
            protocol_version=_validate_protocol_version(
                data.get("agent_interface_version", PROTOCOL_VERSION),
            ),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "agent_interface_version": self.protocol_version,
            "kind": self.kind,
            "message_id": self.message_id,
            "correlation_id": self.correlation_id,
            "in_reply_to": self.in_reply_to,
            "sender": self.sender,
            "recipient": self.recipient,
            "sent_at": self.sent_at,
            "trace_id": self.trace_id,
            "payload": _thaw_value(self.payload),
        }


class AgentExecutor:
    """Structural interface for target-agent implementations."""

    def describe(self) -> Mapping[str, Any]:
        raise NotImplementedError

    def validate_handoff(self, handoff: AgentHandoff) -> None:
        raise NotImplementedError

    def step(self, request: Mapping[str, Any]) -> AgentStepResult:
        raise NotImplementedError


class StreamingAgentExecutor:
    """Structural interface for streaming target-agent implementations.

    Where ``AgentExecutor.step`` is a single sync call returning a
    monolithic ``AgentStepResult``, ``StreamingAgentExecutor.stream``
    yields a sequence of ``AgentStepEvent`` values describing one step
    as it runs: acceptance, progress, intermediate tool events, partial
    responses, questions, and a terminal ``final`` event carrying the
    ``AgentStepResult``.

    AIP does not own the transport. A sync adapter is trivial: drain
    ``stream(handoff)`` and return the ``final`` event's body.
    """

    def describe(self) -> Mapping[str, Any]:
        raise NotImplementedError

    def validate_handoff(self, handoff: AgentHandoff) -> None:
        raise NotImplementedError

    def stream(self, handoff: AgentHandoff) -> Iterator[AgentStepEvent]:
        raise NotImplementedError

    def cancel(self, handoff_id: str, reason: str) -> None:
        raise NotImplementedError
