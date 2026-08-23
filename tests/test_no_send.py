from pathlib import Path

from sedb_ral.no_send import scan_no_send

ROOT = Path(__file__).parents[1]


def test_source_tree_contains_no_send_capability():
    assert scan_no_send(ROOT / "src/sedb_ral") == ()


def test_socket_call_turns_ast_gate_red(tmp_path):
    module = tmp_path / "network.py"
    module.write_text(
        "import socket\nsocket.create_connection(('example.test', 443))\n",
        encoding="utf-8",
    )

    findings = scan_no_send(tmp_path)

    assert [(item.code, item.line) for item in findings] == [
        ("forbidden_call:socket.create_connection", 2),
        ("forbidden_import:socket", 1),
    ]


def test_sedb_import_turns_ast_gate_red(tmp_path):
    module = tmp_path / "external.py"
    module.write_text("import sedb\n", encoding="utf-8")

    findings = scan_no_send(tmp_path)

    assert [(item.code, item.line) for item in findings] == [
        ("forbidden_import:sedb", 1)
    ]


def test_sedb_submodule_import_turns_ast_gate_red(tmp_path):
    module = tmp_path / "external_submodule.py"
    module.write_text("from sedb.runtime import Runtime\n", encoding="utf-8")

    findings = scan_no_send(tmp_path)

    assert [(item.code, item.line) for item in findings] == [
        ("forbidden_import:sedb", 1)
    ]
