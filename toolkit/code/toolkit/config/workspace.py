"""Workspace model — multi-root project for the toolkit.

Spec: docs/WORKSPACE.md. Pure data + validation + JSON I/O. Not wired
into Session / backends / GUI yet — that is steps 3+ of the plan.

Concepts:
  Workspace   — a named set of FS roots + policy + per-domain index config.
  Root        — one FS directory; identified by the basename of its path.
                Uniqueness enforced: two roots named `toolkit` cannot
                coexist. No label / id / display_name — the basename is
                the identity (see WORKSPACE.md §2).
  RootPolicy  — five independent flags per root: read, write, index_docs,
                index_py, index_lua. No nesting, so no inheritance.

State layout (external by default):
    <toolkit_root>/runtime/workspaces/<id>/
        workspace.json    this module reads/writes it
        .patchignore      FS visibility rules
        .mcpignore        MCP visibility rules
        INDEX.md          docs index (produced elsewhere)
        CODE_INDEX.md     Python index
        CODE_INDEX_LUA.md Luau index
        *.manifest.json   index sidecars
        .index_meta.json  per-section metadata
        runtime/          bridge state, logs, metrics

Embedded state (user puts the directory inside their project) works the
same — the toolkit just needs the path. `runtime/recent.json` records
recently opened state directories, so embedded workspaces can be found.

Not implemented here: policy enforcement, path resolution to roots,
Session wiring, GUI, migration from the old single-root model.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path


WORKSPACE_FILENAME = "workspace.json"

DEFAULT_INDEX_FLAGS = ("index_docs", "index_py", "index_lua")


@dataclass
class Root:
    """One FS root. Name is derived from path's basename (see module doc)."""
    path: str
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)

    def name(self) -> str:
        """Basename of the root path — the root's identity in workspace."""
        return Path(self.path).name


@dataclass
class RootPolicy:
    """Per-root policy. All flags independent; default all True."""
    read: bool = True
    write: bool = True
    index_docs: bool = True
    index_py: bool = True
    index_lua: bool = True


@dataclass
class Workspace:
    """A workspace: roots + policy + per-domain index config."""
    id: str
    name: str
    roots: dict[str, Root] = field(default_factory=dict)
    policy: dict[str, RootPolicy] = field(default_factory=dict)
    format: dict = field(default_factory=dict)
    exec: dict = field(default_factory=dict)
    mcp: dict = field(default_factory=dict)

    def root_names(self) -> list[str]:
        return sorted(self.roots.keys())


# --- identity -------------------------------------------------------------


def new_id() -> str:
    """Fresh workspace id: 12 hex chars. Stable for the workspace's life."""
    return uuid.uuid4().hex[:12]


# --- validation -----------------------------------------------------------


def _is_nested(a: Path, b: Path) -> bool:
    """True if either path is a strict ancestor of the other.

    Both sides resolved first. On Windows this is case-insensitive in
    practice via the filesystem; on POSIX it is exact.
    """
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

    Raises ValueError with a short reason when a check fails. Called on
    save and on add_root. Does not touch the filesystem beyond the
    paths' resolve() for nesting checks.
    """
    names: dict[str, str] = {}  # name -> path, to report collisions
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
    # Nesting: pairwise, but N is tiny.
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            n1, p1 = paths[i]
            n2, p2 = paths[j]
            if _is_nested(p1, p2):
                raise ValueError(
                    f"roots {n1!r} and {n2!r} are nested: "
                    f"{p1} <-> {p2}"
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
        raise ValueError(
            f"a root named {name!r} already exists in this workspace"
        )
    probe = Workspace(
        id=ws.id, name=ws.name,
        roots={**ws.roots, name: candidate},
        policy={**ws.policy, name: RootPolicy()},
        format=ws.format, exec=ws.exec, mcp=ws.mcp,
    )
    validate(probe)
    ws.roots[name] = candidate
    ws.policy.setdefault(name, RootPolicy())
    return name


# --- serialization --------------------------------------------------------


def _root_to_dict(r: Root) -> dict:
    d: dict = {"path": r.path}
    if r.include:
        d["include"] = list(r.include)
    if r.exclude:
        d["exclude"] = list(r.exclude)
    return d


def _root_from_dict(d: dict) -> Root:
    return Root(
        path=str(d.get("path", "")),
        include=list(d.get("include") or []),
        exclude=list(d.get("exclude") or []),
    )


def _policy_to_dict(p: RootPolicy) -> dict:
    return {
        "read": bool(p.read),
        "write": bool(p.write),
        "index_docs": bool(p.index_docs),
        "index_py": bool(p.index_py),
        "index_lua": bool(p.index_lua),
    }


def _policy_from_dict(d: dict) -> RootPolicy:
    return RootPolicy(
        read=bool(d.get("read", True)),
        write=bool(d.get("write", True)),
        index_docs=bool(d.get("index_docs", True)),
        index_py=bool(d.get("index_py", True)),
        index_lua=bool(d.get("index_lua", True)),
    )


def to_dict(ws: Workspace) -> dict:
    return {
        "id": ws.id,
        "name": ws.name,
        "roots": {k: _root_to_dict(v) for k, v in ws.roots.items()},
        "policy": {k: _policy_to_dict(v) for k, v in ws.policy.items()},
        "format": dict(ws.format),
        "exec": dict(ws.exec),
        "mcp": dict(ws.mcp),
    }


def from_dict(d: dict) -> Workspace:
    roots = {k: _root_from_dict(v) for k, v in (d.get("roots") or {}).items()}
    policy = {k: _policy_from_dict(v) for k, v in (d.get("policy") or {}).items()}
    # Every root must have a policy entry; fill defaults for missing ones.
    for name in roots:
        policy.setdefault(name, RootPolicy())
    return Workspace(
        id=str(d.get("id") or new_id()),
        name=str(d.get("name") or "workspace"),
        roots=roots,
        policy=policy,
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
