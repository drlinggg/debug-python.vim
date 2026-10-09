"""Tests for pydbg.protocol dataclasses at the to_json / parse seams."""
from protocol import (
    Bytecode,
    ClearBreakpoint,
    Continue,
    Disassemble,
    Evaluate,
    Evaluation,
    GetVariables,
    Output,
    SetBreakpoint,
    StepInto,
    StepOut,
    StepOver,
    Stop,
    Stopped,
    Terminated,
    Variables,
    parse_command,
)


def test_evaluate_command() -> None:
    assert Evaluate("x and y").to_json() == {"cmd": "evaluate", "expr": "x and y"}
    assert parse_command({"cmd": "evaluate", "expr": "x"}) == Evaluate("x")


def test_disassemble_command_and_bytecode_event() -> None:
    assert Disassemble().to_json() == {"cmd": "disassemble"}
    assert parse_command({"cmd": "disassemble"}) == Disassemble()
    assert Bytecode("--> LOAD_FAST").to_json() == {
        "event": "bytecode",
        "text": "--> LOAD_FAST",
    }


def test_evaluation_event() -> None:
    ok = Evaluation("x and y", type_name="bool", value="True")
    assert ok.to_json() == {
        "event": "evaluation",
        "expr": "x and y",
        "type": "bool",
        "value": "True",
    }
    bad = Evaluation("nope", error="NameError: name 'nope' is not defined")
    assert bad.to_json() == {
        "event": "evaluation",
        "expr": "nope",
        "error": "NameError: name 'nope' is not defined",
    }


def test_commands_to_json() -> None:
    assert Continue().to_json() == {"cmd": "continue"}
    assert StepOver().to_json() == {"cmd": "step_over"}
    assert StepInto().to_json() == {"cmd": "step_into"}
    assert StepOut().to_json() == {"cmd": "step_out"}
    assert GetVariables().to_json() == {"cmd": "variables"}
    assert Stop().to_json() == {"cmd": "stop"}
    assert SetBreakpoint("/a.py", 10).to_json() == {
        "cmd": "set_breakpoint",
        "file": "/a.py",
        "line": 10,
    }
    assert ClearBreakpoint("/a.py", 10).to_json() == {
        "cmd": "clear_breakpoint",
        "file": "/a.py",
        "line": 10,
    }


def test_events_to_json() -> None:
    assert Stopped("/a.py", 5, "breakpoint").to_json() == {
        "event": "stopped",
        "file": "/a.py",
        "line": 5,
        "reason": "breakpoint",
    }
    assert Output("hi").to_json() == {"event": "output", "text": "hi"}
    assert Terminated().to_json() == {"event": "terminated"}
    local_vars = {"x": {"type": "int", "value": "10"}}
    assert Variables(local_vars, {}).to_json() == {
        "event": "variables",
        "locals": local_vars,
        "globals": {},
    }


def test_parse_command_round_trips() -> None:
    assert parse_command({"cmd": "step_over"}) == StepOver()
    assert parse_command({"cmd": "set_breakpoint", "file": "/a.py", "line": 10}) == (
        SetBreakpoint("/a.py", 10)
    )
    assert parse_command({"cmd": "variables"}) == GetVariables()
