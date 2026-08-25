from __future__ import annotations

from pathlib import Path

from sedb_ral.no_send import scan_no_send

ROOT = Path(__file__).parents[1]


def test_operations_package_has_no_send_provider_or_private_capability(tmp_path):
    assert scan_no_send(ROOT / "src/sedb_ral/operations") == ()

    injected = tmp_path / "operations"
    injected.mkdir()
    (injected / "network.py").write_text(
        "import socket\nsocket.create_connection(('example.test', 443))\n",
        encoding="utf-8",
    )
    codes = {item.code for item in scan_no_send(injected)}
    assert "forbidden_call:socket.create_connection" in codes
