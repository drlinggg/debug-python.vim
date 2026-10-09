"""The debug engine: a sys.monitoring tracer driven over the Bridge.

PEP 669 (``sys.monitoring``, Python 3.12+) lets a tool subscribe to execution
events and ``DISABLE`` them per code location. Unlike ``sys.settrace`` (used by
bdb), a line without a breakpoint stops costing after its first hit, so one
breakpoint no longer slows the whole program ~75x — the overhead drops to a
small factor.

We instrument only the debugged program: on ``PY_START`` we enable ``LINE``
events locally for frames that descend from the run entry (``_botframe``).
Stepping uses call-depth tracking; breakpoints live in the engine.
"""
import dis
import os
import sys
from pyinstrument import Profiler
from enum import Enum, auto
from types import FrameType
from typing import Any, Callable, Dict, Set, Tuple

from bridge import Bridge
from config import MONITOR_TOOL_ID
from describer import Describer
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
    ProfilerStart,
    ProfilerStop,
    ProfilerReport,
    StopReason,
    Stopped,
    Terminated,
    Variables,
    parse_command,
)

BreakKey = Tuple[str, int]
_EVENTS = sys.monitoring.events


class _Mode(Enum):
    """How execution should proceed after the current stop."""

    CONTINUE = auto()
    STEP_INTO = auto()
    STEP_OVER = auto()
    STEP_OUT = auto()


class _Quit(BaseException):
    """Raised inside a monitoring callback to abort the debuggee."""




class Engine:
    """A sys.monitoring tracer that speaks the wire protocol via a Bridge.

    Attributes:
        bridge: The channel to Neovim.
        describer: Builds the typed variables view of a frame.
    """

    def __init__(self, bridge: Bridge, describer: Describer) -> None:
        """Create the engine.

        Args:
            bridge: Transport to Neovim.
            describer: Variable describer for the panel.
        """
        self._bridge = bridge
        self._describer = describer
        self._breakpoints: Set[BreakKey] = set()
        self._debuggee: Set[int] = set()
        self._mode = _Mode.STEP_INTO
        self._ref_depth = 0
        self._botframe: FrameType | None = None
        self._root_code: Any = None  # code object of the debuggee entry
        self._canonic_cache: Dict[str, str] = {}  # co_filename -> canonical path

        self._profile_pending = False
        self._profiler: Profiler | None = None

    # -- entry points ----------------------------------------------------- #
    def run_file(self, path: str) -> None:
        """Run a target file top-to-bottom under the debugger.

        Args:
            path: Absolute path of the Python file to debug.
        """
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        code = compile(source, path, "exec")
        namespace: Dict[str, Any] = {"__name__": "__main__", "__file__": path}
        self._prepare()
        self._root_code = code
        self._botframe = sys._getframe()
        self._start()
        try:
            exec(code, namespace, namespace)
        except _Quit:
            pass
        except Exception as exc:  # uncaught in the debuggee: post-mortem stop
            self._handle_uncaught(exc)
        finally:
            if self._profile_pending:
                self._finish_profiling()
            self._stop()
            self._bridge.send(Terminated())

    def run_call(self, func: Callable[..., Any], *args: Any) -> None:
        """Run a single callable under the debugger.

        Args:
            func: The callable to debug.
            *args: Positional arguments for ``func``.
        """
        self._prepare()
        self._root_code = getattr(func, "__code__", None)
        self._botframe = sys._getframe()
        self._start()
        try:
            func(*args)
        except _Quit:
            pass
        except Exception as exc:
            self._handle_uncaught(exc)
        finally:
            if self._profile_pending:
                self._finish_profiling()
            self._stop()
            self._bridge.send(Terminated())

    def _prepare(self) -> None:
        """Reset per-run state. The first stop is the program entry."""
        self._debuggee = set()
        self._mode = _Mode.STEP_INTO
        self._ref_depth = 0

    # -- monitoring lifecycle --------------------------------------------- #
    def _start(self) -> None:
        """Claim the tool id and subscribe to call/return events."""
        mon = sys.monitoring
        try:
            mon.use_tool_id(MONITOR_TOOL_ID, "pydbg")
        except ValueError:  # recover a tool id left claimed by a crashed run
            mon.free_tool_id(MONITOR_TOOL_ID)
            mon.use_tool_id(MONITOR_TOOL_ID, "pydbg")
        mon.register_callback(MONITOR_TOOL_ID, _EVENTS.PY_START, self._on_start)
        mon.register_callback(MONITOR_TOOL_ID, _EVENTS.PY_RETURN, self._on_return)
        mon.register_callback(MONITOR_TOOL_ID, _EVENTS.PY_UNWIND, self._on_unwind)
        mon.register_callback(MONITOR_TOOL_ID, _EVENTS.LINE, self._on_line)
        mon.set_events(MONITOR_TOOL_ID, _EVENTS.PY_START | _EVENTS.PY_RETURN | _EVENTS.PY_UNWIND)

    def _stop(self) -> None:
        """Unsubscribe and release the tool id."""
        mon = sys.monitoring
        try:
            mon.set_events(MONITOR_TOOL_ID, _EVENTS.NO_EVENTS)
            for event in (
                _EVENTS.PY_START,
                _EVENTS.PY_RETURN,
                _EVENTS.PY_UNWIND,
                _EVENTS.LINE,
            ):
                mon.register_callback(MONITOR_TOOL_ID, event, None)
            mon.free_tool_id(MONITOR_TOOL_ID)
        except ValueError:
            pass

    # -- callbacks -------------------------------------------------------- #
    def _on_start(self, code: Any, offset: int) -> None:
        """Enable LINE events for a frame that belongs to the debuggee.

        Args:
            code: The starting code object.
            offset: Instruction offset (unused).
        """
        frame = sys._getframe(1)
        if code is self._root_code or id(frame.f_back) in self._debuggee:
            self._debuggee.add(id(frame))
            sys.monitoring.set_local_events(MONITOR_TOOL_ID, code, _EVENTS.LINE)

    def _on_return(self, code: Any, offset: int, retval: Any) -> None:
        """Forget a debuggee frame that returned normally."""
        self._debuggee.discard(id(sys._getframe(1)))

    def _on_unwind(self, code: Any, offset: int, exc: BaseException) -> None:
        """Forget a debuggee frame that is unwinding on an exception."""
        self._debuggee.discard(id(sys._getframe(1)))

    def _on_line(self, code: Any, lineno: int) -> Any:
        """Decide, for each debuggee line, whether to stop.

        Args:
            code: The executing code object.
            lineno: The current 1-based line.

        Returns:
            ``sys.monitoring.DISABLE`` to stop future events for this location
            (continue mode, no breakpoint), otherwise ``None``.
        """
        frame = sys._getframe(1)
        is_bp = bool(self._breakpoints) and (
            self._canon(code.co_filename),
            lineno,
        ) in self._breakpoints
        if self._should_stop(frame, is_bp):
            self._interact(frame, is_bp)
            return None
        if self._mode is _Mode.CONTINUE and not is_bp:
            return sys.monitoring.DISABLE
        return None

    def _canon(self, path: str) -> str:
        """Return a cached canonical path (abspath is costly per line event).

        Args:
            path: A ``co_filename`` or breakpoint path.

        Returns:
            The absolute, case-normalised path.
        """
        cached = self._canonic_cache.get(path)
        if cached is None:
            cached = self._canonic_cache[path] = os.path.normcase(
                os.path.abspath(path)
            )
        return cached

    def _should_stop(self, frame: FrameType, is_bp: bool) -> bool:
        """Apply the step policy for the current mode.

        Args:
            frame: The current frame.
            is_bp: Whether a breakpoint sits on this line.

        Returns:
            True if execution should stop here.
        """
        match self._mode:
            case _Mode.CONTINUE:
                return is_bp
            case _Mode.STEP_INTO:
                return True
            case _Mode.STEP_OVER:
                return is_bp or self._depth(frame) <= self._ref_depth
            case _Mode.STEP_OUT:
                return is_bp or self._depth(frame) < self._ref_depth
        return False

    def _depth(self, frame: FrameType) -> int:
        """Return the debuggee call depth of a frame (entry frame = 1)."""
        depth = 0
        current: FrameType | None = frame
        while current is not None and current is not self._botframe:
            depth += 1
            current = current.f_back
        return depth

    # -- interaction ------------------------------------------------------ #
    def _interact(self, frame: FrameType, is_bp: bool) -> None:
        """Report a stop, then process commands until execution resumes.

        Args:
            frame: The frame stopped at.
            is_bp: Whether the stop is on a breakpoint.
        """
        if self._profile_pending:
            self._finish_profiling()

        filename = os.path.abspath(frame.f_code.co_filename)
        reason = StopReason.BREAKPOINT if is_bp else StopReason.STEP
        self._bridge.send(Stopped(filename, frame.f_lineno, reason))
        self._command_loop(frame)

    def _handle_uncaught(self, exc: BaseException) -> None:
        """Stop at the line that raised an uncaught exception.

        The traceback keeps the raising frames alive, so locals are still
        inspectable.

        Args:
            exc: The exception that propagated out of the debuggee.
        """
        tb = exc.__traceback__
        if tb is None:
            return
        while tb.tb_next is not None:
            tb = tb.tb_next
        frame = tb.tb_frame
        filename = os.path.abspath(frame.f_code.co_filename)
        self._bridge.send(Output(f"exception: {type(exc).__name__}: {exc}"))
        self._bridge.send(Stopped(filename, tb.tb_lineno, StopReason.EXCEPTION))
        try:
            self._command_loop(frame)
        except _Quit:
            pass  # nothing left to abort — this is post-mortem

    def _evaluate(self, frame: FrameType, expr: str) -> Evaluation:
        """Evaluate an expression in a frame's namespaces.

        Args:
            frame: The frame whose locals/globals to use.
            expr: The Python expression.

        Returns:
            An Evaluation with the typed result, or an error.
        """
        try:
            value = eval(expr, frame.f_globals, frame.f_locals)  # noqa: S307
        except Exception as exc:  # report any failure, never crash the engine
            return Evaluation(expr, error=f"{type(exc).__name__}: {exc}")
        return Evaluation(expr, type_name=type(value).__name__, value=repr(value))

    def _disassemble(self, frame: FrameType) -> Bytecode:
        """Disassemble the current frame, marking the current instruction.

        Args:
            frame: The frame stopped at.

        Returns:
            A Bytecode event with the ``dis`` listing (``-->`` marks the
            current bytecode offset).
        """
        listing = dis.Bytecode(frame.f_code, current_offset=frame.f_lasti)
        return Bytecode(listing.dis())

    def _finish_profiling(self) -> None:
        """Stop the sampler and push the rendered report to Neovim."""
        self._profile_pending = False
        if self._profiler is None:
            return
        self._profiler.stop()
        report = self._profiler.output_text(short_mode=False, color=True)
        self._bridge.send(ProfilerReport(report))
        self._profiler = None

    def _command_loop(self, frame: FrameType) -> None:
        """Read and apply commands for the current stop.

        Query commands answer in place and keep waiting. Flow commands set the
        next mode and return so execution resumes. ``stop`` / a closed channel
        raise :class:`_Quit` to abort the program.

        Args:
            frame: The frame stopped at.
        """
        while True:
            raw = self._bridge.recv_command()
            if raw is None:
                raise _Quit
            match parse_command(raw):
                case GetVariables():
                    local_vars, global_vars = self._describer.describe(frame)
                    self._bridge.send(Variables(local_vars, global_vars))
                case Evaluate(expr=expr):
                    self._bridge.send(self._evaluate(frame, expr))
                case Disassemble():
                    self._bridge.send(self._disassemble(frame))
                case Continue():
                    self._mode = _Mode.CONTINUE
                    return
                case StepOver():
                    self._mode = _Mode.STEP_OVER
                    self._ref_depth = self._depth(frame)
                    sys.monitoring.restart_events()
                    return
                case StepInto():
                    self._mode = _Mode.STEP_INTO
                    sys.monitoring.restart_events()
                    return
                case StepOut():
                    self._mode = _Mode.STEP_OUT
                    self._ref_depth = self._depth(frame)
                    sys.monitoring.restart_events()
                    return
                case SetBreakpoint(file=bp_file, line=bp_line):
                    self._breakpoints.add((self._canon(bp_file), bp_line))
                    sys.monitoring.restart_events()
                    self._bridge.send(Output(f"breakpoint set {bp_file}:{bp_line}"))
                case ClearBreakpoint(file=bp_file, line=bp_line):
                    self._breakpoints.discard((self._canon(bp_file), bp_line))
                    self._bridge.send(
                        Output(f"breakpoint cleared {bp_file}:{bp_line}")
                    )
                case ProfilerStart():
                    if self._profiler is None and not self._profile_pending:
                        self._profiler = Profiler(interval=0.001)
                        self._profiler.start()
                        self._profile_pending = True
                        self._mode = _Mode.CONTINUE
                        sys.monitoring.restart_events()
                        self._bridge.send(Output("profiling started, running to next stop"))
                        return  
                
                case ProfilerStop():
                    if self._profile_pending or self._profiler is not None:
                        self._finish_profiling()
                case Stop():
                    raise _Quit
