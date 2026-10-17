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
from ..xml.reader import is_mixed_content
from ..xml.writer import WriteError, remove_attr, replace_text, set_attr


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


# Directories at depth >= 3 from the starting `path` are grouped
# under their depth-2 ancestor to keep the output compact even on big
# trees. Depth-0 is the start itself, depth-1 immediate children, etc.
_MAP_MAX_SAMPLE = 5


class XmlModifyTool:
    """Atomic edits on a single XML element.

    `ops` is a list of operations, applied in order; all-or-nothing: any
    refusal (`has_children`, `attr_not_found`, `mixed_content_unsupported`,
    ...) aborts the whole patch and the file is left untouched.

    Supported ops:

      {"op": "set_attr", "name": "...", "value": "..."}
      {"op": "remove_attr", "name": "..."}
      {"op": "set_text", "value": "..."}     # leaf only, refuses children

    Not in v1 (Step 3.5): `set_annotation` (needs child-insertion logic),
    `append_child` (needs indentation), `replace_self` (uses xml_replace).
    """

    name = "xml_modify"
    op = "write"
    path_args: list[str] = ["file_path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any = None,
        file_path: str = "",
        address: str = "",
        ops: list | None = None,
        occurrence: int | None = None,
        **_kwargs: Any,
    ) -> Result:
        if not file_path:
            return Result(
                status="error", action="xml_modify",
                error_code="bad_input", message="file_path required",
            )
        if not address:
            return Result(
                status="error", action="xml_modify",
                error_code="bad_input", message="address required",
            )
        if not isinstance(ops, list) or not ops:
            return Result(
                status="error", action="xml_modify",
                error_code="bad_input", message="ops must be a non-empty list",
            )
        if occurrence is not None and (
            not isinstance(occurrence, int) or occurrence < 1
        ):
            return Result(
                status="error", action="xml_modify",
                error_code="bad_occurrence",
                message=f"occurrence must be a positive int, got {occurrence!r}",
            )

        # --- validate op shapes up front (all-or-nothing contract) -------
        for i, op_spec in enumerate(ops):
            bad = self._validate_op(i, op_spec)
            if bad is not None:
                return Result(
                    status="error", action="xml_modify",
                    error_code="bad_op", message=bad,
                )

        try:
            segments = parse_address(address)
        except AddressError as e:
            return Result(
                status="error", action="xml_modify",
                error_code="bad_address", message=str(e),
            )

        # --- read current bytes ------------------------------------------
        try:
            data = _read_bytes(backend, file_path)
        except FileNotFoundError:
            return Result(
                status="error", action="xml_modify",
                error_code="not_found", message=f"file not found: {file_path}",
            )
        except Exception as e:
            return Result(
                status="error", action="xml_modify",
                error_code="read_failed",
                message=f"{type(e).__name__}: {e}",
            )

        try:
            doc = parse(data)
        except XmlError as e:
            return Result(
                status="error", action="xml_modify",
                error_code=e.code, message=e.message,
            )
        if doc.has_entities:
            return Result(
                status="error", action="xml_modify",
                error_code="dtd_unsupported",
                message="DTD with <!ENTITY ...> declarations is not supported",
            )

        xml_cfg = _xml_cfg(backend)

        try:
            resolved = resolve_one(
                doc, segments, xml_cfg, occurrence=occurrence,
            )
        except ResolveError as e:
            return Result(
                status="error", action="xml_modify",
                error_code=e.code, message=e.message,
            )

        el = resolved.element

        # --- apply ops on bytes; iterate the editor ----------------------
        # After each op the tree is stale (byte offsets shift). For a small
        # number of ops, the simplest correct approach is: apply op, reparse,
        # re-resolve the address. It is slower but avoids offset drift and
        # is easy to reason about.
        current_bytes = data
        for i, op_spec in enumerate(ops):
            try:
                if op_spec["op"] == "set_attr":
                    current_bytes = set_attr(doc, el, op_spec["name"], op_spec["value"])
                elif op_spec["op"] == "remove_attr":
                    current_bytes = remove_attr(doc, el, op_spec["name"])
                elif op_spec["op"] == "set_text":
                    if is_mixed_content(el):
                        return Result(
                            status="error", action="xml_modify",
                            error_code="mixed_content_unsupported",
                            message=(
                                f"<{el.tag}> has mixed content; "
                                f"set_text is not safe, use xml_replace"
                            ),
                        )
                    current_bytes = replace_text(doc, el, op_spec["value"])
                else:  # pragma: no cover -- validate_op caught it
                    raise WriteError("bad_op", f"unknown op {op_spec['op']!r}")
            except WriteError as e:
                return Result(
                    status="error", action="xml_modify",
                    error_code=e.code, message=f"op[{i}]: {e.message}",
                )
            # Reparse + reresolve for the next op (offsets have moved).
            if i + 1 < len(ops):
                try:
                    doc = parse(current_bytes)
                    resolved = resolve_one(
                        doc, segments, xml_cfg, occurrence=occurrence,
                    )
                    el = resolved.element
                except (XmlError, ResolveError) as e:
                    return Result(
                        status="error", action="xml_modify",
                        error_code=getattr(e, "code", "result_parse_error"),
                        message=(
                            f"op[{i}]: after edit the address no longer "
                            f"resolves: {getattr(e, 'message', str(e))}"
                        ),
                    )

        # --- verify: new bytes are well-formed ---------------------------
        try:
            parse(current_bytes)
        except XmlError as e:
            return Result(
                status="error", action="xml_modify",
                error_code="result_syntax_error",
                message=f"resulting XML is not well-formed: {e.message}",
            )

        # --- write via backend write-bytes -------------------------------
        err = self._write_bytes(backend, file_path, current_bytes)
        if err is not None:
            return Result(
                status="error", action="xml_modify",
                error_code="write_failed",
                message=err,
            )

        delta = len(current_bytes) - len(data)
        return Result(
            status="ok", action="xml_modify",
            message=(
                f"{file_path}  <{el.tag}>  {len(ops)} op(s) applied  "
                f"({delta:+d} B)"
            ),
        )

    @staticmethod
    def _validate_op(i: int, spec: Any) -> str | None:
        if not isinstance(spec, dict):
            return f"op[{i}] must be a dict, got {type(spec).__name__}"
        kind = spec.get("op")
        if kind not in ("set_attr", "remove_attr", "set_text"):
            return f"op[{i}].op must be one of set_attr/remove_attr/set_text, got {kind!r}"
        if kind in ("set_attr", "remove_attr"):
            name = spec.get("name")
            if not isinstance(name, str) or not name:
                return f"op[{i}].name must be a non-empty string"
        if kind == "set_attr":
            if not isinstance(spec.get("value"), str):
                return f"op[{i}].value must be a string"
        if kind == "set_text":
            if not isinstance(spec.get("value"), str):
                return f"op[{i}].value must be a string"
        return None

    @staticmethod
    def _write_bytes(backend: Backend, path: str, data: bytes) -> str | None:
        resolver = getattr(backend, "resolve_physical", None)
        if not callable(resolver):
            return f"backend {type(backend).__name__} has no resolve_physical"
        phys = resolver(path)
        if phys is None:
            return f"cannot resolve physical path: {path}"
        try:
            phys.parent.mkdir(parents=True, exist_ok=True)
            phys.write_bytes(data)
        except OSError as e:
            return f"write failed: {type(e).__name__}: {e}"
        return None


class XmlMapTool:
    """Directory map: file counts and top-N child tags per directory.

    Walks `path/*.xml`, parses each, aggregates (directory -> tag -> count).
    Output is a compact tree with one line per directory:

        Mods/MyMod/Defs/               12 files   ThingDef(234)  RecipeDef(89)
          Items/                       12 files   ThingDef(156)
          Recipes/                      9 files   RecipeDef(89)

    Sample of up to `_MAP_MAX_SAMPLE` names per top tag uses the discriminator
    chain; without one, prints `<tag>[N]`.

    Scope: `path` required; `max_files` caps parse work (default 2000);
    `max_tags` caps tags shown per line (default 5); `depth` groups deeper
    directories under an ancestor.
    """

    name = "xml_map"
    op = "read"
    path_args: list[str] = ["path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any = None,
        path: str = "",
        max_files: int = 2000,
        max_tags: int = 5,
        depth: int = 2,
        **_kwargs: Any,
    ) -> Result:
        if not path:
            return Result(
                status="error", action="xml_map",
                error_code="bad_input", message="path required",
            )
        try:
            max_files = int(max_files)
            max_tags = int(max_tags)
            depth = int(depth)
        except (TypeError, ValueError):
            return Result(
                status="error", action="xml_map",
                error_code="bad_options",
                message="max_files / max_tags / depth must be ints",
            )
        if max_files < 1 or max_tags < 1 or depth < 0:
            return Result(
                status="error", action="xml_map",
                error_code="bad_options",
                message="max_files/max_tags must be >= 1; depth >= 0",
            )

        try:
            st = backend.stat(path)
        except FileNotFoundError:
            return Result(
                status="error", action="xml_map",
                error_code="not_found", message=f"path not found: {path}",
            )
        if st.is_file:
            return Result(
                status="error", action="xml_map",
                error_code="bad_input",
                message=f"path must be a directory, got a file: {path}",
            )
        try:
            all_files = backend.list(path, "*.xml")
        except FileNotFoundError:
            return Result(
                status="error", action="xml_map",
                error_code="not_found", message=f"path not found: {path}",
            )
        if not all_files:
            return Result(
                status="ok", action="xml_map",
                message=f"no .xml files under {path}",
            )
        if len(all_files) > max_files:
            return Result(
                status="error", action="xml_map",
                error_code="too_many_files",
                message=(
                    f"{len(all_files)} xml files under {path}; "
                    f"narrow path or raise max_files (now {max_files})"
                ),
            )

        path_prefix = path.rstrip("/")
        prefix_len = len(path_prefix) + 1 if path_prefix else 0

        # dir_key -> {tag -> count}; dir_key -> {tag -> [names]}
        tag_counts: dict[str, dict[str, int]] = {}
        tag_samples: dict[str, dict[str, list[str]]] = {}
        file_count: dict[str, int] = {}

        xml_cfg = _xml_cfg(backend)
        unparsed = 0

        for fpath in all_files:
            # Directory key relative to `path`.
            rel = fpath[prefix_len:] if prefix_len else fpath
            # Split off the file component.
            slash = rel.rfind("/")
            if slash < 0:
                dir_rel = ""
            else:
                dir_rel = rel[:slash]
            dir_key = self._group_dir(dir_rel, depth)
            file_count[dir_key] = file_count.get(dir_key, 0) + 1

            try:
                data = _read_bytes(backend, fpath)
                doc = parse(data)
            except (XmlError, OSError, FileNotFoundError):
                unparsed += 1
                continue

            counts = tag_counts.setdefault(dir_key, {})
            samples = tag_samples.setdefault(dir_key, {})
            # Only direct children of root: those are the Def/Operation
            # elements the user cares about. Descendants (defName, label,
            # verbProperties) are noise at the map level -- see §5.1.
            root_tag_path = [doc.root.tag]
            for el in doc.root.children:
                counts[el.tag] = counts.get(el.tag, 0) + 1
                lst = samples.setdefault(el.tag, [])
                if len(lst) < _MAP_MAX_SAMPLE:
                    chain = chain_for(root_tag_path + [el.tag], xml_cfg)
                    name = match_value(el, chain)
                    if name is not None:
                        lst.append(name)

        lines = [f"=== xml_map: {path} ({len(all_files)} files, {len(file_count)} dirs) ==="]
        for dir_key in sorted(file_count):
            n = file_count[dir_key]
            counts = tag_counts.get(dir_key, {})
            if counts:
                ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
                shown = ordered[:max_tags]
                rest = len(ordered) - len(shown)
                parts: list[str] = []
                for tag, c in shown:
                    sample = tag_samples.get(dir_key, {}).get(tag, [])
                    if sample:
                        s = ", ".join(sample[:3])
                        if c > len(sample):
                            s += f", +{c - len(sample)}"
                        parts.append(f"{tag}({c}: {s})")
                    else:
                        parts.append(f"{tag}({c})")
                if rest > 0:
                    parts.append(f"+{rest} more tags")
                tags_str = "  ".join(parts)
            else:
                tags_str = "(no xml content parsed)"
            label = dir_key or "."
            lines.append(f"  {label:<30} {n:>4} files  {tags_str}")
        if unparsed:
            lines.append(f"  ... ({unparsed} unparseable file(s) skipped)")
        return Result(status="ok", action="xml_map", message="\n".join(lines))

    @staticmethod
    def _group_dir(dir_rel: str, depth: int) -> str:
        """Group a directory path to at most `depth` path segments.

        Empty `dir_rel` -> "" (files directly under the start path).
        "A" -> "A". "A/B/C" with depth=2 -> "A/B".
        "A/B" with depth=0 -> "" (everything collapses to root).
        """
        if not dir_rel:
            return ""
        if depth == 0:
            return ""
        parts = dir_rel.split("/")
        return "/".join(parts[:depth])


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
