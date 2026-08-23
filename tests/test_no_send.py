from pathlib import Path

import pytest

import sedb_ral.no_send as no_send
from sedb_ral.no_send import scan_no_send

ROOT = Path(__file__).parents[1]


def test_source_tree_contains_no_send_capability():
    assert scan_no_send(ROOT / "src/sedb_ral") == ()


def test_task5_script_allows_only_its_isolated_sedb_imports():
    scanner = getattr(no_send, "scan_task5_no_send", None)

    assert callable(scanner), "Task 5 executable boundary is not scanned"
    assert scanner(ROOT / "scripts/validate_sedb_v04b.py") == ()


@pytest.mark.parametrize(
    ("source", "expected_code"),
    [
        ("import requests\nrequests.get('https://example.test')\n", "forbidden_import:requests"),
        ("import urllib\nurllib.request.urlopen('https://example.test')\n", "forbidden_import:urllib"),
        ("import http\nhttp.client.HTTPConnection('example.test')\n", "forbidden_import:http"),
        ("import subprocess\nsubprocess.run(['echo'])\n", "forbidden_import:subprocess"),
        ("from sedb.runtime import Runtime\n", "forbidden_import:sedb"),
    ],
    ids=["requests", "urllib", "http", "subprocess", "unapproved-sedb"],
)
def test_task5_script_rejects_network_process_and_other_sedb_imports(
    tmp_path, source, expected_code
):
    script = tmp_path / "validate_sedb_v04b.py"
    script.write_text(source, encoding="utf-8")

    assert expected_code in {
        finding.code for finding in no_send.scan_task5_no_send(script)
    }


def test_missing_package_root_is_not_a_clean_scan(tmp_path):
    findings = scan_no_send(tmp_path / "missing")

    assert [item.code for item in findings] == ["package_root_missing"]


def test_package_root_file_is_not_a_clean_scan(tmp_path):
    package = tmp_path / "package.py"
    package.write_text("value = 1\n", encoding="utf-8")

    findings = scan_no_send(package)

    assert [item.code for item in findings] == ["package_root_not_directory"]


def test_directory_without_python_source_is_not_a_clean_scan(tmp_path):
    (tmp_path / "README.md").write_text("not Python\n", encoding="utf-8")

    findings = scan_no_send(tmp_path)

    assert [item.code for item in findings] == ["python_source_missing"]


def test_scanned_clean_package_is_an_actual_positive_control(tmp_path):
    (tmp_path / "clean.py").write_text("value = 1\n", encoding="utf-8")

    assert scan_no_send(tmp_path) == ()


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
