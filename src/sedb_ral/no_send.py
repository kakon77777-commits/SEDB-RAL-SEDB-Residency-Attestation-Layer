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
_TASK5_FORBIDDEN_MODULES = (
    "socket",
    "requests",
    "urllib",
    "http",
    "httpx",
    "aiohttp",
    "subprocess",
)
_TASK5_ALLOWED_SEDB_IMPORTS = frozenset(
    {
        "sedb.db.Database",
        "sedb.entities.EntityService",
        "sedb.exchange.ExchangeService",
        "sedb.fields.FieldService",
    }
)


@dataclass(frozen=True, order=True)
class NoSendFinding:
    code: str
    path: str
    line: int


def _is_forbidden_module(
    name: str, forbidden_modules: tuple[str, ...]
) -> bool:
    return name == "sedb" or name.startswith("sedb.") or any(
        name == module or name.startswith(module + ".")
        for module in forbidden_modules
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


def _findings(
    path: Path,
    root: Path,
    *,
    allowed_sedb_imports: frozenset[str] = frozenset(),
    forbidden_modules: tuple[str, ...] = _FORBIDDEN_MODULES,
) -> tuple[NoSendFinding, ...]:
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
                if _is_forbidden_module(alias.name, forbidden_modules):
                    findings.append(NoSendFinding(_import_code(alias.name), relative, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                name = f"{module}.{alias.name}" if module else alias.name
                if name in allowed_sedb_imports:
                    continue
                if _is_forbidden_module(module, forbidden_modules):
                    findings.append(NoSendFinding(_import_code(module), relative, node.lineno))
                elif _is_forbidden_module(name, forbidden_modules):
                    findings.append(NoSendFinding(_import_code(name), relative, node.lineno))
        elif isinstance(node, ast.Call):
            name = _dotted_name(node.func)
            if name is not None and any(
                name == module or name.startswith(module + ".")
                for module in forbidden_modules
            ):
                findings.append(NoSendFinding(f"forbidden_call:{name}", relative, node.lineno))
    return tuple(findings)


def scan_no_send(package_root: Path) -> tuple[NoSendFinding, ...]:
    """Return AST findings for transport/process or external-SEDB imports."""
    root = Path(package_root)
    if not root.exists():
        return (NoSendFinding("package_root_missing", ".", 0),)
    if not root.is_dir():
        return (NoSendFinding("package_root_not_directory", ".", 0),)
    paths = sorted(root.rglob("*.py"))
    if not paths:
        return (NoSendFinding("python_source_missing", ".", 0),)
    findings = [
        finding
        for path in paths
        for finding in _findings(path, root)
    ]
    return tuple(sorted(findings))


def scan_task5_no_send(script: Path) -> tuple[NoSendFinding, ...]:
    """Scan the isolated Task 5 executable with only exact SEDB imports allowed."""
    path = Path(script)
    if not path.exists():
        return (NoSendFinding("script_missing", ".", 0),)
    if not path.is_file():
        return (NoSendFinding("script_not_file", ".", 0),)
    return tuple(
        sorted(
            _findings(
                path,
                path.parent,
                allowed_sedb_imports=_TASK5_ALLOWED_SEDB_IMPORTS,
                forbidden_modules=_TASK5_FORBIDDEN_MODULES,
            )
        )
    )
