"""Core data models.

Frozen contract — changes here break every Tool and Backend.
Keep this module free of I/O, dependencies, and side effects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ResultStatus = Literal["ok", "error", "skipped", "blocked"]
FilterMode = Literal["none", "white", "black"]
ToolOp = Literal["read", "write", "index"]


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
class FilterSpec:
    """Per-role path policy with inheritance.

    `overrides` maps relative directory paths to explicit allow/deny:
      True  = explicitly allowed
      False = explicitly denied

    Paths not present inherit the nearest ancestor's override, falling
    back to default allow at root. A file uses the policy of its
    containing directory.

    Legacy white/black modes are supported via `from_legacy` and are
    translated into the same override dict:
      white + paths  ->  {".": False, **{p: True for p in paths}}
      black + paths  ->  {**{p: False for p in paths}}
    """
    overrides: dict = field(default_factory=dict)

    def resolve(self, path: str) -> bool:
        """True if `path` (relative, e.g. 'toolkit/x.py') is allowed."""
        if not self.overrides:
            return True
        norm = path.replace("\\", "/")
        if norm in self.overrides:
            return self.overrides[norm]
        parts = norm.split("/")
        for i in range(len(parts) - 1, 0, -1):
            prefix = "/".join(parts[:i])
            if prefix in self.overrides:
                return self.overrides[prefix]
        if "." in self.overrides:
            return self.overrides["."]
        return True

    def is_active(self) -> bool:
        return bool(self.overrides)

    @classmethod
    def from_legacy(cls, mode: str = "none", paths: list | None = None) -> "FilterSpec":
        if mode == "none" or not paths:
            return cls()
        norm_paths = [str(p).replace("\\", "/").strip("/") for p in paths if p]
        norm_paths = [p for p in norm_paths if p]
        if not norm_paths:
            return cls()
        if mode == "white":
            ov = {".": False}
            for p in norm_paths:
                ov[p] = True
            return cls(overrides=ov)
        if mode == "black":
            ov = {}
            for p in norm_paths:
                ov[p] = False
            return cls(overrides=ov)
        return cls()

    @classmethod
    def from_dict(cls, data) -> "FilterSpec":
        if not isinstance(data, dict):
            return cls()
        if "overrides" in data:
            ov_raw = data.get("overrides") or {}
            ov = {str(k): bool(v) for k, v in ov_raw.items()}
            return cls(overrides=ov)
        mode = data.get("mode", "none")
        paths = list(data.get("paths", []) or [])
        return cls.from_legacy(mode, paths)

    def to_dict(self) -> dict:
        return {"overrides": dict(self.overrides)}


@dataclass
class Policy:
    """Three independent FilterSpecs, one per operation role.

    A Tool declares its role via the `op` attribute (default "write").
    Backends receive a single FilterSpec via Policy.for_op.
    """
    read: FilterSpec = field(default_factory=FilterSpec)
    write: FilterSpec = field(default_factory=FilterSpec)
    index: FilterSpec = field(default_factory=FilterSpec)

    @classmethod
    def uniform(cls, mode: str = "none", paths: list | None = None) -> "Policy":
        """Legacy: same rule for all three roles."""
        spec = FilterSpec.from_legacy(mode, list(paths or []))
        return cls(read=spec, write=spec, index=spec)

    @classmethod
    def from_dict(cls, data) -> "Policy":
        """Accept three shapes:
          - new per-op: {"read": {"overrides": {...}}, "write": {...}, "index": {...}}
          - legacy per-op: {"read": {"mode": "white", "paths": [...]}, ...}
          - legacy flat: {"mode": "white", "paths": [...]}
        """
        if not data or not isinstance(data, dict):
            return cls()
        if any(k in data for k in ("read", "write", "index")):
            return cls(
                read=FilterSpec.from_dict(data.get("read")),
                write=FilterSpec.from_dict(data.get("write")),
                index=FilterSpec.from_dict(data.get("index")),
            )
        spec = FilterSpec.from_dict(data)
        return cls(read=spec, write=spec, index=spec)

    def for_op(self, op: str) -> FilterSpec:
        if op == "read":
            return self.read
        if op == "index":
            return self.index
        return self.write

    def to_dict(self) -> dict:
        return {
            "read": self.read.to_dict(),
            "write": self.write.to_dict(),
            "index": self.index.to_dict(),
        }


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

    source_hash is a lightweight polynomial over the first 2048 bytes;
    the same algorithm is used in the Lua-side code_index_regen so that
    a hash mismatch between Python and Studio is directly comparable.
    """
    path: str
    source: str
    source_hash: int
    source_len: int
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
