"""Python code format — AST-based symbol extraction.

Unlike the markdown Format, CodeFormat has no configurable syntax.
Python's ast module is the source of truth. The entry point is
`parse_module(text, path) -> Module`, which flattens the AST into a
list of Symbol entries in source order.

Covered node types:
    FunctionDef, AsyncFunctionDef, ClassDef

Not covered in MVP:
    lambdas, class-level attribute assignments, nested comprehensions,
    cross-module reference resolution.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from ..core.models import Module, Symbol
from .hashing import content_hash


DOCSTRING_MAX = 200
HASH_MODULO = 2147483647


@dataclass
class CodeFormat:
    """Stateless AST parser. No presets, no overrides."""

    @classmethod
    def load(cls) -> "CodeFormat":
        return cls()

    def parse(self, text: str, path: str = "") -> Module:
        return parse_module(text, path)


# --- public ---------------------------------------------------------------


def parse_module(text: str, path: str = "") -> Module:
    tree = ast.parse(text)
    data = text.encode("utf-8")
    h, n = source_hash(text)
    c_hash = content_hash(data)
    symbols: list[Symbol] = []
    imports: list[str] = []
    imported_modules: list[str] = []
    calls: list[dict] = []
    import_bindings: list[dict] = []

    _walk_body(tree.body, parent=None, in_class=False,
               symbols=symbols, imports=imports,
               imported_modules=imported_modules, source=text,
               calls=calls, import_bindings=import_bindings)

    # Sort by position for stable output.
    symbols.sort(key=lambda s: (s.line_start, s.line_end))

    return Module(
        path=path,
        source=text,
        source_hash=h,
        source_len=n,
        content_hash=c_hash,
        symbols=symbols,
        imports=imports,
        imported_modules=imported_modules,
        calls=calls,
        import_bindings=import_bindings,
        suppress=_parse_suppress(text),
        has_main=_has_main(tree),
    )


def _has_main(tree) -> bool:
    """True if module has `if __name__ == "__main__":` at top level.

    Fact from AST, not a judgement: we look for an `if` whose test is
    `__name__ == "__main__"` (any string literal `__main__`). Common
    variants (`!=`, `not in`) are ignored — this marker is deliberately
    narrow.
    """
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not isinstance(test, ast.Compare):
            continue
        if not (isinstance(test.left, ast.Name) and test.left.id == "__name__"):
            continue
        if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
            continue
        if len(test.comparators) != 1:
            continue
        right = test.comparators[0]
        if isinstance(right, ast.Constant) and right.value == "__main__":
            return True
    return False


_SUPPRESS_RE = re.compile(r"^#\s*pa:\s*(.+?)\s*$")
_SUPPRESS_HEAD_LINES = 20


def _parse_suppress(text: str) -> frozenset[str]:
    """Parse `# pa: no-users, no-large` directives from the file head.

    Only the first _SUPPRESS_HEAD_LINES lines are scanned: directives
    belong near the top of the file, next to the module docstring and
    imports. Multiple lines merge. Marker names match the tokens the
    renderer emits (minus the `⚠`/`◉` glyph).
    """
    if not text:
        return frozenset()
    names: set[str] = set()
    for i, line in enumerate(text.splitlines()):
        if i >= _SUPPRESS_HEAD_LINES:
            break
        m = _SUPPRESS_RE.match(line)
        if not m:
            continue
        for token in m.group(1).split(","):
            token = token.strip()
            if token:
                names.add(token)
    return frozenset(names)


def source_hash(source: str) -> tuple[int, int]:
    """Polynomial hash over the whole source; matches Lua-side impl.

    Returns (hash, length_bytes). Empty input -> (17, 0).
    """
    data = source.encode("utf-8")
    h = 17
    for b in data:
        h = (h * 31 + b) % HASH_MODULO
    return h, len(data)


# --- internal -------------------------------------------------------------


def _walk_body(nodes, parent, in_class, symbols, imports,
               imported_modules=None, source=None,
               calls=None, import_bindings=None):
    if imported_modules is None:
        imported_modules = []
    if calls is None:
        calls = []
    if import_bindings is None:
        import_bindings = []
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
                imported_modules.append(alias.name)
                import_bindings.append({
                    "local": alias.asname or alias.name,
                    "dotted": alias.name,
                    "attr": None,
                })
            continue
        if isinstance(node, ast.ImportFrom):
            base = ("." * (node.level or 0)) + (node.module or "")
            if node.module is None:
                # `from . import a` / `from .. import b`: each alias names a
                # submodule of the base package (convention), not an attribute.
                for alias in node.names:
                    full = (base + alias.name) if base else alias.name
                    imports.append(full)
                    imported_modules.append(full)
                    import_bindings.append({
                        "local": alias.asname or alias.name,
                        "dotted": full,
                        "attr": None,
                    })
            else:
                imported_modules.append(base)
                for alias in node.names:
                    imports.append(f"{base}.{alias.name}" if base else alias.name)
                    import_bindings.append({
                        "local": alias.asname or alias.name,
                        "dotted": base,
                        "attr": alias.name,
                    })
            continue

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sym = _make_function_symbol(node, parent, in_class, source)
            symbols.append(sym)
            _walk_body(node.body, parent=sym.qualname, in_class=False,
                       symbols=symbols, imports=imports,
                       imported_modules=imported_modules, source=source,
                       calls=calls, import_bindings=import_bindings)
            continue

        if isinstance(node, ast.ClassDef):
            sym = _make_class_symbol(node, parent, source)
            symbols.append(sym)
            _walk_body(node.body, parent=sym.qualname, in_class=True,
                       symbols=symbols, imports=imports,
                       imported_modules=imported_modules, source=source,
                       calls=calls, import_bindings=import_bindings)
            continue

        if isinstance(node, ast.Call):
            try:
                target_text = ast.unparse(node.func)
            except Exception:
                target_text = ""
            if target_text:
                calls.append({
                    "caller": parent or "<module>",
                    "line": node.lineno,
                    "target_text": target_text,
                })
            # Recurse into children so nested calls (foo(bar())) are caught.
            for child in ast.iter_child_nodes(node):
                _walk_body([child], parent=parent, in_class=in_class,
                           symbols=symbols, imports=imports,
                           imported_modules=imported_modules, source=source,
                           calls=calls, import_bindings=import_bindings)
            continue

        # Other statements / expressions: recurse into all children so
        # Call nodes buried in expressions (assignments, if/with bodies,
        # comprehensions) get visited. Symbol discovery is unaffected —
        # only the branches above add symbols.
        for child in ast.iter_child_nodes(node):
            _walk_body([child], parent=parent, in_class=in_class,
                       symbols=symbols, imports=imports,
                       imported_modules=imported_modules, source=source,
                       calls=calls, import_bindings=import_bindings)


def _make_function_symbol(node, parent, in_class, source=None) -> Symbol:
    is_async = isinstance(node, ast.AsyncFunctionDef)
    if in_class:
        kind = "async_method" if is_async else "method"
    else:
        kind = "async_function" if is_async else "function"

    qualname = f"{parent}.{node.name}" if parent else node.name
    line_start = _definition_start_line(node)

    return Symbol(
        name=node.name,
        qualname=qualname,
        kind=kind,
        line_start=line_start,
        line_end=node.end_lineno or node.lineno,
        signature=_function_signature(node),
        docstring=_clean_docstring(ast.get_docstring(node, clean=True)),
        decorators=_decorators(node),
        parent=parent,
        source_hash=_symbol_hash(node, source),
    )


def _make_class_symbol(node, parent, source=None) -> Symbol:
    qualname = f"{parent}.{node.name}" if parent else node.name
    line_start = _definition_start_line(node)

    bases = [ast.unparse(b) for b in node.bases]
    sig = f"class {node.name}"
    if bases:
        sig += f"({', '.join(bases)})"

    return Symbol(
        name=node.name,
        qualname=qualname,
        kind="class",
        line_start=line_start,
        line_end=node.end_lineno or node.lineno,
        signature=sig,
        docstring=_clean_docstring(ast.get_docstring(node, clean=True)),
        decorators=_decorators(node),
        parent=parent,
        source_hash=_symbol_hash(node, source),
    )


def _symbol_hash(node, source: str | None) -> int | None:
    """Hash of a symbol's source slice (same polynomial as module hash).

    Returns None when source is unavailable (foreign callers). The slice is
    taken via ast.get_source_segment, so it reflects exactly what is in the
    file, not a re-rendered version.
    """
    if not source:
        return None
    try:
        seg = ast.get_source_segment(source, node)
    except Exception:
        return None
    if seg is None:
        return None
    h, _ = source_hash(seg)
    return h


def _definition_start_line(node) -> int:
    """Include decorators in the reported start line."""
    if getattr(node, "decorator_list", None):
        return node.decorator_list[0].lineno
    return node.lineno


def _decorators(node) -> list[str]:
    out: list[str] = []
    for d in getattr(node, "decorator_list", []):
        try:
            out.append(ast.unparse(d))
        except Exception:
            out.append("?")
    return out


def _function_signature(node) -> str:
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    try:
        args_str = ast.unparse(node.args)
    except Exception:
        args_str = ""
    if not args_str.startswith("("):
        args_str = f"({args_str})"
    sig = f"{prefix} {node.name}{args_str}"
    if node.returns is not None:
        try:
            sig += f" -> {ast.unparse(node.returns)}"
        except Exception:
            pass
    return sig


def _clean_docstring(doc: str | None) -> str | None:
    if not doc:
        return None
    doc = doc.strip()
    if not doc:
        return None
    first_line = doc.splitlines()[0].strip()
    if len(first_line) > DOCSTRING_MAX:
        first_line = first_line[:DOCSTRING_MAX - 3] + "..."
    return first_line
