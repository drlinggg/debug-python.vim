"""Entry point for the debug engine.

Neovim launches this with the absolute path of the file to debug. The engine
binds the control socket, waits for Neovim, then runs the target file under
bdb on a worker thread while the main thread waits for it to finish.
"""
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from bridge import Bridge  # noqa: E402
from config import Config  # noqa: E402
from describer import Describer  # noqa: E402
from engine import Engine  # noqa: E402


def main(argv: list[str]) -> int:
    """Start the engine and debug the target file.

    Args:
        argv: Positional arguments after the program name. ``argv[0]`` is the
            absolute path of the Python file Neovim wants to debug.

    Returns:
        Process exit code (0 on success, 2 on bad usage).
    """
    if not argv:
        print("usage: main.py <target.py>", file=sys.stderr)
        return 2

    target = os.path.abspath(argv[0])
    if not os.path.isfile(target):
        print(f"pydbg: no such file: {target}", file=sys.stderr)
        return 2
    # Replicate `python target.py`: the script's own directory is importable,
    # so sibling-module imports in the debugged program resolve.
    sys.path.insert(0, os.path.dirname(target))

    config = Config.load()
    bridge = Bridge(config.host, config.port)
    bridge.start()  # block until Neovim connects

    engine = Engine(bridge, Describer())
    worker = threading.Thread(
        target=engine.run_file, args=(target,), name="pydbg-debuggee", daemon=True
    )
    worker.start()
    worker.join()

    bridge.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
