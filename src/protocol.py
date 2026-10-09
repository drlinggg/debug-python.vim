"""Wire protocol for the NDJSON control channel.

Two directions:
    * Commands flow Neovim -> engine (``{"cmd": ...}``).
    * Events flow engine -> Neovim (``{"event": ...}``).

Wire names live in :class:`CommandName`, :class:`EventName` and
:class:`StopReason` (all ``StrEnum``), so no raw strings appear in the
matching logic. Every message is a dataclass with :meth:`to_json`, which
returns a plain ``dict`` ready for :func:`json.dumps`.
"""
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Dict

JsonDict = Dict[str, Any]


class CommandName(StrEnum):
    """Wire names of commands sent from Neovim to the engine."""

    CONTINUE = "continue"
    STEP_OVER = "step_over"
    STEP_INTO = "step_into"
    STEP_OUT = "step_out"
    VARIABLES = "variables"
    EVALUATE = "evaluate"
    DISASSEMBLE = "disassemble"
    STOP = "stop"
    SET_BREAKPOINT = "set_breakpoint"
    CLEAR_BREAKPOINT = "clear_breakpoint"
    PROFILE_START = "profile_start"
    PROFILE_STOP = "profile_stop"


class EventName(StrEnum):
    """Wire names of events sent from the engine to Neovim."""

    STOPPED = "stopped"
    VARIABLES = "variables"
    EVALUATION = "evaluation"
    BYTECODE = "bytecode"
    OUTPUT = "output"
    PROFILER = "profiler"
    TERMINATED = "terminated"


class StopReason(StrEnum):
    """Why execution stopped, shown as a hint in the UI."""

    ENTRY = "entry"
    STEP = "step"
    BREAKPOINT = "breakpoint"
    EXCEPTION = "exception"


# --------------------------------------------------------------------------- #
# Commands: Neovim -> engine
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Continue:
    """Resume until the next breakpoint."""

    def to_json(self) -> JsonDict:
        """Return the wire form of the command."""
        return {"cmd": CommandName.CONTINUE}


@dataclass(frozen=True)
class StepOver:
    """Run the current line, without descending into calls."""

    def to_json(self) -> JsonDict:
        """Return the wire form of the command."""
        return {"cmd": CommandName.STEP_OVER}


@dataclass(frozen=True)
class StepInto:
    """Run the current line, descending into the first call."""

    def to_json(self) -> JsonDict:
        """Return the wire form of the command."""
        return {"cmd": CommandName.STEP_INTO}


@dataclass(frozen=True)
class StepOut:
    """Run until the current function returns."""

    def to_json(self) -> JsonDict:
        """Return the wire form of the command."""
        return {"cmd": CommandName.STEP_OUT}


@dataclass(frozen=True)
class GetVariables:
    """Ask the engine for the variables of the current frame."""

    def to_json(self) -> JsonDict:
        """Return the wire form of the command."""
        return {"cmd": CommandName.VARIABLES}


@dataclass(frozen=True)
class Evaluate:
    """Evaluate an expression in the current frame.

    Attributes:
        expr: The Python expression to evaluate.
    """

    expr: str

    def to_json(self) -> JsonDict:
        """Return the wire form of the command."""
        return {"cmd": CommandName.EVALUATE, "expr": self.expr}


@dataclass(frozen=True)
class Disassemble:
    """Ask for the bytecode of the current frame."""

    def to_json(self) -> JsonDict:
        """Return the wire form of the command."""
        return {"cmd": CommandName.DISASSEMBLE}


@dataclass(frozen=True)
class Stop:
    """Abort the debugged program."""

    def to_json(self) -> JsonDict:
        """Return the wire form of the command."""
        return {"cmd": CommandName.STOP}


@dataclass(frozen=True)
class SetBreakpoint:
    """Add a breakpoint.

    Attributes:
        file: Absolute path of the source file.
        line: 1-based line number.
    """

    file: str
    line: int

    def to_json(self) -> JsonDict:
        """Return the wire form of the command."""
        return {"cmd": CommandName.SET_BREAKPOINT, "file": self.file, "line": self.line}


@dataclass(frozen=True)
class ProfilerStart:
    """Start sampling the debuggee with pyinstrument."""
    def to_json(self) -> JsonDict:
        """Return the wire form of the command."""
        return {"cmd": CommandName.PROFILE_START}


@dataclass(frozen=True)
class ProfilerStop:
    """Stop sampling and return the report."""
    def to_json(self) -> JsonDict:
        """Return the wire form of the command."""
        return {"cmd": CommandName.PROFILE_STOP}


@dataclass(frozen=True)
class ClearBreakpoint:
    """Remove a breakpoint.

    Attributes:
        file: Absolute path of the source file.
        line: 1-based line number.
    """

    file: str
    line: int

    def to_json(self) -> JsonDict:
        """Return the wire form of the command."""
        return {
            "cmd": CommandName.CLEAR_BREAKPOINT,
            "file": self.file,
            "line": self.line,
        }


# --------------------------------------------------------------------------- #
# Events: engine -> Neovim
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Stopped:
    """Execution halted at a line.

    Attributes:
        file: Absolute path of the current source file.
        line: 1-based line number.
        reason: A :class:`StopReason` value.
    """

    file: str
    line: int
    reason: str

    def to_json(self) -> JsonDict:
        """Return the wire form of the event."""
        return {
            "event": EventName.STOPPED,
            "file": self.file,
            "line": self.line,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Variables:
    """A snapshot of the current frame's variables.

    Attributes:
        local_vars: Mapping name -> descriptor for locals.
        global_vars: Mapping name -> descriptor for globals.
    """

    local_vars: JsonDict
    global_vars: JsonDict

    def to_json(self) -> JsonDict:
        """Return the wire form of the event."""
        return {
            "event": EventName.VARIABLES,
            "locals": self.local_vars,
            "globals": self.global_vars,
        }


@dataclass(frozen=True)
class ProfilerReport:
    """A rendered pyinstrument report."""
    text: str

    def to_json(self) -> JsonDict:
        return {"event": EventName.PROFILER, "text": self.text}


@dataclass(frozen=True)
class Evaluation:
    """The result of an :class:`Evaluate` command.

    On success ``type_name`` and ``value`` are set; on failure ``error`` is.

    Attributes:
        expr: The expression that was evaluated.
        type_name: Runtime type name of the result (success only).
        value: ``repr`` of the result (success only).
        error: Error text (failure only).
    """

    expr: str
    type_name: str | None = None
    value: str | None = None
    error: str | None = None

    def to_json(self) -> JsonDict:
        """Return the wire form of the event."""
        data: JsonDict = {"event": EventName.EVALUATION, "expr": self.expr}
        if self.error is not None:
            data["error"] = self.error
        else:
            data["type"] = self.type_name
            data["value"] = self.value
        return data


@dataclass(frozen=True)
class Bytecode:
    """A disassembly listing of the current frame.

    Attributes:
        text: The ``dis`` output, with ``-->`` on the current instruction.
    """

    text: str

    def to_json(self) -> JsonDict:
        """Return the wire form of the event."""
        return {"event": EventName.BYTECODE, "text": self.text}


@dataclass(frozen=True)
class Output:
    """A free-text line for the user.

    Attributes:
        text: Message to display.
    """

    text: str

    def to_json(self) -> JsonDict:
        """Return the wire form of the event."""
        return {"event": EventName.OUTPUT, "text": self.text}


@dataclass(frozen=True)
class Terminated:
    """The debugged program finished."""

    def to_json(self) -> JsonDict:
        """Return the wire form of the event."""
        return {"event": EventName.TERMINATED}


# Any command the engine may receive.
Command = (
    Continue
    | StepOver
    | StepInto
    | StepOut
    | GetVariables
    | Evaluate
    | Disassemble
    | Stop
    | SetBreakpoint
    | ClearBreakpoint
    | ProfilerStart
    | ProfilerStop
)


# --------------------------------------------------------------------------- #
# Parsing incoming commands
# --------------------------------------------------------------------------- #
def parse_command(data: JsonDict) -> Command:
    """Turn a decoded wire dict into a command dataclass.

    Args:
        data: A decoded JSON object with a ``"cmd"`` key.

    Returns:
        The matching command dataclass.

    Raises:
        ValueError: If the ``"cmd"`` field is missing or unknown.
    """
    raw = data.get("cmd")
    try:
        name = CommandName(raw)
    except ValueError:
        raise ValueError(f"unknown command: {raw!r}") from None

    match name:
        case CommandName.CONTINUE:
            return Continue()
        case CommandName.STEP_OVER:
            return StepOver()
        case CommandName.STEP_INTO:
            return StepInto()
        case CommandName.STEP_OUT:
            return StepOut()
        case CommandName.VARIABLES:
            return GetVariables()
        case CommandName.EVALUATE:
            return Evaluate(data["expr"])
        case CommandName.DISASSEMBLE:
            return Disassemble()
        case CommandName.STOP:
            return Stop()
        case CommandName.SET_BREAKPOINT:
            return SetBreakpoint(data["file"], int(data["line"]))
        case CommandName.CLEAR_BREAKPOINT:
            return ClearBreakpoint(data["file"], int(data["line"]))
        case CommandName.PROFILE_START:
            return ProfilerStart()
        case CommandName.PROFILE_STOP:
            return ProfilerStop()
