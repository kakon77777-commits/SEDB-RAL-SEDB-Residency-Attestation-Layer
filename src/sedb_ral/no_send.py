from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

_FORBIDDEN_MODULES = (
    "socket",
    "requests",
    "urllib.request",
    "http.client",
    "httpx",
    "aiohttp",
    "subprocess",
)


@dataclass(frozen=True, order=True)
class NoSendFinding:
    code: str
    path: str
    line: int


def _is_forbidden_module(name: str) -> bool:
    return name == "sedb" or name.startswith("sedb.") or any(
        name == module or name.startswith(module + ".")
        for module in _FORBIDDEN_MODULES
    )


def _import_code(name: str) -> str:
    return (
        "forbidden_import:sedb"
        if name == "sedb" or name.startswith("sedb.")
        else f"forbidden_import:{name}"
    )


def _dotted_name(value: ast.expr) -> str | None:
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        parent = _dotted_name(value.value)
        return None if parent is None else f"{parent}.{value.attr}"
    return None


def _findings(path: Path, root: Path) -> tuple[NoSendFinding, ...]:
    relative = path.relative_to(root).as_posix()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
    except (OSError, UnicodeError, SyntaxError) as error:
        line = getattr(error, "lineno", 0) or 0
        return (NoSendFinding("source_not_parseable", relative, line),)
    findings: list[NoSendFinding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden_module(alias.name):
                    findings.append(NoSendFinding(_import_code(alias.name), relative, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                name = f"{module}.{alias.name}" if module else alias.name
                if _is_forbidden_module(module):
                    findings.append(NoSendFinding(_import_code(module), relative, node.lineno))
                elif _is_forbidden_module(name):
                    findings.append(NoSendFinding(_import_code(name), relative, node.lineno))
        elif isinstance(node, ast.Call):
            name = _dotted_name(node.func)
            if name is not None and any(
                name == module or name.startswith(module + ".")
                for module in _FORBIDDEN_MODULES
            ):
                findings.append(NoSendFinding(f"forbidden_call:{name}", relative, node.lineno))
    return tuple(findings)


def scan_no_send(package_root: Path) -> tuple[NoSendFinding, ...]:
    """Return AST findings for transport/process or external-SEDB imports."""
    root = Path(package_root)
    findings = [finding for path in sorted(root.rglob("*.py")) for finding in _findings(path, root)]
    return tuple(sorted(findings))
