"""Tests for pydbg.config at the Config.load seam."""
from pathlib import Path

import pytest

from config import DEFAULT_HOST, DEFAULT_PORT, Config


def test_load_reads_host_and_port_from_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PYDBG_HOST", raising=False)
    monkeypatch.delenv("PYDBG_PORT", raising=False)
    env = tmp_path / ".env"
    env.write_text("PYDBG_HOST=0.0.0.0\nPYDBG_PORT=9000\n")

    cfg = Config.load(str(env))

    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9000


def test_load_falls_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PYDBG_HOST", raising=False)
    monkeypatch.delenv("PYDBG_PORT", raising=False)

    cfg = Config.load("/nonexistent/.env")

    assert cfg.host == DEFAULT_HOST
    assert cfg.port == DEFAULT_PORT
