"""Immutable Agent Interface Protocol DTOs.

The protocol separates semantic state from execution state:

* semantic context/result describe what the agent believes happened
  and what should happen next;
* tool events describe what was invoked and what came back.

Tool calls are an execution trace, not the source of semantic meaning.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, Mapping


PROTOCOL_VERSION = 1

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
    try:
        version = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"unparseable agent_interface_version {value!r}")
    if version != PROTOCOL_VERSION:
        raise ValueError(
            f"unsupported agent_interface_version {version} "
            f"(expected {PROTOCOL_VERSION})"
        )
    return version


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
        data = dict(payload or {})
        return cls(
            user_goal=str(data.get("user_goal") or ""),
            source_summary=str(data.get("source_summary") or ""),
            assumptions=tuple(data.get("assumptions") or ()),
            decisions=tuple(data.get("decisions") or ()),
            constraints=tuple(data.get("constraints") or ()),
            expected_outcome=str(data.get("expected_outcome") or ""),
            observations=tuple(data.get("observations") or ()),
            extra=data.get("extra") if isinstance(data.get("extra"), Mapping) else {},
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
        data = dict(payload or {})
        return cls(
            action_summary=str(data.get("action_summary") or ""),
            state_changes=tuple(data.get("state_changes") or ()),
            unresolved_questions=tuple(data.get("unresolved_questions") or ()),
            followups=tuple(data.get("followups") or ()),
            observations=tuple(data.get("observations") or ()),
            extra=data.get("extra") if isinstance(data.get("extra"), Mapping) else {},
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
        data = dict(payload or {})
        return cls(
            write_scope=tuple(data.get("write_scope") or ()),
            dependency_keys=tuple(data.get("dependency_keys") or ()),
            priority=int(data.get("priority", 100) or 100),
            requires_confirmation=bool(data.get("requires_confirmation") or False),
            max_steps=int(data.get("max_steps", 1) or 1),
            extra=data.get("extra") if isinstance(data.get("extra"), Mapping) else {},
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
        return cls(
            name=str(payload.get("name") or ""),
            args=payload.get("args") if isinstance(payload.get("args"), Mapping) else {},
            result=str(payload.get("result") or ""),
            status=str(payload.get("status") or "ok"),
            ui_preview=str(payload.get("ui_preview") or ""),
            error=str(payload.get("error") or ""),
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
        return cls(
            protocol_version=_validate_protocol_version(
                payload.get("agent_interface_version", PROTOCOL_VERSION),
            ),
            handoff_id=str(payload.get("handoff_id") or ""),
            source_agent=str(payload.get("source_agent") or "host"),
            target_agent=str(payload.get("target_agent") or ""),
            lane=str(payload.get("lane") or ""),
            action=str(payload.get("action") or ""),
            args=payload.get("args")
            if isinstance(payload.get("args"), Mapping)
            else {},
            semantic_context=SemanticContext.from_payload(
                payload.get("semantic_context")
                if isinstance(payload.get("semantic_context"), Mapping)
                else {},
            ),
            execution_policy=ExecutionPolicy.from_payload(
                payload.get("execution_policy")
                if isinstance(payload.get("execution_policy"), Mapping)
                else {},
            ),
            warnings=tuple(payload.get("warnings") or ()),
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
        updated = payload.get("updated_handoff")
        status = str(payload.get("status") or "completed")
        if status not in AGENT_STEP_STATUSES:
            raise ValueError(f"unknown AgentStepResult status: {status!r}")
        return cls(
            status=status,  # type: ignore[arg-type]
            user_visible_response=str(payload.get("user_visible_response") or ""),
            semantic_result=SemanticResult.from_payload(
                payload.get("semantic_result")
                if isinstance(payload.get("semantic_result"), Mapping)
                else {},
            ),
            tool_events=tuple(
                ToolEvent.from_payload(ev)
                for ev in payload.get("tool_events", ())
                if isinstance(ev, Mapping)
            ),
            question=str(payload.get("question") or ""),
            error=str(payload.get("error") or ""),
            updated_handoff=AgentHandoff.from_payload(updated)
            if isinstance(updated, Mapping)
            else None,
            telemetry=payload.get("telemetry")
            if isinstance(payload.get("telemetry"), Mapping)
            else {},
            protocol_version=_validate_protocol_version(
                payload.get("agent_interface_version", PROTOCOL_VERSION),
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
