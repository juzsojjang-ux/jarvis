import json
from pathlib import Path

from jarvis.tools import plugins


def _make_plugin(root: Path, name: str, server: str):
    d = root / name
    d.mkdir(parents=True)
    (d / ".mcp.json").write_text(json.dumps({"mcpServers": {server: {"command": "x"}}}),
                                 encoding="utf-8")
    return d


def test_discover_disabled_returns_empty(tmp_path):
    _make_plugin(tmp_path, "notion-plugin", "notion")
    assert plugins.discover(False, path=tmp_path) == []


def test_discover_and_servers(tmp_path):
    _make_plugin(tmp_path, "notion-plugin", "notion")
    cfgs = plugins.discover(True, path=tmp_path)
    assert cfgs and cfgs[0]["type"] == "local"
    assert plugins.plugin_servers(path=tmp_path) == {"notion"}
    assert plugins.trusted_servers(path=tmp_path) == set()  # trust.json 없음 → 비신뢰


def test_trust_promotes(tmp_path):
    _make_plugin(tmp_path, "notion-plugin", "notion")
    (tmp_path / "trust.json").write_text(json.dumps({"notion-plugin": True}), encoding="utf-8")
    assert plugins.trusted_servers(path=tmp_path) == {"notion"}


def test_broken_dir_is_safe(tmp_path):
    assert plugins.discover(True, path=tmp_path / "nope") == []
    assert plugins.plugin_servers(path=tmp_path / "nope") == set()
