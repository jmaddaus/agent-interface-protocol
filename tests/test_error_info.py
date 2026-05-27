from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from agent_interface_protocol.agent_interface import ErrorInfo


def test_error_info_round_trip():
    err = ErrorInfo(
        code="executor_failure",
        message="agent crashed",
        retriable=True,
        details={"trace_id": "t1", "step_id": "s1"},
    )

    payload = err.to_payload()
    assert payload == {
        "code": "executor_failure",
        "message": "agent crashed",
        "retriable": True,
        "details": {"trace_id": "t1", "step_id": "s1"},
    }
    assert ErrorInfo.from_payload(payload) == err


def test_error_info_defaults():
    err = ErrorInfo()
    assert err.code == ""
    assert err.message == ""
    assert err.retriable is False
    assert dict(err.details) == {}
    assert ErrorInfo.from_payload({}) == err


def test_error_info_is_immutable():
    err = ErrorInfo(code="x", details={"a": 1})
    with pytest.raises(FrozenInstanceError):
        err.code = "y"  # type: ignore[misc]
    with pytest.raises(TypeError):
        err.details["a"] = 2  # type: ignore[index]


def test_error_info_rejects_unknown_field():
    with pytest.raises(ValueError, match="unknown ErrorInfo field"):
        ErrorInfo.from_payload({"code": "x", "stack": "..."})


def test_error_info_rejects_wrong_typed_fields():
    with pytest.raises(ValueError, match="must be a string"):
        ErrorInfo.from_payload({"code": 123})
    with pytest.raises(ValueError, match="must be a boolean"):
        ErrorInfo.from_payload({"retriable": "yes"})
    with pytest.raises(ValueError, match="must be a mapping"):
        ErrorInfo.from_payload({"details": [1, 2]})
