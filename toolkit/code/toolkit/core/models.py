"""Core data models.

Frozen contract — changes here break every Tool and Backend.
Keep this module free of I/O, dependencies, and side effects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ResultStatus = Literal["ok", "error", "skipped", "blocked"]
ToolOp = Literal["read", "write", "index_docs", "index_py", "index_lua", "index_cs"]


@dataclass
class Section:
    """A single heading-delimited block of a markdown document.

    Offsets (heading_start, heading_end, body_start, body_end) are byte positions
    in the source text. children holds nested subsections (### under ##, etc.).

    `body_hash` is sha1 of the section's own body (excluding child subsections,
    normalized). `summary_hash` is sha1 of the summary text, or "" if absent.
    `stale` is set by `build_index` when the summary was last changed before
    the body.
    """
    level: int
    number: str | None
    title: str
    heading_start: int
    heading_end: int
    summary: str | None = None
    tags: list[str] = field(default_factory=list)
    large_ok: bool = False
    flat_scope: bool = False
    body_start: int = 0
    body_end: int = 0
    children: list[Section] = field(default_factory=list)
    body_hash: str = ""
    summary_hash: str = ""
    stale: bool = False
    suppress: frozenset[str] = field(default_factory=frozenset)


@dataclass
class Delta:
    """Line/byte/occurrence change produced by a write operation."""
    lines: int = 0
    bytes: int = 0
    occurrences: int = 1


@dataclass
class Result:
    """Structured result of a single Tool invocation.

    status: ok | error | skipped | blocked
        blocked is for sandbox/whitelist rejections — distinct from error.
    delta: only for write operations. None for reads.
    verified: True/False for write operations that did read-after-write check.
             None for reads and for backends that don't verify.
    error_code: machine-readable tag ("not_found", "no_op", "sandbox", ...).
    """
    status: ResultStatus
    message: str
    delta: Delta | None = None
    verified: bool | None = None
    error_code: str | None = None
    action: str | None = None
    # Label from the patch's `id` field. Any JSON scalar or string the LLM
    # supplied; None when the action had no `id`. Used only for display.
    id_label: str | None = None


@dataclass
class FileStat:
    """File metadata returned by Backend.stat()."""
    size_bytes: int
    lines: int
    mtime: float
    is_file: bool = True


@dataclass
class Symbol:
    """A Python named code entity extracted from an AST.

    Covers top-level functions, async functions, classes, methods, and
    nested functions/classes. line_start is 1-based inclusive and includes
    any decorators attached to the definition. line_end is the last line of
    the body (ast.end_lineno).

    qualname uses dotted form: "function", "Class", "Class.method",
    "outer.inner" for nested. `parent` is the qualname of the enclosing
    definition, or None for top-level symbols.
    """
    name: str
    qualname: str
    kind: str          # function | async_function | method | async_method | class
    line_start: int
    line_end: int
    signature: str
    docstring: str | None = None
    decorators: list[str] = field(default_factory=list)
    parent: str | None = None
    # Hash of the symbol's source slice (signature + body), same polynomial
    # as module-level source_hash. Used by CODE_INDEX diff to detect body
    # edits that do not shift line ranges. None for legacy/foreign sources.
    source_hash: int | None = None

    def is_class(self) -> bool:
        return self.kind == "class"


@dataclass
class Module:
    """A parsed Python source file: symbols + imports + source metadata.

    source_hash is a lightweight polynomial over the full source; the same
    algorithm is used in the Lua-side code_index_regen so that a hash
    mismatch between Python and Studio is directly comparable.
    content_hash is blake2b-8 over full source bytes; used only for
    duplicate detection across the tree (0 = not computed).
    """
    path: str
    source: str
    source_hash: int
    source_len: int
    content_hash: int = 0
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    imported_modules: list[str] = field(default_factory=list)
    # Line count when source is empty (Lua-side index). 0 means "fall back
    # to counting newlines from source".
    lines: int = 0
    # Marker names to suppress for this module (parsed from `# pa: ...`
    # directives in the file head). Empty = show all markers. See
    # formats/code.py:_parse_suppress.
    suppress: frozenset[str] = field(default_factory=frozenset)
    # True if module has an `if __name__ == "__main__":` guard. Fact from
    # AST; rendered as `◉` in the index. Lua-side has no equivalent and
    # leaves this False.
    has_main: bool = False

    # Call edges extracted from the AST during parse. Each entry is the
    # raw text of the call's `func` expression plus the qualname of the
    # symbol that contains the call:
    #     {"caller": qualname | "<module>", "line": int,
    #      "target_text": str}
    # Resolution to a qualified target happens in indexers/code.py;
    # the field here is deliberately unresolved (raw text, exactly as
    # written in source).
    calls: list[dict] = field(default_factory=list)
    # Import bindings with local aliases. Parallel to `imports`; the
    # module-level import graph still uses `imports`, this exists for
    # symbol-level call resolution. Each entry:
    #     {"local": name_used_in_code, "dotted": module_dotted,
    #      "attr": attr_or_None}
    #     import X            -> {"local": "X", "dotted": "X",   "attr": None}
    #     import X as Y       -> {"local": "Y", "dotted": "X",   "attr": None}
    #     from X import Y     -> {"local": "Y", "dotted": "X",   "attr": "Y"}
    #     from X import Y as Z-> {"local": "Z", "dotted": "X",   "attr": "Y"}
    import_bindings: list[dict] = field(default_factory=list)

    def find(self, qualname: str) -> Symbol | None:
        for s in self.symbols:
            if s.qualname == qualname:
                return s
        return None
