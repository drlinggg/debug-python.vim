# nvim-python-debugger

![vibecoded](https://img.shields.io/badge/vibecoded-70%25-purple)
![python](https://img.shields.io/badge/python-3.14-blue)
![transport](https://img.shields.io/badge/transport-NDJSON%20%2F%20TCP-informational)
![profiler](https://img.shields.io/badge/profiler-pyinstrument-orange)
![debugger](https://img.shields.io/badge/debugger-sys.monitoring-red)

A small Python debugger with a Neovim front-end.

* The **engine** is a `sys.monitoring` tracer (PEP 669, Python 3.12+). It runs
  your program, stops at lines and breakpoints, and reports state.
* The **plugin** is the UI. It highlights the current line, opens the file
  under execution, shows a foldable variables panel, a bytecode view, an eval
  panel, and a `pyinstrument` profile.

They talk over a TCP socket with newline-delimited JSON (NDJSON).

```
┌──────────────┐   NDJSON over TCP    ┌──────────────────────────┐
│ Neovim plugin│ ──── commands ─────► │ Python engine            │
│   (client)   │ ◄──── events ─────── │ sys.monitoring + bridge  │
└──────────────┘   127.0.0.1:5678     │ describer + pyinstrument │
                                      └──────────────────────────┘
```

## Layout

```
.
├── main.py                 # entry point: nvim launches `python main.py <file>`
├── src/
│   ├── config.py           # HOST/PORT, RECV_BUFSIZE, MONITOR_TOOL_ID, MAX_REPR
│   ├── protocol.py         # command + event dataclasses (StrEnum wire names)
│   ├── bridge.py           # TCP server + NDJSON framing (all socket code)
│   ├── describer.py        # frame -> typed, filtered variables view
│   └── engine.py           # Engine: sys.monitoring tracer using Bridge
├── plugin/
│   ├── pydbg_config.vim    # constants, colours, signs (loads first)
│   └── pydebugger.vim      # logic, commands, key maps
├── examples/               # sample_a.py / sample_b.py — demo targets
├── tests/                  # pytest unit + behaviour tests
├── .env.example            # PYDBG_HOST / PYDBG_PORT
└── requirements.txt        # python-dotenv, pyinstrument
```

## Setup

```sh
cd nvim-python-debugger
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cp .env.example .env            # optional: edit host/port
```

Install the plugin (vim-plug):

```vim
Plug 'drlinggg/debug-python.vim'
```

The plugin finds the engine through `g:pydebugger_python` (defaults to the
project `.venv`) and `g:pydebugger_main`. Override in `init.vim` if needed.

## Hotkeys

| Key | Action            |
|-----|-------------------|
| F3  | toggle bytecode panel |
| F4  | eval an expression |
| F5  | continue          |
| F6  | step over         |
| F7  | step into         |
| F8  | step out          |
| F9  | toggle breakpoint |
| F10 | connect / start engine for the current file |
| F11 | one-shot profile (auto-resumes, report at next stop) |
| F12 | disconnect / stop engine |

In the variables panel, `<Tab>` (or `za`) folds/unfolds a section.
`:PyDbgHelp` prints the keys.

## Transport

| Item     | Value                                        |
|----------|----------------------------------------------|
| Protocol | TCP                                          |
| Host     | `127.0.0.1` (`PYDBG_HOST`, `g:pydebugger_host`) |
| Port     | `5678` (`PYDBG_PORT`, `g:pydebugger_port`)   |
| Framing  | NDJSON — one JSON object per line, `\n`, UTF-8 |
| Roles    | engine = server, Neovim = client             |

Rules: one object per line; `file` is always absolute; variable values are
`repr()` strings; the plugin asks for `variables` after every `stopped`.

## Commands (nvim → engine)

| cmd                | fields          |
|--------------------|-----------------|
| `continue`         | —               |
| `step_over`        | —               |
| `step_into`        | —               |
| `step_out`         | —               |
| `set_breakpoint`   | `file`, `line`  |
| `clear_breakpoint` | `file`, `line`  |
| `variables`        | —               |
| `evaluate`         | `expr`          |
| `disassemble`      | —               |
| `profile_start`    | —               |
| `profile_stop`     | —               |
| `stop`             | —               |

## Events (engine → nvim)

`stopped` — execution halted:

```json
{"event": "stopped", "file": "/abs/a.py", "line": 8, "reason": "breakpoint"}
```

`reason` is `breakpoint`, `step`, or `exception` (post-mortem stop on an
uncaught exception).

`variables` — typed snapshot. Each value carries its true runtime type;
user-defined class instances expand their attributes recursively up to
`MAX_DEPTH`, with a cycle guard:

```json
{"event": "variables",
 "locals":  {"n": {"type": "int", "value": "22"},
             "p": {"type": "Point", "value": "<Point>",
                   "attributes": {"x": {"type": "int", "value": "1"}}}},
 "globals": {"CONST": {"type": "int", "value": "42"}}}
```

Modules, classes and functions are rendered by their clean name — no `repr()`
noise, no `<module 'asyncio' from '/opt/...'>`:

```json
{"type": "module",   "value": "asyncio"}
{"type": "class",    "value": "Point"}
{"type": "function", "value": "compute"}
```

Only user data appears in `globals` (modules, functions and classes are
hidden) so the panel is not flooded with every live object.

`evaluation` — result of an `evaluate` command:

```json
{"event": "evaluation", "expr": "x + 1", "type": "int", "value": "11"}
```

On failure, `error` instead of `type`/`value`.

`bytecode` — the dis listing of the current frame, with `-->` marking the
current instruction offset:

```json
{"event": "bytecode", "text": " 12 LOAD_FAST  0 (x)\n--> 14 ..."}
```

`profiler` — a rendered `pyinstrument` report (plain text, no ANSI colour):

```json
{"event": "profiler", "text": "0.244 compute  sample_a.py:25\n..."}
```

`output` — free text. `terminated` — the program finished; the plugin clears
the current-line sign and closes the variables and bytecode panels.

## Try it

```sh
nvim examples/sample_a.py
```

1. Press **F10**. The engine starts for this file and stops at the first line.
2. Move to line 15, press **F9** (red dot), press **F5** → stop at line 15.
3. Press **F7** → execution enters `sample_b.py` in a new tab; the current
   line is highlighted and the panel shows `n` and `CONST` with types.
4. Press **F3** → bytecode panel opens on the right, `-->` tracks the current
   instruction as you step.
5. Press **F4** and type `z * 2` → the result lands in the Eval section of the
   variables panel.
6. Press **F11** → profiling starts and the engine auto-resumes. When the
   next breakpoint (or program end) is reached, the report appears in
   `__PyDbgProfiler__`.
7. Press **F5** → the program finishes and the panels close.

## What is `sys.monitoring`, and why use it?

PEP 669 (`sys.monitoring`, Python 3.12+) lets a tool subscribe to execution
events and **`DISABLE`** them per code location. Unlike `sys.settrace` (used
by `bdb`), a line without a breakpoint stops costing after its first hit, so
one breakpoint no longer slows the whole program ~75x — the overhead drops to
a small factor.

The engine instruments only the debugged program. On `PY_START` it enables
`LINE` events locally for frames that descend from the run entry
(`_botframe`). Stepping uses call-depth tracking:

* `STEP_INTO` — stop on every line,
* `STEP_OVER` — stop when depth returns to the reference depth,
* `STEP_OUT`  — stop when depth drops below it,
* `CONTINUE`  — stop only on a breakpoint.

Breakpoints live in the engine (`self._breakpoints`), keyed by canonicalised
`(co_filename, lineno)`. When a breakpoint is set at runtime,
`sys.monitoring.restart_events()` re-arms every location that was
`DISABLE`d earlier, so the new breakpoint actually fires.

Unlike `pdb`, we do not rewrite bytecode or inject anything — CPython manages
its own instrumentation tables and simply calls our callbacks.

## Stepping into imported modules (e.g. `asyncio`)

When you step into a call like `asyncio.gather(...)`, the engine follows
execution into the next frame. That frame's code object already knows its
source file: `frame.f_code.co_filename` points at the real stdlib path
(e.g. `.../python3.14/asyncio/tasks.py`). The engine sends that absolute path
in the `stopped` event, and the plugin opens it like any other file. So
"jumping into asyncio" works without any import resolution on our side — we do
not search `sys.path`; Python already records each code object's file.

Two caveats:

* C-implemented functions (many builtins, some stdlib) have no Python source,
  so there is nothing to step into.
* Stepping into the stdlib is noisy. A "just my code" filter is a natural
  next step — a config list of `co_filename` prefixes to skip on `PY_START`.

## Profiling

`F11` is a **one-shot** profile:

1. The plugin sends `profile_start`. The engine spins up a
   `pyinstrument.Profiler(interval=0.001)`, starts it, switches to
   `CONTINUE`, and returns from the command loop — the program resumes on
   its own.
2. When execution reaches the next breakpoint (or the program ends), the
   engine calls `_finish_profiling()`: it stops the profiler, renders
   `output_text(short_mode=True, color=False)`, and sends a `profiler`
   event.
3. The plugin lands the report in the `__PyDbgProfiler__` buffer on the
   right. No second keypress, no manual stop.

`pyinstrument` is a **sampling** profiler: it wakes up ~every 1 ms and
records the current stack. Overhead does not scale with the number of calls,
which is why it coexists with our `sys.monitoring` tracer. It does **not**
claim `sys.monitoring.PROFILER_ID`, so `cProfile` and friends still work.

Because sampling is wall-clock, the report includes any time the program
spent paused at a breakpoint. If you want clean CPU numbers, start the
profile and let it run without stopping until the program ends.

## Tests

```sh
PYTHONPATH=src ./.venv/bin/python -m pytest tests/ -q
```

Seams under test: `protocol` to_json/parse, `Describer`, `Bridge` NDJSON
framing, and `Engine` behaviour (step over/into/out, breakpoint during
step-over, disable-and-restart semantics) driven through a fake bridge.
