"""Tests for pydbg.bridge.Bridge framing (no real sockets)."""
import json

from bridge import Bridge
from protocol import Output


def test_encode_produces_one_ndjson_line() -> None:
    raw = Bridge.encode(Output("hi"))
    assert raw.endswith(b"\n")
    assert raw.count(b"\n") == 1
    assert json.loads(raw) == {"event": "output", "text": "hi"}


def test_feed_splits_messages_across_chunk_boundaries() -> None:
    bridge = Bridge("127.0.0.1", 5678)  # no start(): no socket is opened

    first = bridge.feed(b'{"cmd": "step_over"}\n{"cmd":')
    assert first == [{"cmd": "step_over"}]

    second = bridge.feed(b' "stop"}\n')
    assert second == [{"cmd": "stop"}]


def test_feed_ignores_blank_lines() -> None:
    bridge = Bridge("127.0.0.1", 5678)
    assert bridge.feed(b"\n\n") == []
