from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_interface_protocol import (
    AgentHandoff,
    AgentMessage,
    AgentStepEvent,
    AgentStepResult,
    ErrorInfo,
    ExecutionPolicy,
    HarnessPolicy,
    OrchestrationContext,
    SemanticContext,
    SemanticResult,
    ToolEvent,
)
from agent_interface_protocol.schema import (
    SCHEMA_DIALECT,
    agent_handoff_schema,
    agent_message_schema,
    agent_step_event_schema,
    agent_step_result_schema,
    json_schemas,
)

jsonschema = pytest.importorskip("jsonschema")
Draft202012Validator = jsonschema.validators.Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "agent_interface_protocol" / "schemas"


# ---------------------------------------------------------------------------
# Meta-schema validation: every schema is itself a valid JSON Schema
# ---------------------------------------------------------------------------


def test_all_schemas_validate_against_meta_schema():
    for name, schema in json_schemas().items():
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == SCHEMA_DIALECT, name


# ---------------------------------------------------------------------------
# Real payloads validate against their schemas
# ---------------------------------------------------------------------------


def _validate(schema: dict, payload: dict) -> None:
    Draft202012Validator(schema).validate(payload)


def test_agent_handoff_payload_validates():
    handoff = AgentHandoff(
        source_agent="host",
        target_agent="billing_agent",
        lane="billing",
        action="create_invoice",
        args={"customer_id": "cust_123", "amount": 1250},
        semantic_context=SemanticContext(
            user_goal="invoice approved work",
            assumptions=("budget exists",),
        ),
        execution_policy=ExecutionPolicy(
            write_scope=("billing:invoices",),
            requires_confirmation=False,
        ),
    )
    _validate(agent_handoff_schema(), handoff.to_payload())


def test_agent_step_result_payload_validates():
    result = AgentStepResult(
        status="completed",
        user_visible_response="Done.",
        semantic_result=SemanticResult(
            action_summary="Created draft invoice inv_456.",
            state_changes=("invoice:inv_456:draft",),
        ),
        tool_events=(
            ToolEvent(
                name="create_invoice",
                args={"customer_id": "cust_123", "amount": 1250},
                result='{"invoice_id": "inv_456"}',
                status="ok",
            ),
        ),
    )
    _validate(agent_step_result_schema(), result.to_payload())


@pytest.mark.parametrize(
    "kind,body",
    [
        ("accepted", {}),
        ("progress", {"fraction": 0.5, "message": "halfway"}),
        ("progress", {"fraction": None, "message": ""}),
        (
            "tool_event",
            ToolEvent(name="lookup", args={"q": "x"}, result="ok").to_payload(),
        ),
        ("partial_response", {"text": "hello", "delta": True}),
        (
            "question",
            {
                "question": "Which env?",
                "schema": {"type": "string", "enum": ["dev", "prod"]},
            },
        ),
        (
            "final",
            AgentStepResult(
                status="completed",
                semantic_result=SemanticResult(action_summary="x"),
            ).to_payload(),
        ),
        ("phase_started", {"phase": "planner", "message": "planning"}),
        (
            "phase_completed",
            {"phase": "planner", "summary": "ok", "metrics": {"tokens": 100}},
        ),
        ("checkpoint", {"checkpoint_id": "ck1", "state": {"cursor": 42}}),
        (
            "evaluation",
            {
                "passed": True,
                "score": 0.92,
                "findings": ["matches schema"],
                "details": {"rubric": "v3"},
            },
        ),
    ],
)
def test_agent_step_event_each_kind_validates(kind: str, body: dict):
    event = AgentStepEvent(
        kind=kind, handoff_id="h", step_id="s", seq=1, body=body,
    )
    _validate(agent_step_event_schema(), event.to_payload())


def test_step_event_with_orchestration_and_harness_validates():
    event = AgentStepEvent(
        kind="phase_started",
        handoff_id="h", step_id="s", seq=1,
        body={"phase": "planner", "message": ""},
        orchestration=OrchestrationContext(
            run_id="r1", phase="planner", capability="pd_authoring",
        ),
        harness_policy=HarnessPolicy(
            contract_id="pd_authoring_v1",
            allowed_tools=("create_pd",),
            max_tool_calls=12,
            requires_self_evaluation=True,
        ),
    )
    _validate(agent_step_event_schema(), event.to_payload())


@pytest.mark.parametrize(
    "kind,payload",
    [
        ("handoff", AgentHandoff(lane="x").to_payload()),
        (
            "step_event",
            AgentStepEvent(kind="accepted", seq=0).to_payload(),
        ),
        (
            "step_result",
            AgentStepResult(status="completed").to_payload(),
        ),
        ("cancel", {"handoff_id": "h", "reason": "user aborted"}),
        ("ack", {"accepted": True, "reason": ""}),
        ("error", ErrorInfo(code="timeout", message="x").to_payload()),
    ],
)
def test_agent_message_each_kind_validates(kind: str, payload: dict):
    msg = AgentMessage(
        kind=kind,
        message_id="m1",
        correlation_id="h1",
        sender="a@svc",
        recipient="b@svc",
        payload=payload,
    )
    _validate(agent_message_schema(), msg.to_payload())


# ---------------------------------------------------------------------------
# Malformed payloads must fail validation
# ---------------------------------------------------------------------------


def test_unknown_top_level_field_fails_validation():
    schema = agent_handoff_schema()
    payload = AgentHandoff(lane="x").to_payload()
    payload["dispatch_args"] = {}
    with pytest.raises(jsonschema.ValidationError):
        Draft202012Validator(schema).validate(payload)


def test_unknown_status_fails_validation():
    schema = agent_step_result_schema()
    payload = AgentStepResult(status="completed").to_payload()
    payload["status"] = "complete-ish"
    with pytest.raises(jsonschema.ValidationError):
        Draft202012Validator(schema).validate(payload)


def test_negative_seq_fails_validation():
    schema = agent_step_event_schema()
    payload = AgentStepEvent(kind="accepted", seq=0).to_payload()
    payload["seq"] = -1
    with pytest.raises(jsonschema.ValidationError):
        Draft202012Validator(schema).validate(payload)


def test_unknown_event_kind_fails_validation():
    schema = agent_step_event_schema()
    payload = AgentStepEvent(kind="accepted", seq=0).to_payload()
    payload["kind"] = "not_a_real_kind"
    with pytest.raises(jsonschema.ValidationError):
        Draft202012Validator(schema).validate(payload)


def test_cross_kind_body_fails_validation():
    """A `final` event with a handoff-shaped body should fail because
    `lane` is not a valid AgentStepResult field."""
    schema = agent_step_event_schema()
    payload = {
        "kind": "final",
        "handoff_id": "h",
        "step_id": "s",
        "seq": 0,
        "ts": "",
        "body": {"lane": "billing"},
        "orchestration": None,
        "harness_policy": None,
    }
    with pytest.raises(jsonschema.ValidationError):
        Draft202012Validator(schema).validate(payload)


def test_harness_policy_negative_limit_fails_validation():
    schema = agent_message_schema()
    msg = AgentMessage(
        kind="ack",
        payload={"accepted": True, "reason": ""},
        harness_policy=HarnessPolicy(contract_id="x"),
    )
    payload = msg.to_payload()
    payload["harness_policy"]["max_tool_calls"] = -1
    with pytest.raises(jsonschema.ValidationError):
        Draft202012Validator(schema).validate(payload)


def test_protocol_version_out_of_range_fails_validation():
    schema = agent_handoff_schema()
    payload = AgentHandoff(lane="x").to_payload()
    payload["agent_interface_version"] = 99
    with pytest.raises(jsonschema.ValidationError):
        Draft202012Validator(schema).validate(payload)


# ---------------------------------------------------------------------------
# Committed JSON files match code-generated schemas (catches drift)
# ---------------------------------------------------------------------------


def test_committed_schema_files_exist_for_every_dto():
    expected = set(json_schemas().keys())
    on_disk = {p.stem for p in SCHEMAS_DIR.glob("*.json")}
    assert on_disk == expected


def test_committed_schema_files_match_code():
    """Run `python scripts/generate_schemas.py` if this fails."""
    schemas = json_schemas()
    for name, expected in schemas.items():
        path = SCHEMAS_DIR / f"{name}.json"
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert on_disk == expected, (
            f"{path.name} is out of date — "
            "run `python scripts/generate_schemas.py` to regenerate."
        )


def test_committed_schemas_accessible_via_importlib_resources():
    """Schemas resolve through ``importlib.resources`` at runtime.

    Note: this passes in an editable / source-tree install regardless
    of ``[tool.setuptools.package-data]`` because the .json files
    physically live in the package directory. The real packaging
    coverage lives in
    ``test_committed_schemas_present_in_built_wheel`` and
    ``test_committed_schemas_present_in_built_sdist`` below, which
    invoke a real build and inspect the resulting archive.
    """
    import importlib.resources

    package_root = importlib.resources.files("agent_interface_protocol")
    schemas_dir = package_root / "schemas"
    files = {p.name for p in schemas_dir.iterdir() if p.name.endswith(".json")}
    expected = {f"{name}.json" for name in json_schemas()}
    assert files == expected


def test_committed_schemas_present_in_built_wheel(tmp_path):
    """Build a real wheel and assert every schema JSON is inside it.

    This is the headline-claim guard: the importlib test above cannot
    distinguish a properly packaged build from a source-tree happy
    path. This one fails if ``[tool.setuptools.package-data]`` is
    missing, mistyped, or pointed at the wrong glob.
    """
    build = pytest.importorskip("build")
    import zipfile

    builder = build.ProjectBuilder(REPO_ROOT)
    wheel_path = Path(builder.build("wheel", str(tmp_path)))
    with zipfile.ZipFile(wheel_path) as zf:
        names = set(zf.namelist())

    expected = {
        f"agent_interface_protocol/schemas/{name}.json"
        for name in json_schemas()
    }
    missing = expected - names
    assert not missing, (
        f"schemas missing from built wheel {wheel_path.name}: "
        f"{sorted(missing)}"
    )


def test_committed_schemas_present_in_built_sdist(tmp_path):
    """Build a real sdist and assert every schema JSON is inside it.

    Guards against a setuptools regression where ``package-data`` is
    honored by the wheel build but dropped from the sdist when
    ``include-package-data`` is unset. With pip falling back to sdist
    in some environments, this matters for installed consumers that
    read schemas via ``importlib.resources``.
    """
    build = pytest.importorskip("build")
    import tarfile

    builder = build.ProjectBuilder(REPO_ROOT)
    sdist_path = Path(builder.build("sdist", str(tmp_path)))
    with tarfile.open(sdist_path) as tf:
        # sdist tar entries are prefixed with `<name>-<version>/`.
        names = [m.name for m in tf.getmembers() if m.isfile()]

    expected_suffixes = {
        f"agent_interface_protocol/schemas/{name}.json"
        for name in json_schemas()
    }
    found = {
        suffix
        for suffix in expected_suffixes
        if any(n.endswith(suffix) for n in names)
    }
    missing = expected_suffixes - found
    assert not missing, (
        f"schemas missing from built sdist {sdist_path.name}: "
        f"{sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


from agent_interface_protocol.schema import _cli  # noqa: E402


def test_cli_lists_names(capsys):
    code = _cli(["--list"])
    captured = capsys.readouterr()
    assert code == 0
    lines = [line for line in captured.out.splitlines() if line]
    assert lines == sorted(json_schemas())


def test_cli_lists_when_no_args(capsys):
    code = _cli([])
    captured = capsys.readouterr()
    assert code == 0
    assert "AgentMessage" in captured.out


def test_cli_dumps_named_schema(capsys):
    code = _cli(["ErrorInfo"])
    captured = capsys.readouterr()
    assert code == 0
    parsed = json.loads(captured.out)
    assert parsed == json_schemas()["ErrorInfo"]


def test_cli_dumps_all(capsys):
    code = _cli(["--all"])
    captured = capsys.readouterr()
    assert code == 0
    parsed = json.loads(captured.out)
    assert set(parsed) == set(json_schemas())


def test_cli_rejects_unknown_name(capsys):
    code = _cli(["NotAThing"])
    captured = capsys.readouterr()
    assert code == 2
    assert "unknown schema" in captured.err
    assert "available:" in captured.err


def test_cli_indent_zero_emits_single_line(capsys):
    code = _cli(["ErrorInfo", "--indent", "0"])
    captured = capsys.readouterr()
    assert code == 0
    assert "\n" not in captured.out.strip()


def test_cli_rejects_combined_selectors(capsys):
    """NAME, --list, and --all are mutually exclusive."""
    with pytest.raises(SystemExit) as excinfo:
        _cli(["ErrorInfo", "--list"])
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "mutually exclusive" in err

    with pytest.raises(SystemExit) as excinfo:
        _cli(["ErrorInfo", "--all"])
    assert excinfo.value.code == 2

    with pytest.raises(SystemExit) as excinfo:
        _cli(["--list", "--all"])
    assert excinfo.value.code == 2
