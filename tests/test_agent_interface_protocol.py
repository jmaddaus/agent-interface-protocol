from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from agent_interface_protocol.agent_interface import (
    AgentHandoff,
    AgentStepResult,
    PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    ToolEvent,
)


def test_handoff_carries_semantic_fields_at_top_level():
    """v4: semantic-context fields live directly on AgentHandoff."""
    handoff = AgentHandoff(
        lane="admin",
        user_goal="add users",
        source_summary="add Kim and Eli",
        decisions=["route to admin"],
        constraints=["PII stays in governed form"],
        context_extra={"nested": {"count": 2}},
    )

    with pytest.raises(FrozenInstanceError):
        handoff.user_goal = "mutated"  # type: ignore[misc]
    with pytest.raises(TypeError):
        handoff.context_extra["nested"] = {}  # type: ignore[index]

    rebuilt = AgentHandoff.from_payload(handoff.to_payload())
    assert rebuilt == handoff
    assert rebuilt.decisions == ("route to admin",)
    assert rebuilt.constraints == ("PII stays in governed form",)


def test_handoff_keeps_semantics_separate_from_tool_args():
    handoff = AgentHandoff(
        source_agent="host",
        target_agent="admin",
        lane="admin",
        action="bulk_add_users",
        args={"user_refs": [{"display_name": "Kim"}]},
        user_goal="add two technicians",
        source_summary="Kim and Eli should be added as techs",
        expected_outcome="Open the governed bulk-add form.",
        write_scope=["admin:users"],
        dependency_keys=["group:technicians"],
    )

    payload = handoff.to_payload()
    assert payload["args"] == {"user_refs": [{"display_name": "Kim"}]}
    assert payload["user_goal"] == "add two technicians"
    assert "user_goal" not in payload["args"]
    assert payload["write_scope"] == ["admin:users"]
    assert AgentHandoff.from_payload(payload) == handoff


def test_handoff_rejects_unknown_payload_fields():
    with pytest.raises(ValueError, match="unknown AgentHandoff field"):
        AgentHandoff.from_payload({
            "lane": "admin",
            "action": "bulk_add_users",
            "dispatch_args": {"user_refs": [{"display_name": "Kim"}]},
        })


def test_handoff_rejects_v3_nested_shape():
    """v4 is a hard break — v3-shape sub-objects must be rejected."""
    with pytest.raises(ValueError, match="unknown AgentHandoff field"):
        AgentHandoff.from_payload({
            "lane": "admin",
            "semantic_context": {"user_goal": "x"},
        })
    with pytest.raises(ValueError, match="unknown AgentHandoff field"):
        AgentHandoff.from_payload({
            "lane": "admin",
            "execution_policy": {"priority": 1},
        })


def test_from_payload_rejects_wrong_typed_fields():
    with pytest.raises(ValueError, match="must be a string"):
        AgentHandoff.from_payload({"lane": "admin", "user_goal": 123})
    with pytest.raises(ValueError, match="must be a mapping"):
        AgentHandoff.from_payload({"lane": "admin", "args": "not-a-mapping"})
    with pytest.raises(ValueError, match="must be a list of strings"):
        AgentHandoff.from_payload({"lane": "admin", "assumptions": "not-a-list"})
    with pytest.raises(ValueError, match="must be a string"):
        AgentHandoff.from_payload({"lane": "admin", "write_scope": [1, 2]})
    with pytest.raises(ValueError, match="must be an integer"):
        AgentHandoff.from_payload({"lane": "admin", "priority": "high"})
    with pytest.raises(ValueError, match="must be a boolean"):
        AgentHandoff.from_payload(
            {"lane": "admin", "requires_confirmation": "yes"},
        )


def test_handoff_rejects_unsupported_protocol_version():
    with pytest.raises(ValueError, match="unsupported agent_interface_version"):
        AgentHandoff.from_payload({
            "agent_interface_version": max(SUPPORTED_PROTOCOL_VERSIONS) + 1,
            "lane": "admin",
        })


def test_supported_protocol_versions_are_preserved_on_round_trip():
    for version in SUPPORTED_PROTOCOL_VERSIONS:
        handoff = AgentHandoff.from_payload({
            "agent_interface_version": version,
            "lane": "admin",
        })
        assert handoff.protocol_version == version
        assert handoff.to_payload()["agent_interface_version"] == version


def test_step_result_carries_semantic_fields_at_top_level():
    """v4: semantic-result fields live directly on AgentStepResult."""
    result = AgentStepResult(
        status="completed",
        user_visible_response="Opened the Bulk Add Users form for Kim.",
        action_summary="Opened the governed user-add form.",
        followups=["Wait for form submission before creating users."],
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
    assert payload["action_summary"] == "Opened the governed user-add form."
    assert payload["tool_events"][0]["name"] == "start_workflow"
    assert "action_summary" not in payload["tool_events"][0]
    assert AgentStepResult.from_payload(payload) == result


def test_step_result_rejects_v3_nested_shape():
    """v4 is a hard break — v3-shape semantic_result and updated_handoff
    must be rejected."""
    with pytest.raises(ValueError, match="unknown AgentStepResult field"):
        AgentStepResult.from_payload({
            "status": "completed",
            "semantic_result": {"action_summary": "x"},
        })
    with pytest.raises(ValueError, match="unknown AgentStepResult field"):
        AgentStepResult.from_payload({
            "status": "completed",
            "updated_handoff": None,
        })


def test_step_result_next_handoff_id_is_a_reference():
    """v4: re-delegation is by reference, not by embedded DTO."""
    result = AgentStepResult(
        status="completed",
        next_handoff_id="h2",
    )
    assert result.next_handoff_id == "h2"
    payload = result.to_payload()
    assert payload["next_handoff_id"] == "h2"
    assert AgentStepResult.from_payload(payload) == result


def test_step_result_rejects_unknown_status():
    with pytest.raises(ValueError, match="unknown AgentStepResult status"):
        AgentStepResult.from_payload({"status": "complete-ish"})
    with pytest.raises(ValueError, match="unknown AgentStepResult status"):
        AgentStepResult(status="complete-ish")  # type: ignore[arg-type]


def test_step_result_requires_status_at_parse_boundary():
    """from_payload must not silently default missing/empty status — the
    Python constructor requires it, and the boundary should match."""
    with pytest.raises(ValueError, match="'status' is required"):
        AgentStepResult.from_payload({})
    with pytest.raises(ValueError, match="'status' is required"):
        AgentStepResult.from_payload({"status": ""})
    with pytest.raises(ValueError, match="'status' is required"):
        AgentStepResult.from_payload({"status": None})


def test_step_result_rejects_unsupported_protocol_version():
    with pytest.raises(ValueError, match="unsupported agent_interface_version"):
        AgentStepResult.from_payload({
            "agent_interface_version": max(SUPPORTED_PROTOCOL_VERSIONS) + 1,
            "status": "completed",
        })


def test_step_result_is_not_mapping_compatible():
    result = AgentStepResult(status="completed", user_visible_response="Done.")

    assert not hasattr(result, "get")
    with pytest.raises(TypeError):
        result["answer"]  # type: ignore[index]


def test_agent_executor_interface_unchanged():
    """The existing sync executor surface is preserved by the v4 changes."""
    from agent_interface_protocol.agent_interface import AgentExecutor

    assert {"describe", "validate_handoff", "step"}.issubset(set(dir(AgentExecutor)))


def test_streaming_agent_executor_interface_pinned():
    """The streaming executor surface should not drift."""
    from agent_interface_protocol.agent_interface import StreamingAgentExecutor

    expected = {"describe", "validate_handoff", "stream", "cancel"}
    assert expected.issubset(set(dir(StreamingAgentExecutor)))
