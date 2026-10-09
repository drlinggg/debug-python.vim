"""Runtime configuration for the debug engine.

This module is the single home for constants. Connection settings come from a
``.env`` file (see ``.env.example``) with safe defaults; the rest are tunables
the other modules import instead of hard-coding their own.
"""

import sys
import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_HOST: str = "127.0.0.1"
DEFAULT_PORT: int = 5678

# Socket read size for the NDJSON channel (bridge).
RECV_BUFSIZE: int = 4096
# Variables panel (describer).
MAX_REPR: int = 200   # clip long repr() strings
MAX_DEPTH: int = 3    # levels of nested user objects to expand
# sys.monitoring tool id the engine claims.
MONITOR_TOOL_ID: int = sys.monitoring.DEBUGGER_ID


@dataclass(frozen=True)
class Config:
    """Connection settings shared by the engine and the plugin.

    Attributes:
        host: IP address the engine binds to and the plugin connects to.
        port: TCP port used for the NDJSON control channel.
    """

    host: str
    port: int

    @classmethod
    def load(cls, env_file: str | None = None) -> "Config":
        """Build a Config from environment variables, filled from ``.env``.

        Existing process environment variables win over the file. Missing
        values fall back to :data:`DEFAULT_HOST` and :data:`DEFAULT_PORT`.

        Args:
            env_file: Optional path to a ``.env`` file. When ``None`` the
                library searches the working directory upward.

        Returns:
            A frozen Config with the resolved host and port.
        """
        if env_file is not None:
            load_dotenv(env_file)
        else:
            load_dotenv()
        host = os.getenv("PYDBG_HOST", DEFAULT_HOST)
        port = int(os.getenv("PYDBG_PORT", str(DEFAULT_PORT)))
        return cls(host=host, port=port)
