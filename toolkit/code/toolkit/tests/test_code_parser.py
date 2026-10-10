"""Unit tests for formats.code (AST parser)."""
from __future__ import annotations

import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent

sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.formats import CodeFormat, parse_module, source_hash


PASS = "[OK]  "
FAIL = "[FAIL]"


class T:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def expect(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"{PASS} {label}")
            self.passed += 1
        else:
            print(f"{FAIL} {label}" + (f" -- {detail}" if detail else ""))
            self.failed += 1


def _by_qualname(module, qualname: str):
    return module.find(qualname)


SIMPLE = '''\
"""Module docstring."""
import os
from pathlib import Path


def greet(name: str) -> str:
    """Say hi."""
    return f"hi {name}"


async def fetch(url: str) -> bytes:
    return b""


class Service:
    """A service."""

    def __init__(self, name: str):
        self.name = name

    @staticmethod
    def make() -> "Service":
        return Service("x")

    async def run(self) -> None:
        pass
'''


DECORATED = '''\
@decorator
@another(arg=1)
def f():
    pass


class Outer:
    @classmethod
    def cm(cls):
        pass

    class Inner:
        def im(self):
            pass
'''


NESTED = '''\
def outer():
    def inner():
        pass
    return inner
'''


def main():
    t = T()
    fmt = CodeFormat.load()

    # --- simple module ---
    print("== simple module ==")
    m = fmt.parse(SIMPLE, path="simple.py")
    t.expect("has 5 symbols (greet, fetch, Service, __init__, make, run)?",
             len(m.symbols) == 6, f"got {len(m.symbols)}: {[s.qualname for s in m.symbols]}")

    greet = _by_qualname(m, "greet")
    t.expect("greet found", greet is not None)
    t.expect("greet kind == function", greet and greet.kind == "function",
             greet and greet.kind)
    t.expect("greet signature", greet and greet.signature == "def greet(name: str) -> str",
             greet and greet.signature)
    t.expect("greet docstring", greet and greet.docstring == "Say hi.",
             greet and greet.docstring)
    t.expect("greet line_start", greet and greet.line_start == 6, greet and greet.line_start)

    fetch = _by_qualname(m, "fetch")
    t.expect("fetch kind == async_function", fetch and fetch.kind == "async_function",
             fetch and fetch.kind)
    t.expect("fetch signature prefix", fetch and fetch.signature.startswith("async def fetch"),
             fetch and fetch.signature)

    svc = _by_qualname(m, "Service")
    t.expect("Service found", svc is not None)
    t.expect("Service kind == class", svc and svc.kind == "class")
    t.expect("Service docstring", svc and svc.docstring == "A service.")

    init = _by_qualname(m, "Service.__init__")
    t.expect("__init__ found", init is not None)
    t.expect("__init__ kind == method", init and init.kind == "method")
    t.expect("__init__ parent == Service", init and init.parent == "Service")

    mk = _by_qualname(m, "Service.make")
    t.expect("make found", mk is not None)
    t.expect("make has @staticmethod", mk and "staticmethod" in mk.decorators,
             mk and mk.decorators)

    run = _by_qualname(m, "Service.run")
    t.expect("run kind == async_method", run and run.kind == "async_method",
             run and run.kind)

    # --- imports ---
    print()
    print("== imports ==")
    t.expect("import os captured", "os" in m.imports, m.imports)
    t.expect("from pathlib import Path captured",
             "pathlib.Path" in m.imports, m.imports)

    # --- decorators on definitions ---
    print()
    print("== decorated ==")
    m2 = fmt.parse(DECORATED, path="dec.py")
    f = _by_qualname(m2, "f")
    t.expect("f has 2 decorators", f and len(f.decorators) == 2, f and f.decorators)
    t.expect("f line_start includes decorator", f and f.line_start == 1,
             f and f.line_start)
    t.expect("f qualname preserved", f is not None)

    cm = _by_qualname(m2, "Outer.cm")
    t.expect("Outer.cm has @classmethod", cm and "classmethod" in cm.decorators,
             cm and cm.decorators)

    inner = _by_qualname(m2, "Outer.Inner")
    t.expect("Outer.Inner kind == class", inner and inner.kind == "class")
    t.expect("Outer.Inner parent == Outer", inner and inner.parent == "Outer")

    im = _by_qualname(m2, "Outer.Inner.im")
    t.expect("Outer.Inner.im kind == method", im and im.kind == "method")
    t.expect("Outer.Inner.im parent == Outer.Inner",
             im and im.parent == "Outer.Inner", im and im.parent)

    # --- nested functions ---
    print()
    print("== nested functions ==")
    m3 = fmt.parse(NESTED, path="nested.py")
    outer = _by_qualname(m3, "outer")
    inner = _by_qualname(m3, "outer.inner")
    t.expect("outer found", outer is not None)
    t.expect("outer.inner found", inner is not None,
             [s.qualname for s in m3.symbols])
    t.expect("outer.inner parent == outer", inner and inner.parent == "outer")

    # --- empty module ---
    print()
    print("== empty module ==")
    m4 = fmt.parse("", path="empty.py")
    t.expect("no symbols", len(m4.symbols) == 0)
    t.expect("no imports", len(m4.imports) == 0)
    t.expect("source_len == 0", m4.source_len == 0)

    # --- syntax error ---
    print()
    print("== syntax error ==")
    try:
        fmt.parse("def broken(:\n    pass\n", path="broken.py")
        t.expect("raises SyntaxError", False)
    except SyntaxError:
        t.expect("raises SyntaxError", True)

    # --- source_hash stability ---
    print()
    print("== source_hash ==")
    h1, n1 = source_hash("abc")
    h2, n2 = source_hash("abc")
    h3, n3 = source_hash("abd")
    t.expect("same input -> same hash", h1 == h2 and n1 == n2)
    t.expect("different input -> different hash", h1 != h3)
    t.expect("empty -> (17, 0)", source_hash("") == (17, 0))

    # --- hash of a long source is limited to 2048 bytes ---
    long_a = "a" * 5000
    long_b = "a" * 2048 + "b" * 2952
    t.expect("hash ignores bytes past limit",
             source_hash(long_a)[0] == source_hash(long_b)[0])

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
