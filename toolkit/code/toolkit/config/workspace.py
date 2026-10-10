"""Workspace model — multi-root project for the toolkit.

Spec: docs/WORKSPACE.md, docs/WORKSPACE_BACKEND.md.

Concepts:
  Workspace    — a named set of FS roots + per-domain config. Identity
                 file: `workspace.json` in the state directory.
  Root         — one FS directory; identified by the basename of its path.
                 Uniqueness enforced: two roots named `toolkit` cannot
                 coexist. No label / id / display_name — the basename is
                 the identity.
  PathPolicy   — five independent flags (read, write, index_docs,
                 index_py, index_lua) applied to a path and, by
                 inheritance, to its subtree.
  Root.overrides — per-path policy map: relative path -> PathPolicy.
                 Special key "." holds the root default; empty means
                 all-True everywhere. Nearest-match wins.

Serialization form of a root:
    {
      "path": "...",
      "overrides": {
        ".": {"read": true, "write": true,
              "index_docs": true, "index_py": true, "index_lua": true},
        "docs/generated": {"write": false, "index_docs": false}
      },
      "include": [...],
      "exclude": [...]
    }

Legacy workspace.json (single top-level `policy: {root_name: flags}` block)
still loads: the flags become the root's `overrides["."]` on the fly. It
is not written back in that shape.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path


WORKSPACE_FILENAME = "workspace.json"

ALL_FLAGS = ("read", "write", "index_docs", "index_py", "index_lua")


# --- dataclasses -----------------------------------------------------------


@dataclass
class PathPolicy:
    """Five independent permission flags for a path (and, by inheritance,
    its subtree). All True by default."""
    read: bool = True
    write: bool = True
    index_docs: bool = True
    index_py: bool = True
    index_lua: bool = True

    def to_dict(self) -> dict:
        return {k: bool(getattr(self, k)) for k in ALL_FLAGS}

    @classmethod
    def from_dict(cls, d) -> "PathPolicy":
        if not isinstance(d, dict):
            return cls()
        return cls(**{k: bool(d.get(k, True)) for k in ALL_FLAGS})

    def copy(self) -> "PathPolicy":
        return PathPolicy(**{k: bool(getattr(self, k)) for k in ALL_FLAGS})


@dataclass
class Root:
    """One FS root. Name is derived from path's basename.

    `overrides` maps relative paths (forward-slash separated) to a
    PathPolicy. The special key "." holds the default for the root. An
    empty map means "all flags True everywhere".
    """
    path: str
    overrides: dict[str, PathPolicy] = field(default_factory=dict)
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)

    def name(self) -> str:
        """Basename of the root path — the root's identity in workspace."""
        return Path(self.path).name

    def policy_for(self, rel: str) -> PathPolicy:
        """Effective policy for a relative path inside this root.

        Nearest-match wins: exact -> nearest ancestor -> "." -> default.
        """
        if not self.overrides:
            return PathPolicy()
        norm = (rel or "").replace("\\", "/").strip("/")
        if norm in self.overrides:
            return self.overrides[norm]
        parts = norm.split("/") if norm else []
        for i in range(len(parts) - 1, 0, -1):
            prefix = "/".join(parts[:i])
            if prefix in self.overrides:
                return self.overrides[prefix]
        if "." in self.overrides:
            return self.overrides["."]
        return PathPolicy()


@dataclass
class Workspace:
    """A workspace: roots + per-domain config."""
    id: str
    name: str
    roots: dict[str, Root] = field(default_factory=dict)
    format: dict = field(default_factory=dict)
    exec: dict = field(default_factory=dict)
    mcp: dict = field(default_factory=dict)

    def root_names(self) -> list[str]:
        return sorted(self.roots.keys())

    def policy_for(self, root_name: str, rel: str) -> PathPolicy:
        """Effective policy for `<root_name>/<rel>`. Defaults to all-True."""
        r = self.roots.get(root_name)
        if r is None:
            return PathPolicy()
        return r.policy_for(rel)


# --- identity -------------------------------------------------------------


def new_id() -> str:
    """Fresh workspace id: 12 hex chars. Stable for the workspace's life."""
    return uuid.uuid4().hex[:12]


# --- validation -----------------------------------------------------------


def _is_nested(a: Path, b: Path) -> bool:
    """True if either path is a strict ancestor of the other."""
    try:
        a = a.resolve()
        b = b.resolve()
    except OSError:
        return False
    if a == b:
        return False
    return a in b.parents or b in a.parents


def _roblox_services() -> set[str]:
    try:
        from ..core.paths import ROBLOX_SERVICES  # type: ignore
        return {str(s) for s in ROBLOX_SERVICES}
    except Exception:
        return set()


def validate(ws: Workspace) -> None:
    """Check the invariants from WORKSPACE.md §4 / §8.

    Raises ValueError with a short reason when a check fails.
    """
    names: dict[str, str] = {}
    reserved = _roblox_services()
    paths: list[tuple[str, Path]] = []
    for name, root in ws.roots.items():
        if not name:
            raise ValueError("root name is empty")
        derived = root.name()
        if not derived:
            raise ValueError(f"root {name!r} has an empty basename")
        if name != derived:
            raise ValueError(
                f"root key {name!r} does not match path basename {derived!r}"
            )
        if name in reserved:
            raise ValueError(
                f"root name {name!r} collides with a Roblox service name"
            )
        if name in names:
            raise ValueError(
                f"duplicate root name {name!r} "
                f"(paths {names[name]!r} and {root.path!r})"
            )
        names[name] = root.path
        paths.append((name, Path(root.path)))
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            n1, p1 = paths[i]
            n2, p2 = paths[j]
            if _is_nested(p1, p2):
                raise ValueError(
                    f"roots {n1!r} and {n2!r} are nested: {p1} <-> {p2}"
                )


def add_root(ws: Workspace, path: str) -> str:
    """Add a root by absolute path; return its derived name.

    Raises ValueError on name collision, nesting, or reserved-name
    collision. No auto-renaming: the caller fixes the input.
    """
    p = str(Path(path).resolve())
    candidate = Root(path=p)
    name = candidate.name()
    if not name:
        raise ValueError(f"cannot derive a root name from {path!r}")
    if name in ws.roots:
        raise ValueError(f"a root named {name!r} already exists")
    probe = Workspace(
        id=ws.id, name=ws.name,
        roots={**ws.roots, name: candidate},
        format=ws.format, exec=ws.exec, mcp=ws.mcp,
    )
    validate(probe)
    ws.roots[name] = candidate
    return name


# --- serialization --------------------------------------------------------


def _root_to_dict(r: Root) -> dict:
    d: dict = {"path": r.path}
    if r.overrides:
        d["overrides"] = {k: v.to_dict() for k, v in r.overrides.items()}
    if r.include:
        d["include"] = list(r.include)
    if r.exclude:
        d["exclude"] = list(r.exclude)
    return d


def _root_from_dict(d: dict) -> Root:
    raw = d.get("overrides") or {}
    overrides = {str(k): PathPolicy.from_dict(v) for k, v in raw.items()}
    return Root(
        path=str(d.get("path", "")),
        overrides=overrides,
        include=list(d.get("include") or []),
        exclude=list(d.get("exclude") or []),
    )


def to_dict(ws: Workspace) -> dict:
    return {
        "id": ws.id,
        "name": ws.name,
        "roots": {k: _root_to_dict(v) for k, v in ws.roots.items()},
        "format": dict(ws.format),
        "exec": dict(ws.exec),
        "mcp": dict(ws.mcp),
    }


def from_dict(d: dict) -> Workspace:
    roots_data = d.get("roots") or {}
    old_policy = d.get("policy") or {}  # migration from pre-per-path format
    roots: dict[str, Root] = {}
    for name, rd in roots_data.items():
        r = _root_from_dict(rd or {})
        # Migrate old top-level policy block into the root's default override.
        if not r.overrides and name in old_policy:
            r.overrides["."] = PathPolicy.from_dict(old_policy[name])
        roots[name] = r
    return Workspace(
        id=str(d.get("id") or new_id()),
        name=str(d.get("name") or "workspace"),
        roots=roots,
        format=dict(d.get("format") or {}),
        exec=dict(d.get("exec") or {}),
        mcp=dict(d.get("mcp") or {}),
    )


# --- disk I/O -------------------------------------------------------------


def workspace_file(state_dir: Path) -> Path:
    return Path(state_dir) / WORKSPACE_FILENAME


def load(state_dir: Path) -> Workspace | None:
    """Read workspace.json from a state directory. None if absent/broken."""
    p = workspace_file(state_dir)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    try:
        return from_dict(data)
    except Exception:
        return None


def save(ws: Workspace, state_dir: Path) -> bool:
    """Write workspace.json. Validates first. Returns True on success."""
    try:
        validate(ws)
    except ValueError:
        return False
    p = workspace_file(state_dir)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(to_dict(ws), ensure_ascii=False, indent=2,
                       sort_keys=True),
            encoding="utf-8",
        )
        return True
    except OSError:
        return False
