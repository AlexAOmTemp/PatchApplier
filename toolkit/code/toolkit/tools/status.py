"""Session status tool.

Compact "where I am" call for an LLM starting a session or checking the
world after a config change. Returns three sections: session info, index
status, and effective path policy. Pure text, no JSON.

Policy flags are R / W / Id / Ip / Il — a letter present means the flag
is allowed for that path. For filesystem roots the policy comes from the
WorkspaceBackend's Workspace (per-root and per-path PathPolicy); for MCP
there is no path policy.

Only indexes whose owning backend is enabled are reported: docs/code need
the filesystem backend, lua needs the MCP (Roblox) backend.
"""
from __future__ import annotations

from typing import Any

from ..core.backend import Backend
from ..core.models import Result
from ..core.paths import ROBLOX_SERVICES


def _is_roblox_path(path: str) -> bool:
    """True if a policy key refers to a Roblox DataModel service subtree."""
    if not path or path == ".":
        return False
    top = path.split("/", 1)[0]
    return top in ROBLOX_SERVICES


def _backends_enabled_from_name(name: str) -> set[str]:
    if name == "composite":
        return {"filesystem", "mcp"}
    if name == "mcp":
        return {"mcp"}
    return {"filesystem"}


class GetStatusTool:
    name = "get_status"
    op = "read"
    path_args: list[str] = []
    path_list_args: list[str] = []

    DEFAULT_SECTIONS = ("session", "indexes", "policy")

    _context: dict = {}

    @classmethod
    def set_context(
        cls,
        *,
        project_name: str = "",
        backend: str = "",
        luau_mode: str = "mcp",
        format_preset: str = "",
        exec_enabled: bool = False,
        exec_interpreter: str | None = None,
        native_tools_enabled: bool = False,
        native_tools_allow: list | None = None,
        index_paths: dict | None = None,
        backends_enabled: set | None = None,
    ) -> None:
        cls._context = {
            "project_name": project_name or "",
            "backend": backend or "",
            "luau_mode": luau_mode or "mcp",
            "format_preset": format_preset or "default",
            "exec_enabled": bool(exec_enabled),
            "exec_interpreter": exec_interpreter or None,
            "native_tools_enabled": bool(native_tools_enabled),
            "native_tools_allow": list(native_tools_allow or []),
            "index_paths": dict(index_paths or {
                "docs": "INDEX.md",
                "code": "CODE_INDEX.md",
                "lua": "CODE_INDEX_LUA.md",
            }),
            "backends_enabled": set(backends_enabled or {"filesystem"}),
        }


    def execute(
        self,
        backend: Backend,
        fmt: Any = None,
        sections: str | list | None = None,
        **_: Any,
    ) -> Result:
        if sections is None:
            secs = list(self.DEFAULT_SECTIONS)
        elif isinstance(sections, str):
            secs = [sections]
        elif isinstance(sections, list):
            secs = sections
        else:
            return Result(
                status="error",
                message="`sections` must be a string or a list.",
                error_code="bad_sections",
                action="get_status",
            )

        unknown = [s for s in secs if s not in self.DEFAULT_SECTIONS]
        if unknown:
            return Result(
                status="error",
                message=(
                    f"unknown section(s) {unknown}; valid: "
                    f"{list(self.DEFAULT_SECTIONS)}"
                ),
                error_code="unknown_section",
                action="get_status",
            )

        blocks: list[str] = []
        if "session" in secs:
            blocks.append(self._render_session())
        if "indexes" in secs:
            blocks.append(self._render_indexes(backend))
        if "policy" in secs:
            blocks.append(self._render_policy(backend))

        return Result(
            status="ok",
            message="\n\n".join(b for b in blocks if b),
            action="get_status",
        )

    # --- session ----------------------------------------------------------

    def _render_session(self) -> str:
            ctx = self._context
            lines = ["## Session"]
            lines.append(f"project:  {ctx.get('project_name') or '(unknown)'}")
            lines.append(f"backend:  {ctx.get('backend') or '(unknown)'}")
            lines.append(f"luau:     {ctx.get('luau_mode') or 'mcp'}")
            enabled = ctx.get("backends_enabled") or {"filesystem"}
            lines.append(f"format:   {ctx.get('format_preset') or 'default'}")
            if ctx.get("exec_enabled"):
                interp = ctx.get("exec_interpreter") or "sys.executable"
                lines.append(f"exec:     enabled  ({interp})")
            else:
                lines.append("exec:     disabled")
            if "mcp" in enabled:
                if ctx.get("native_tools_enabled"):
                    allow = ctx.get("native_tools_allow") or []
                    allow_s = ", ".join(allow) if allow else "(no allowlist -> all)"
                    lines.append(f"native:   enabled  ({allow_s})")
                else:
                    lines.append("native:   disabled")
            return "\n".join(lines)

    # --- indexes ----------------------------------------------------------

    def _render_indexes(self, backend: Backend) -> str:
        ctx = self._context
        paths = ctx.get("index_paths") or {}
        enabled = ctx.get("backends_enabled") or {"filesystem"}

        # docs and code live on the filesystem; the lua index requires the
        # MCP (Roblox) backend to rebuild. Hide kinds whose backend is off.
        kind_to_owner = {"docs": "filesystem", "code": "filesystem", "lua": "mcp"}

        entries: list[tuple[str, str]] = []
        for kind in ("docs", "code", "lua"):
            if kind_to_owner[kind] not in enabled:
                continue
            path = paths.get(kind)
            if not path:
                continue
            entries.append((kind, path))

        if not entries:
            return "## Indexes\n(no indexes for enabled backends)"

        from ..indexers.state import read_seq

        rows: list[str] = []
        for kind, path in entries:
            try:
                exists = backend.exists(path)
            except Exception as e:
                rows.append(f"{kind}  {path}  (exists error: {e})")
                continue
            if not exists:
                rows.append(f"{kind}  {path}  (not built)")
                continue
            try:
                text = backend.read(path)
            except Exception as e:
                rows.append(f"{kind}  {path}  (read error: {e})")
                continue
            try:
                seq = read_seq(backend, path + ".version")
            except Exception:
                seq = 0
            size_kb = len(text.encode("utf-8")) / 1024
            items = self._count_items(kind, text)
            rows.append(f"{kind}  {path}  [v{seq}]  {size_kb:.1f} KB  {items}")

        return "## Indexes\n" + "\n".join(rows)

    def _count_items(self, kind: str, text: str) -> str:
        n = sum(1 for line in text.splitlines() if line.startswith("## "))
        if kind == "docs":
            return f"{n} files"
        if kind in ("code", "lua"):
            return f"{n} modules"
        return f"{n} items"

    # --- policy -----------------------------------------------------------

    def _render_policy(self, backend: Backend) -> str:
        ctx = self._context
        enabled = ctx.get("backends_enabled") or {"filesystem"}

        blocks: list[str] = []

        if "filesystem" in enabled:
            ws = getattr(backend, "ws", None)
            if ws is None:
                blocks.append("## Policy Filesystem")
                blocks.append("(no workspace on this backend)")
            else:
                blocks.append("## Policy Filesystem")
                blocks.extend(self._render_policy_rows(ws))
                blocks.append("")
                blocks.append("+ auto-closed: dotdirs, __pycache__, node_modules, .venv  (not shown)")
                blocks.append("  to open a hidden path: set + on the dir itself or its named ancestor")

        if "mcp" in enabled:
            luau = ctx.get("luau_mode") or "mcp"
            scope = "Roblox scene + Luau code" if luau == "mcp" else "Roblox scene"
            blocks.append("## MCP")
            blocks.append(f"scope:    {scope}")
            blocks.append("access:   unrestricted (DataModel is not path-filtered)")

        if not blocks:
            return "## Policy\n(no backends enabled)"
        return "\n".join(blocks)

    def _render_policy_rows(self, ws) -> list[str]:
        """One row per root: name and effective default flags.

        Explicit per-path overrides (keys other than ".") are listed beneath
        the root when present.
        """
        rows: list[str] = []
        for name in ws.root_names():
            root = ws.roots[name]
            default = ws.policy_for(name, "")
            rows.append(f"{name.ljust(24)}   {self._flags_for(default)}")
            extras = [k for k in root.overrides.keys() if k != "."]
            for p in sorted(extras):
                pol = root.overrides[p]
                rows.append(f"  {p.ljust(22)}   {self._flags_for(pol)}")
        if not rows:
            return ["(no roots)"]
        return rows

    def _flags_for(self, pol) -> str:
        """[R W Id Ip Il] with letters present only for True flags."""
        tokens = []
        for letter, key in (("R", "read"), ("W", "write"),
                            ("Id", "index_docs"), ("Ip", "index_py"),
                            ("Il", "index_lua")):
            try:
                if bool(getattr(pol, key)):
                    tokens.append(letter)
            except Exception:
                pass
        return "[" + " ".join(tokens) + "]" if tokens else "[-]"
