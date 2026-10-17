"""XML tools: read, map, find, list, modify, append, insert, delete, replace.

First shipped: `xml_read` -- resolve one address to one element and return
its exact source slice.

Reader rule: the XML toolkit bypasses `backend.read()` because that is
UTF-8-only and returns `str`, while expat needs bytes (BOM, byte offsets,
encoding declaration). We go through `backend.resolve_physical` then
`Path.read_bytes()`. `filter_check(path, "read")` is still called by
`Patcher` via `path_args`, so policy is honoured.
"""
from __future__ import annotations

from typing import Any

from ..core.backend import Backend
from ..core.models import Result
from ..xml.address import AddressError, parse_address
from ..xml.reader import XmlError, parse
from ..xml.resolver import ResolveError, resolve_one


def _xml_cfg(backend: Backend) -> dict | None:
    """Locate `Workspace.xml` through whatever wrapper chain backend is.

    MultiDomainBackend -> pairs -> fs sub-backend -> .ws -> .xml.
    MultiRootFsBackend -> .ws -> .xml.
    RootDirBackend -> None (tests, ad-hoc use).
    """
    seen: set[int] = set()
    cur: Any = backend
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        ws = getattr(cur, "ws", None)
        if ws is not None:
            return getattr(ws, "xml", None) or None
        pairs = getattr(cur, "_pairs", None)
        if pairs:
            for name, sub in pairs:
                if name == "fs":
                    cur = sub
                    break
            else:
                return None
            continue
        return None
    return None


def _read_bytes(backend: Backend, path: str) -> bytes:
    """Read raw bytes for path, bypassing the UTF-8-only backend.read()."""
    resolver = getattr(backend, "resolve_physical", None)
    if not callable(resolver):
        raise FileNotFoundError(
            f"backend {type(backend).__name__} has no resolve_physical"
        )
    phys = resolver(path)
    if phys is None:
        raise FileNotFoundError(path)
    return phys.read_bytes()


def _line_range(data: bytes, start: int, end: int) -> tuple[int, int]:
    """1-based (first_line, last_line) of bytes[start:end]."""
    first = data.count(b"\n", 0, start) + 1
    last = data.count(b"\n", 0, end) + 1
    return first, last


class XmlReadTool:
    name = "xml_read"
    op = "read"
    path_args: list[str] = ["file_path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any = None,
        file_path: str = "",
        address: str = "",
        occurrence: int | None = None,
        **_kwargs: Any,
    ) -> Result:
        if not file_path:
            return Result(
                status="error", action="xml_read",
                error_code="bad_input", message="file_path required",
            )
        if not address:
            return Result(
                status="error", action="xml_read",
                error_code="bad_input", message="address required",
            )
        if occurrence is not None:
            if not isinstance(occurrence, int) or occurrence < 1:
                return Result(
                    status="error", action="xml_read",
                    error_code="bad_occurrence",
                    message=f"occurrence must be a positive int, got {occurrence!r}",
                )

        try:
            segments = parse_address(address)
        except AddressError as e:
            return Result(
                status="error", action="xml_read",
                error_code="bad_address", message=str(e),
            )

        try:
            data = _read_bytes(backend, file_path)
        except FileNotFoundError:
            return Result(
                status="error", action="xml_read",
                error_code="not_found", message=f"file not found: {file_path}",
            )
        except Exception as e:
            return Result(
                status="error", action="xml_read",
                error_code="read_failed",
                message=f"{type(e).__name__}: {e}",
            )

        try:
            doc = parse(data)
        except XmlError as e:
            return Result(
                status="error", action="xml_read",
                error_code=e.code, message=e.message,
            )

        try:
            resolved = resolve_one(
                doc, segments, _xml_cfg(backend), occurrence=occurrence,
            )
        except ResolveError as e:
            return Result(
                status="error", action="xml_read",
                error_code=e.code, message=e.message,
            )

        el = resolved.element
        src = doc.source_bytes[el.start:el.end]
        try:
            text = src.decode(doc.encoding)
        except UnicodeDecodeError:
            text = src.decode("utf-8", errors="replace")

        first, last = _line_range(doc.source_bytes, el.start, el.end)
        header = f"{file_path}  <{el.tag}>  L{first}-L{last}  ({len(src)} B)"
        return Result(
            status="ok", action="xml_read",
            message=header + "\n\n" + text,
        )
