from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from agent_interface_protocol.agent_interface import (
    AgentHandoff,
    AgentStepResult,
    ExecutionPolicy,
    PROTOCOL_VERSION,
    SemanticContext,
    SemanticResult,
    ToolEvent,
)


def test_semantic_context_is_immutable_and_serializable():
    context = SemanticContext(
        user_goal="add users",
        source_summary="add Kim and Eli",
        decisions=["route to admin"],
        constraints=["PII stays in governed form"],
        extra={"nested": {"count": 2}},
    )

    with pytest.raises(FrozenInstanceError):
        context.user_goal = "mutated"  # type: ignore[misc]
    with pytest.raises(TypeError):
        context.extra["nested"] = {}  # type: ignore[index]

    rebuilt = SemanticContext.from_payload(context.to_payload())
    assert rebuilt == context
    assert rebuilt.decisions == ("route to admin",)
    assert rebuilt.constraints == ("PII stays in governed form",)


def test_handoff_keeps_semantics_separate_from_tool_args():
    handoff = AgentHandoff(
        source_agent="host",
        target_agent="admin",
        lane="admin",
        action="bulk_add_users",
        args={"user_refs": [{"display_name": "Kim"}]},
        semantic_context=SemanticContext(
            user_goal="add two technicians",
            source_summary="Kim and Eli should be added as techs",
            expected_outcome="Open the governed bulk-add form.",
        ),
        execution_policy=ExecutionPolicy(
            write_scope=["admin:users"],
            dependency_keys=["group:technicians"],
        ),
    )

    payload = handoff.to_payload()
    assert payload["args"] == {"user_refs": [{"display_name": "Kim"}]}
    assert payload["semantic_context"]["user_goal"] == "add two technicians"
    assert "user_goal" not in payload["args"]
    assert payload["execution_policy"]["write_scope"] == ["admin:users"]
    assert AgentHandoff.from_payload(payload) == handoff


def test_handoff_payload_accepts_only_protocol_args_key():
    handoff = AgentHandoff.from_payload({
        "lane": "admin",
        "action": "bulk_add_users",
        "dispatch_args": {"user_refs": [{"display_name": "Kim"}]},
    })

    assert handoff.args == {}


def test_handoff_rejects_unsupported_protocol_version():
    with pytest.raises(ValueError, match="unsupported agent_interface_version"):
        AgentHandoff.from_payload({
            "agent_interface_version": PROTOCOL_VERSION + 1,
            "lane": "admin",
        })


def test_step_result_does_not_require_parsing_tool_events_for_meaning():
    result = AgentStepResult(
        status="completed",
        user_visible_response="Opened the Bulk Add Users form for Kim.",
        semantic_result=SemanticResult(
            action_summary="Opened the governed user-add form.",
            followups=["Wait for form submission before creating users."],
        ),
        tool_events=[
            ToolEvent(
                name="start_workflow",
                args={"process_id": "bulk_add_users"},
                result='{"status": "pending"}',
            ),
        ],
    )

    payload = result.to_payload()
    assert payload["agent_interface_version"] == PROTOCOL_VERSION
    assert payload["semantic_result"]["action_summary"] == (
        "Opened the governed user-add form."
    )
    assert payload["tool_events"][0]["name"] == "start_workflow"
    assert "action_summary" not in payload["tool_events"][0]
    assert AgentStepResult.from_payload(payload) == result


def test_step_result_rejects_unknown_status():
    with pytest.raises(ValueError, match="unknown AgentStepResult status"):
        AgentStepResult.from_payload({"status": "complete-ish"})
    with pytest.raises(ValueError, match="unknown AgentStepResult status"):
        AgentStepResult(status="complete-ish")  # type: ignore[arg-type]


def test_step_result_rejects_unsupported_protocol_version():
    with pytest.raises(ValueError, match="unsupported agent_interface_version"):
        AgentStepResult.from_payload({
            "agent_interface_version": PROTOCOL_VERSION + 1,
            "status": "completed",
        })


def test_step_result_is_not_mapping_compatible():
    result = AgentStepResult(status="completed", user_visible_response="Done.")

    assert not hasattr(result, "get")
    with pytest.raises(TypeError):
        result["answer"]  # type: ignore[index]
