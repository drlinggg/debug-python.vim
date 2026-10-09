"""The socket side of the debugger.

Bridge owns the whole TCP + NDJSON channel. The Engine talks to Neovim only
through this class, so no socket code leaks into the debugging logic.
"""

import json
import socket
from typing import Any, Dict, List, Optional, Protocol

from config import RECV_BUFSIZE

JsonDict = Dict[str, Any]


class Message(Protocol):
    """Anything the Bridge can serialise: it exposes ``to_json``."""

    def to_json(self) -> JsonDict:
        """Return the wire form of the message."""
        ...


class Bridge:
    """A one-client TCP server that speaks NDJSON.

    Attributes:
        host: Address to bind.
        port: TCP port to bind.
    """

    def __init__(self, host: str, port: int) -> None:
        """Store the address. No socket is opened until :meth:`start`.

        Args:
            host: Address to bind.
            port: TCP port to bind.
        """
        self.host = host
        self.port = port
        self._server: Optional[socket.socket] = None
        self._conn: Optional[socket.socket] = None
        self._rxbuf = b""
        self._queue: List[JsonDict] = []

    @staticmethod
    def encode(message: Message) -> bytes:
        """Serialise a message to a single NDJSON line.

        Args:
            message: An object exposing ``to_json``.

        Returns:
            UTF-8 bytes ending in a newline.
        """
        return (json.dumps(message.to_json()) + "\n").encode("utf-8")

    def feed(self, chunk: bytes) -> List[JsonDict]:
        """Add bytes to the receive buffer and return complete messages.

        Partial lines stay buffered until their newline arrives. Blank lines
        are ignored.

        Args:
            chunk: Newly received bytes.

        Returns:
            Zero or more decoded JSON objects, in arrival order.
        """
        self._rxbuf += chunk
        messages: List[JsonDict] = []
        while b"\n" in self._rxbuf:
            raw, self._rxbuf = self._rxbuf.split(b"\n", 1)
            if raw.strip():
                messages.append(json.loads(raw))
        return messages

    # -- socket lifecycle ------------------------------------------------- #
    def start(self) -> None:
        """Bind, listen and accept the single Neovim connection (blocking)."""
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self.host, self.port))
        self._server.listen(1)
        self._conn, _addr = self._server.accept()

    def send(self, message: Message) -> None:
        """Send one message to Neovim.

        Args:
            message: An object exposing ``to_json``.

        Raises:
            RuntimeError: If called before :meth:`start`.
        """
        if self._conn is None:
            raise RuntimeError("Bridge.send called before start()")
        self._conn.sendall(self.encode(message))

    def recv_command(self) -> Optional[JsonDict]:
        """Block until one command arrives; return it as a dict.

        Returns:
            The next decoded command, or ``None`` if the peer closed.

        Raises:
            RuntimeError: If called before :meth:`start`.
        """
        if self._conn is None:
            raise RuntimeError("Bridge.recv_command called before start()")
        while not self._queue:
            chunk = self._conn.recv(RECV_BUFSIZE)
            if not chunk:
                return None
            self._queue.extend(self.feed(chunk))
        return self._queue.pop(0)

    def close(self) -> None:
        """Close the client connection and the listening socket."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        if self._server is not None:
            self._server.close()
            self._server = None
