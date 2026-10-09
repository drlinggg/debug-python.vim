"""Behaviour tests for Engine: step over/into/out and breakpoints.

The engine is driven through a FakeBridge: a scripted list of commands in,
a recorded list of events out. No sockets, so the real bdb stepping is what
is under test.

Fixture ``prog.py`` lines:
    1  def inner(a):
    2      b = a + 1
    3      return b
    6  def outer():
    7      x = 1
    8      y = inner(x)   # call site
    9      z = y + 1
    10     return z
"""
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))

import prog  # noqa: E402  (fixture import after path tweak)

from describer import Describer  # noqa: E402
from engine import Engine  # noqa: E402

PROG = os.path.abspath(prog.__file__)


class FakeBridge:
    """A scripted stand-in for the real socket Bridge."""

    def __init__(self, script: List[Dict[str, Any]]) -> None:
        self._script = list(script)
        self.sent: List[Dict[str, Any]] = []

    def send(self, message: Any) -> None:
        self.sent.append(message.to_json())

    def recv_command(self) -> Optional[Dict[str, Any]]:
        return self._script.pop(0) if self._script else None


def stopped_lines(bridge: FakeBridge) -> List[int]:
    return [m["line"] for m in bridge.sent if m["event"] == "stopped"]


def stopped_events(bridge: FakeBridge) -> List[Dict[str, Any]]:
    return [m for m in bridge.sent if m["event"] == "stopped"]


def test_step_over_does_not_enter_callee() -> None:
    bridge = FakeBridge([{"cmd": "step_over"}] * 4)
    Engine(bridge, Describer()).run_call(prog.outer)

    lines = stopped_lines(bridge)
    assert 9 in lines              # reached the line after the call
    assert 2 not in lines          # never stepped into inner
    assert 3 not in lines


def test_step_into_enters_callee() -> None:
    bridge = FakeBridge([{"cmd": "step_over"}, {"cmd": "step_into"}])
    Engine(bridge, Describer()).run_call(prog.outer)

    hits = [(os.path.basename(m["file"]), m["line"]) for m in stopped_events(bridge)]
    assert ("prog.py", 2) in hits  # stepped into inner body


def test_step_out_returns_to_caller() -> None:
    bridge = FakeBridge(
        [{"cmd": "step_over"}, {"cmd": "step_into"}, {"cmd": "step_out"}]
    )
    Engine(bridge, Describer()).run_call(prog.outer)

    last = stopped_events(bridge)[-1]
    assert os.path.basename(last["file"]) == "prog.py"
    assert last["line"] >= 8        # back in outer, past the call


def test_evaluate_expression_in_current_frame() -> None:
    bridge = FakeBridge(
        [{"cmd": "evaluate", "expr": "1 + 2"}, {"cmd": "evaluate", "expr": "nope"}]
    )
    Engine(bridge, Describer()).run_call(prog.outer)

    evals = [m for m in bridge.sent if m["event"] == "evaluation"]
    ok = next(m for m in evals if m["expr"] == "1 + 2")
    assert ok["value"] == "3"
    assert ok["type"] == "int"
    bad = next(m for m in evals if m["expr"] == "nope")
    assert "error" in bad


def test_disassemble_marks_current_instruction() -> None:
    bridge = FakeBridge([{"cmd": "disassemble"}])
    Engine(bridge, Describer()).run_call(prog.outer)

    codes = [m for m in bridge.sent if m["event"] == "bytecode"]
    assert codes, "should return a bytecode listing"
    assert "-->" in codes[0]["text"]


def test_break_on_uncaught_exception() -> None:
    # One continue from the entry stop; then the engine should stop at the
    # raising line instead of crashing.
    bridge = FakeBridge([{"cmd": "continue"}])
    Engine(bridge, Describer()).run_call(prog.boom)

    exc_stops = [
        m for m in stopped_events(bridge) if m["reason"] == "exception"
    ]
    assert exc_stops, "should stop at the raising line"
    assert exc_stops[0]["line"] == 15
    outs = [m for m in bridge.sent if m["event"] == "output"]
    assert any("ZeroDivisionError" in m["text"] for m in outs)


def test_breakpoint_fires_during_step_over() -> None:
    bridge = FakeBridge(
        [
            {"cmd": "step_over"},                               # 7 -> 8
            {"cmd": "set_breakpoint", "file": PROG, "line": 3},  # inside inner
            {"cmd": "step_over"},                               # over inner, but bp fires
        ]
    )
    Engine(bridge, Describer()).run_call(prog.outer)

    bp_stops = [
        m for m in stopped_events(bridge)
        if m["line"] == 3 and m["reason"] == "breakpoint"
    ]
    assert bp_stops, "breakpoint inside a stepped-over call must still stop"
