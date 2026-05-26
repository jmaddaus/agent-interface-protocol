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
from typing import Any, Literal, Mapping


# Version this build emits when serializing freshly-constructed objects.
PROTOCOL_VERSION = 1

# Inclusive range of protocol versions this build can parse. Widen this
# (not just PROTOCOL_VERSION) when adding a new version so that services
# deploying on a rolling basis can accept both the old and the new payload
# during the rollout window.
MIN_SUPPORTED_PROTOCOL_VERSION = 1
MAX_SUPPORTED_PROTOCOL_VERSION = 1
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


class AgentExecutor:
    """Structural interface for target-agent implementations."""

    def describe(self) -> Mapping[str, Any]:
        raise NotImplementedError

    def validate_handoff(self, handoff: AgentHandoff) -> None:
        raise NotImplementedError

    def step(self, request: Mapping[str, Any]) -> AgentStepResult:
        raise NotImplementedError
