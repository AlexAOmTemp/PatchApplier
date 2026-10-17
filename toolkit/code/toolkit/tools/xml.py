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
from ..xml.discriminator import chain_for, match_value


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


def _walk(el, tag_path):
    """Pre-order walk yielding (element, tag_path).

    `tag_path` includes the element's own tag. Root is called with
    `tag_path=[root.tag]`.
    """
    yield el, tag_path
    for ch in el.children:
        yield from _walk(ch, tag_path + [ch.tag])


def _glob_match(value: str, pattern: str) -> bool:
    """Glob match: only `*` and `?` are special; everything else is literal.

    Deliberately simpler than fnmatch: no `[seq]` character classes, because
    XML values occasionally contain `[` (e.g. defNames in some games) and
    silent class-matching surprises are worse than the missing feature.
    """
    import re
    parts: list[str] = []
    for c in pattern:
        if c == "*":
            parts.append(".*")
        elif c == "?":
            parts.append(".")
        else:
            parts.append(re.escape(c))
    try:
        return re.fullmatch("".join(parts), value) is not None
    except re.error:
        return False


def _matches_where(el, where: dict) -> bool:
    """True iff every key/value in `where` matches `el`.

    Key `@attr` -> attribute value match.
    Key `name`  -> first child element with that tag has matching text.
    Value is a glob (only * and ? special) or exact string.
    """
    for key, pattern in where.items():
        if key.startswith("@"):
            attr = key[1:]
            if not attr:
                return False
            val = el.attrib.get(attr)
            if val is None:
                return False
            if not _glob_match(val, pattern):
                return False
        else:
            child_text = None
            for ch in el.children:
                if ch.tag == key:
                    child_text = ch.text or ""
                    break
            if child_text is None:
                return False
            if not _glob_match(child_text, pattern):
                return False
    return True


class XmlFindTool:
    """Schema-aware search: find every element of `tag` under `path` whose
    `where` matches (child text or @attr).

    Unlike `grep`, this does not search inside `<description>` / `<label>`
    text or comments. It walks the parsed tree and matches element structure.

    Scope is enforced: `path` is required, `max_files` caps the walk, and a
    too-broad scope fails fast with a suggestion to narrow it. On RimWorld
    the workspace contains 17k XML files — scanning all of them on a typo is
    not a good default.
    """

    name = "xml_find"
    op = "read"
    path_args: list[str] = ["path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any = None,
        path: str = "",
        tag: str = "",
        where: dict | None = None,
        max_files: int = 1000,
        max_results: int = 200,
        **_kwargs: Any,
    ) -> Result:
        if not path:
            return Result(
                status="error", action="xml_find",
                error_code="bad_input", message="path required",
            )
        if not tag:
            return Result(
                status="error", action="xml_find",
                error_code="bad_input", message="tag required",
            )
        if where is None:
            where = {}
        if not isinstance(where, dict):
            return Result(
                status="error", action="xml_find",
                error_code="bad_input",
                message=f"where must be a dict, got {type(where).__name__}",
            )
        for k, v in where.items():
            if not isinstance(k, str) or not k:
                return Result(
                    status="error", action="xml_find",
                    error_code="bad_input",
                    message=f"where keys must be non-empty strings, got {k!r}",
                )
            if not isinstance(v, str):
                return Result(
                    status="error", action="xml_find",
                    error_code="bad_input",
                    message=f"where[{k!r}] must be a string, got {type(v).__name__}",
                )
        try:
            max_files = int(max_files)
            max_results = int(max_results)
        except (TypeError, ValueError):
            return Result(
                status="error", action="xml_find",
                error_code="bad_options",
                message="max_files and max_results must be ints",
            )
        if max_files < 1 or max_results < 1:
            return Result(
                status="error", action="xml_find",
                error_code="bad_options",
                message="max_files and max_results must be >= 1",
            )

        # Collect target files.
        try:
            st = backend.stat(path)
        except FileNotFoundError:
            return Result(
                status="error", action="xml_find",
                error_code="not_found", message=f"path not found: {path}",
            )
        if st.is_file:
            if not path.lower().endswith(".xml"):
                return Result(
                    status="error", action="xml_find",
                    error_code="not_xml", message=f"not an .xml file: {path}",
                )
            files = [path]
        else:
            try:
                listed = backend.list(path, "*.xml")
            except FileNotFoundError:
                return Result(
                    status="error", action="xml_find",
                    error_code="not_found", message=f"path not found: {path}",
                )
            files = list(listed)
            if len(files) > max_files:
                return Result(
                    status="error", action="xml_find",
                    error_code="too_many_files",
                    message=(
                        f"{len(files)} xml files under {path}; "
                        f"narrow path or raise max_files (now {max_files})"
                    ),
                )

        xml_cfg = _xml_cfg(backend)
        matches: list[tuple[str, Any, int, int, list[str]]] = []
        files_parsed = 0
        files_failed = 0
        files_with_matches: set[str] = set()
        truncated = False

        for fpath in files:
            try:
                data = _read_bytes(backend, fpath)
            except Exception:
                files_failed += 1
                continue
            try:
                doc = parse(data)
            except XmlError:
                files_failed += 1
                continue
            files_parsed += 1
            for el, tag_path in _walk(doc.root, [doc.root.tag]):
                if el.tag != tag:
                    continue
                if where and not _matches_where(el, where):
                    continue
                l1 = doc.source_bytes.count(b"\n", 0, el.start) + 1
                l2 = doc.source_bytes.count(b"\n", 0, el.end) + 1
                matches.append((fpath, el, l1, l2, tag_path))
                files_with_matches.add(fpath)
                if len(matches) > max_results:
                    truncated = True
                    break
            if truncated:
                break

        if truncated:
            matches = matches[:max_results]

        if not matches:
            scanned = len(files)
            extra = f", {files_failed} unreadable" if files_failed else ""
            return Result(
                status="ok", action="xml_find",
                message=f"no matches ({scanned} files scanned{extra})",
            )

        lines = [
            f"{len(matches)} matches in {len(files_with_matches)} files:"
        ]
        for fpath, el, l1, l2, tag_path in matches:
            chain = chain_for(tag_path, xml_cfg)
            disc = match_value(el, chain)
            label = f"<{tag}>[{disc}]" if disc else f"<{tag}>"
            lines.append(f"  {fpath}  {label}  L{l1}-L{l2}")
        if truncated:
            lines.append(f"... (truncated to {max_results})")
        if files_failed:
            lines.append(f"... ({files_failed} unparseable file(s) skipped)")
        return Result(
            status="ok", action="xml_find",
            message="\n".join(lines),
        )


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
