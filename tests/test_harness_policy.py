from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from agent_interface_protocol import HarnessPolicy


def test_round_trip_with_all_fields():
    policy = HarnessPolicy(
        contract_id="pd_authoring_v1",
        allowed_tools=("create_pd", "update_pd"),
        required_outputs=("pd_id", "summary"),
        max_tool_calls=12,
        max_steps=4,
        requires_self_evaluation=True,
        budget={"tokens": 50000, "wall_seconds": 60},
        extra={"owner": "platform"},
    )
    payload = policy.to_payload()
    assert payload == {
        "contract_id": "pd_authoring_v1",
        "allowed_tools": ["create_pd", "update_pd"],
        "required_outputs": ["pd_id", "summary"],
        "max_tool_calls": 12,
        "max_steps": 4,
        "requires_self_evaluation": True,
        "budget": {"tokens": 50000, "wall_seconds": 60},
        "extra": {"owner": "platform"},
    }
    assert HarnessPolicy.from_payload(payload) == policy


def test_defaults_are_clean():
    policy = HarnessPolicy()
    assert policy.contract_id == ""
    assert policy.allowed_tools == ()
    assert policy.required_outputs == ()
    assert policy.max_tool_calls is None
    assert policy.max_steps is None
    assert policy.requires_self_evaluation is False
    assert dict(policy.budget) == {}
    assert dict(policy.extra) == {}
    assert HarnessPolicy.from_payload({}) == policy


def test_lists_normalize_to_tuples_during_construction():
    """Construction is lenient — list inputs get frozen to tuples."""
    policy = HarnessPolicy(
        allowed_tools=["create_pd", "update_pd"],
        required_outputs=["pd_id"],
    )
    assert policy.allowed_tools == ("create_pd", "update_pd")
    assert policy.required_outputs == ("pd_id",)


def test_is_immutable():
    policy = HarnessPolicy(contract_id="c1", budget={"tokens": 1})
    with pytest.raises(FrozenInstanceError):
        policy.contract_id = "c2"  # type: ignore[misc]
    with pytest.raises(TypeError):
        policy.budget["tokens"] = 2  # type: ignore[index]


def test_rejects_unknown_field():
    with pytest.raises(ValueError, match="unknown HarnessPolicy field"):
        HarnessPolicy.from_payload({"contract_id": "x", "soft_limit": 5})


def test_rejects_wrong_typed_fields():
    with pytest.raises(ValueError, match="must be a string"):
        HarnessPolicy.from_payload({"contract_id": 1})
    with pytest.raises(ValueError, match="must be a list of strings"):
        HarnessPolicy.from_payload({"allowed_tools": "create_pd"})
    with pytest.raises(ValueError, match="must be a string"):
        HarnessPolicy.from_payload({"allowed_tools": [1, 2]})
    with pytest.raises(ValueError, match="must be a boolean"):
        HarnessPolicy.from_payload({"requires_self_evaluation": "yes"})
    with pytest.raises(ValueError, match="must be a mapping"):
        HarnessPolicy.from_payload({"budget": [1, 2]})


def test_numeric_limits_must_be_non_negative_int_or_null():
    with pytest.raises(ValueError, match="must be an integer or null"):
        HarnessPolicy.from_payload({"max_tool_calls": "many"})
    with pytest.raises(ValueError, match="must be an integer or null"):
        HarnessPolicy.from_payload({"max_tool_calls": True})
    with pytest.raises(ValueError, match="must be >= 0"):
        HarnessPolicy.from_payload({"max_tool_calls": -1})
    with pytest.raises(ValueError, match="must be >= 0"):
        HarnessPolicy.from_payload({"max_steps": -3})


def test_numeric_limits_rejected_at_construction():
    with pytest.raises(ValueError, match="must be >= 0"):
        HarnessPolicy(max_tool_calls=-1)
    with pytest.raises(ValueError, match="must be >= 0"):
        HarnessPolicy(max_steps=-1)
    with pytest.raises(ValueError, match="must be an integer or None"):
        HarnessPolicy(max_tool_calls="lots")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be an integer or None"):
        HarnessPolicy(max_tool_calls=True)  # type: ignore[arg-type]


def test_null_limits_round_trip():
    policy = HarnessPolicy(max_tool_calls=None, max_steps=None)
    payload = policy.to_payload()
    assert payload["max_tool_calls"] is None
    assert payload["max_steps"] is None
    assert HarnessPolicy.from_payload(payload) == policy
