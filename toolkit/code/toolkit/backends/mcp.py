"""MCP backend — talks to Roblox Studio via bridge.py subprocess.

Lifecycle:
    backend = MCPBackend(bridge_script="bridge.py", command="python -u")
    backend.open()   # spawns bridge, waits for "Мост готов"
    ...
    backend.close()  # sends "exit\n", waits, kills on timeout

The bridge speaks a simple protocol:
    - Reads "accept\n" from stdin
    - Reads patch.json: {"tool": "...", "arguments": {...}}
    - Writes outputs.json: list of {tool_called, result: [texts], is_error}
    - New entries are written fresh (accept replaces, accept -add prepends)

We always use plain `accept`, so outputs.json after a call holds exactly
one entry — the result of our single tool invocation.

Path format: DataModel dotted paths, with or without leading "game.":
    "ReplicatedStorage.Foo.Bar"  or  "game.ReplicatedStorage.Foo.Bar"

B1 scope: lifecycle, read, exists, filter_check. write/stat/list/delete/move
are stubs that raise NotImplementedError — they arrive in B2.
"""
from __future__ import annotations

import json
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from ..core.models import FilterSpec, FileStat


DEFAULT_READY_TIMEOUT = 90.0
DEFAULT_CALL_TIMEOUT = 120.0
DEFAULT_STUDIO_TIMEOUT = 60.0
DEFAULT_RETRIES = 6
DEFAULT_RETRY_DELAY = 1.0

# MCP proxy returns these transiently while Studio is warming up or
# reconnecting. We retry rather than surface the error.
STUDIO_TRANSIENT_MARKERS = (
    "No Roblox Studio instances are connected",
    "No Roblox Studio instances",
    "No studio available",
)


# --- Lua script templates ------------------------------------------------
#
# Inline Luau in Python strings is hard to read and easy to break with
# escaping. Transport scripts live as .lua files under toolkit/lua/scripts/
# and are loaded here with %KEY% placeholder substitution. Use .replace()
# rather than str.format() so `{}` in Lua tables stays literal.

_LUA_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "lua" / "scripts"
_LUA_SCRIPTS_CACHE: dict[str, str] = {}
_PLACEHOLDER_RE = re.compile(r"%([A-Z][A-Z0-9_]*)%")


def _lua_script(name: str, **params: str) -> str:
    """Load toolkit/lua/scripts/<name>.lua and substitute %KEY% placeholders.

    Line endings are normalized to \n so scripts behave identically on
    Windows and POSIX. Result is cached per name; parameters are applied
    on every call.

    Substitution is single-pass: a value containing a literal `%MAX%` is
    not re-scanned, so user-supplied patterns cannot inject placeholder
    replacements.
    """
    src = _LUA_SCRIPTS_CACHE.get(name)
    if src is None:
        path = _LUA_SCRIPTS_DIR / f"{name}.lua"
        text = path.read_text(encoding="utf-8")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        _LUA_SCRIPTS_CACHE[name] = text
        src = text
    upper = {k.upper(): str(v) for k, v in params.items()}

    def _sub(m):
        key = m.group(1)
        return upper.get(key, m.group(0))

    return _PLACEHOLDER_RE.sub(_sub, src)


class MCPBackend:
    def __init__(
            self,
            bridge_script: str | Path,
            command: str = "python -u",
            mcp_command: str | None = None,
            mcp_args: str = "",
            working_dir: str | Path = ".",
            state_subdir: str = ".patch_applier",
            patch_file: str = "patch.json",
            outputs_file: str = "outputs.json",
            log_file: str = "bridge_log.jsonl",
            tools_file: str | Path | None = None,
            preflight: bool = True,
            auto_switch: bool = True,
            ready_timeout: float = DEFAULT_READY_TIMEOUT,
            call_timeout: float = DEFAULT_CALL_TIMEOUT,
            studio_timeout: float = DEFAULT_STUDIO_TIMEOUT,
            max_retries: int = DEFAULT_RETRIES,
            retry_delay: float = DEFAULT_RETRY_DELAY,
            native_tools_enabled: bool = False,
            native_tools_allow: list | None = None,
            quiet_bridge: bool = True,
        ):
        self.bridge_script = str(bridge_script)
        self.command = command
        self.mcp_command = mcp_command
        self.mcp_args = mcp_args
        self.working_dir = Path(working_dir).resolve()
        # Working state files (patch.json, outputs.json, bridge_log.jsonl)
        # go into a dedicated subdir of the *project* so they don't pollute
        # the project root, and so each project has its own runtime state.
        state_dir = self.working_dir / state_subdir if state_subdir else self.working_dir
        try:
            state_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            state_dir = self.working_dir
        self.state_dir = state_dir
        self.patch_file = state_dir / patch_file
        self.outputs_file = state_dir / outputs_file
        self.log_file = state_dir / log_file
        # tools_schema.json is toolkit-global, not project data: the same
        # schema is regenerated for every project. Keep it in the toolkit's
        # own runtime dir so switching projects does not litter each one
        # with an identical file. If `tools_file` is absolute — honour it.
        if tools_file is None:
            from ..config.loader import toolkit_runtime_state_dir
            tools_path = toolkit_runtime_state_dir() / "tools_schema.json"
        else:
            tools_path = Path(tools_file)
            if not tools_path.is_absolute():
                tools_path = toolkit_runtime_state_dir() / tools_path
        try:
            tools_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        self.tools_file = tools_path
        self.preflight = preflight
        self.auto_switch = auto_switch
        self.ready_timeout = ready_timeout
        self.call_timeout = call_timeout
        self.studio_timeout = studio_timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.native_tools_enabled = bool(native_tools_enabled)
        self.native_tools_allow = (
            list(native_tools_allow) if native_tools_allow is not None
            else None
        )
        self.quiet_bridge = bool(quiet_bridge)

        self._proc: subprocess.Popen | None = None
        self._stdout_q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._reader: threading.Thread | None = None
        self._lock = threading.Lock()

    # --- lifecycle ---------------------------------------------------------

    def open(self) -> None:
        if not Path(self.bridge_script).is_file():
            raise RuntimeError(f"bridge_script не найден: {self.bridge_script}")
        cmd = self.command.split() + [self.bridge_script]
        if self.mcp_command:
            cmd += ["--command", self.mcp_command]
        if self.mcp_args:
            cmd += ["--args", self.mcp_args]
        cmd += ["--tools-file", str(self.tools_file)]
        cmd += ["--patch-file", str(self.patch_file)]
        cmd += ["--outputs-file", str(self.outputs_file)]
        cmd += ["--log-file", str(self.log_file)]
        if not self.preflight:
            cmd += ["--no-preflight"]
        if not self.auto_switch:
            cmd += ["--no-auto-switch"]
        if self.quiet_bridge:
            cmd += ["--quiet"]

        env = {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
        import os
        full_env = os.environ.copy()
        full_env.update(env)

        # On Windows, spawning a fresh python.exe without flags creates a
        # visible console window for the child. CREATE_NO_WINDOW keeps the
        # bridge headless. On POSIX there is nothing to suppress; use 0.
        creationflags = 0
        if os.name == "nt":
            creationflags = 0x08000000  # CREATE_NO_WINDOW

        self._proc = subprocess.Popen(
            cmd,
            cwd=str(self.working_dir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=full_env,
            creationflags=creationflags,
        )
        self._stop.clear()
        self._reader = threading.Thread(
            target=self._reader_loop, args=(self._proc.stdout,), daemon=True
        )
        self._reader.start()
        self._stderr_reader = threading.Thread(
            target=self._stderr_loop, args=(self._proc.stderr,), daemon=True
        )
        self._stderr_reader.start()

        self._wait_ready(self.ready_timeout)
        self._wait_studio_ready(self.studio_timeout)

    def close(self) -> None:
        proc = self._proc
        if proc is None:
            return
        self._stop.set()
        try:
            if proc.poll() is None and proc.stdin:
                proc.stdin.write("exit\n")
                proc.stdin.flush()
        except Exception:
            pass
        try:
            proc.wait(timeout=5.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        self._proc = None

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def ensure_alive(self) -> bool:
        """If bridge process died, try to reopen it once. Returns True if alive.

        Used before `_invoke` -- after long bulk-read sequences the MCP
        server may drop the Studio connection, and a fresh bridge instance
        re-establishes it.
        """
        if self.is_alive():
            return True
        try:
            self.close()
        except Exception:
            pass
        try:
            self.open()
            return True
        except Exception:
            return False

    # --- data (B1 scope) ---------------------------------------------------

    def read(self, path: str) -> str:
        norm = self._normalize(path)
        # pcall-wrapped so a missing intermediate segment doesn't crash the Lua
        # expression; markers distinguish "no path" from "not a script".
        code = (
            f"local ok, val = pcall(function() return game.{norm} end)\n"
            f"if not ok then return \"__MISSING__\" end\n"
            f"if val == nil then return \"__MISSING__\" end\n"
            f"if typeof(val) ~= 'Instance' then return \"__MISSING__\" end\n"
            f"if not val:IsA('LuaSourceContainer') then return \"__NOT_SOURCE__\" end\n"
            f"return val.Source"
        )
        entry = self._invoke("execute_luau", {
            "datamodel_type": "Edit",
            "code": code,
        })
        texts = entry.get("result") or []
        text = texts[0] if texts else ""
        if entry.get("is_error"):
            raise FileNotFoundError(f"MCP read failed for {path}: {text[:200]}")
        if text == "__MISSING__":
            raise FileNotFoundError(path)
        if text == "__NOT_SOURCE__":
            raise FileNotFoundError(f"{path} is not a script instance")
        return text

    def read_many(self, paths, batch_size: int = 8) -> dict:
        """Read many sources in one accept using a list of execute_luau calls.

        Content-addressed batch matching: each entry in outputs.json carries the
        arguments.code it was invoked with, so we can match entries back to
        their source batches by sha1 of code. Only failed batches are retried
        at half size. Every fallback event is recorded in mcp_fallback.log.
        """
        if not paths:
            return {}

        import hashlib as _hashlib
        import time as _time
        from pathlib import Path as _P

        _fallback_log = _P(__file__).resolve().parents[3] / "runtime" / "logs" / "mcp_fallback.log"
        try:
            _fallback_log.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        def _note(msg):
            try:
                import datetime as _dt
                line = f"{_dt.datetime.now().isoformat()}  {msg}"
                sys.stderr.write(f"[mcp.fallback] {msg}\n")
                sys.stderr.flush()
                with open(_fallback_log, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass

        def _make_read_call(batch):
            paths_lua = "{" + ",".join(json.dumps(p) for p in batch) + "}"
            code = "\n".join([
                f"local paths = {paths_lua}",
                "local out = {}",
                "for _, p in ipairs(paths) do",
                "    local node = game",
                "    local ok = true",
                "    for seg in string.gmatch(p, '[^%.]+') do",
                "        if not ok then break end",
                "        node = node:FindFirstChild(seg)",
                "        if not node then ok = false end",
                "    end",
                "    if ok and node and node:IsA('LuaSourceContainer') then",
                "        out[p] = node.Source",
                "    end",
                "end",
                "return game:GetService('HttpService'):JSONEncode(out)",
            ])
            return {"tool": "execute_luau",
                    "arguments": {"datamodel_type": "Edit", "code": code}}

        def _parse_read_entry(entry):
            if not entry or entry.get("is_error"):
                return None
            texts = entry.get("result") or []
            if not texts:
                return None
            text = texts[0]
            if not text or text == "null":
                return {}
            try:
                chunk = json.loads(text)
            except json.JSONDecodeError:
                return None
            if not isinstance(chunk, dict):
                return None
            return chunk

        def _read_batches_recursive(paths_list, bsize, result, stats, depth):
            if not paths_list:
                return
            if bsize <= 1:
                _note(f"per-path fallback: {len(paths_list)} paths, depth={depth}")
                for p in paths_list:
                    try:
                        result[p] = self.read(p)
                    except Exception:
                        continue
                return

            batches = [paths_list[i:i + bsize]
                       for i in range(0, len(paths_list), bsize)]
            calls = [_make_read_call(b) for b in batches]
            stats["batches"] += len(batches)

            try:
                entries = self._invoke_many(calls)
            except Exception as e:
                _note(f"invoke_many raised at depth {depth}, bsize={bsize}: {type(e).__name__}: {e}")
                _read_batches_recursive(
                    paths_list, max(1, bsize // 2), result, stats, depth + 1
                )
                return

            stats["entries"] += len(entries)
            if len(entries) != len(batches):
                _note(f"entries count mismatch at depth {depth}: got {len(entries)}, expected {len(batches)}")
            code_by_hash = {}
            for b, c in zip(batches, calls):
                h = _hashlib.sha1(c["arguments"]["code"].encode("utf-8")).hexdigest()
                code_by_hash[h] = b

            retry = []
            truncated_examples = []
            for entry in entries:
                args = entry.get("arguments") or {}
                code = args.get("code", "")
                h = _hashlib.sha1(code.encode("utf-8")).hexdigest() if code else ""
                batch = code_by_hash.get(h)
                if batch is None:
                    continue
                chunk = _parse_read_entry(entry)
                if chunk is None:
                    stats["truncated"] += 1
                    if len(truncated_examples) < 3:
                        texts = entry.get("result") or []
                        preview = (texts[0][:200] if texts else "(no text)")
                        truncated_examples.append(preview.replace(chr(10), "\\n"))
                    retry.extend(batch)
                else:
                    result.update(chunk)
            if truncated_examples:
                _note(f"truncated/bad entries at depth {depth}, bsize={bsize}: "
                      f"examples={truncated_examples}")

            received_paths = set(result.keys()) | set(retry)
            for batch in batches:
                for p in batch:
                    if p not in received_paths and p not in result:
                        retry.append(p)
                        received_paths.add(p)

            if retry:
                stats["retries"] += 1
                _read_batches_recursive(
                    retry, max(1, bsize // 2), result, stats, depth + 1
                )

        t0 = _time.time()
        path_list = list(paths)
        result = {}
        stats = {"truncated": 0, "entries": 0, "batches": 0, "retries": 0}
        _read_batches_recursive(path_list, max(1, batch_size), result, stats, 0)
        elapsed = _time.time() - t0
        summary = (
            f"read_many: {len(path_list)} paths, {stats['batches']} batches, "
            f"{stats['entries']} entries, {stats['truncated']} truncated, "
            f"{stats['retries']} retries, {elapsed:.2f}s"
        )
        try:
            sys.stderr.write(f"[mcp] {summary}\n")
            sys.stderr.flush()
        except Exception:
            pass
        if stats["truncated"] or stats["retries"]:
            _note(summary)
        return result

    def _invoke_many(self, calls: list[dict], timeout: float | None = None) -> list[dict]:
        """Send a patch.json with a LIST of calls; return list of entries.

        Bridge executes them sequentially, writes a list of entries into
        outputs.json. Each entry's `result` is bounded by the MCP per-call
        response limit (~112 KB) -- so we batch by expected response size,
        not by number of calls.
        """
        if not calls:
            return []
        if self._proc is None or self._proc.poll() is not None:
            if not self.ensure_alive():
                raise RuntimeError("bridge not alive and could not reopen")
        t = timeout if timeout is not None else max(self.call_timeout, 60.0 * (1 + len(calls) // 16))

        _t0 = time.time()
        with self._lock:
            if self.outputs_file.exists():
                try:
                    self.outputs_file.unlink()
                except Exception:
                    pass
            self.patch_file.parent.mkdir(parents=True, exist_ok=True)
            self.patch_file.write_text(
                json.dumps(calls, ensure_ascii=False),
                encoding="utf-8",
            )
            _t_write = time.time()
            try:
                self._proc.stdin.write("accept\n")
                self._proc.stdin.flush()
            except Exception as e:
                raise RuntimeError(f"cannot write to bridge stdin: {e}")
            _t_accept = time.time()

            deadline = time.time() + t
            first_seen = None
            while time.time() < deadline:
                if self._proc.poll() is not None:
                    raise RuntimeError("bridge died while waiting for outputs")
                if self.outputs_file.exists():
                    try:
                        raw = self.outputs_file.read_text(encoding="utf-8").strip()
                        if raw:
                            data = json.loads(raw)
                            if isinstance(data, list) and data:
                                _t_done = time.time()
                                self._append_timing(
                                    f"[mcp.timing] invoke_many: calls={len(calls)} "
                                    f"write_patch={_t_write-_t0:.3f}s "
                                    f"write_accept={_t_accept-_t_write:.3f}s "
                                    f"wait={_t_done-_t_accept:.3f}s "
                                    f"total={_t_done-_t0:.3f}s"
                                )
                                return data
                    except (json.JSONDecodeError, OSError):
                        pass
                time.sleep(0.05)
            raise TimeoutError(f"no valid outputs.json for {len(calls)} calls after {t}s")

    def _read_batch(self, paths) -> dict:
        if not paths:
            return {}
        paths_lua = "{" + ",".join(json.dumps(p) for p in paths) + "}"
        code = (
            f"local paths = {paths_lua}\n"
            f"local out = {{}}\n"
            f"for _, p in ipairs(paths) do\n"
            f"    local node = game\n"
            f"    local ok = true\n"
            f"    for seg in string.gmatch(p, '[^%.]+') do\n"
            f"        if not ok then break end\n"
            f"        node = node:FindFirstChild(seg)\n"
            f"        if not node then ok = false end\n"
            f"    end\n"
            f"    if ok and node and node:IsA('LuaSourceContainer') then\n"
            f"        out[p] = node.Source\n"
            f"    end\n"
            f"end\n"
            f"return game:GetService('HttpService'):JSONEncode(out)"
        )
        text = self.execute(code)
        if not text or text == "null":
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"read_many: bad JSON from batch: {e}") from e

    def grep_mcp(self, root: str, pattern: str, *, fixed_strings: bool = False,
                     ignore_case: bool = False, word_boundary: bool = False,
                     max_results: int = 200,
                     before: int = 0, after: int = 0) -> str:
        """Grep LuaSourceContainers under `root` on the Studio side.

        Returns the raw output: lines "path:lineno: text" (with context
        markers if before/after > 0), or "__EMPTY__" if no matches, or
        "__MISSING__" if the root does not exist. On truncation, a final
        line "__TRUNCATED__" is appended. All transport is a single
        execute_luau call.

        Pattern semantics: `fixed_strings=False` (default) means the pattern
        is a Lua pattern (string.find with plain=false). `fixed_strings=True`
        means literal search. `ignore_case=True` is only supported when
        fixed_strings=True (ASCII-only lowercasing; documented limit).
        `word_boundary=True` restricts matches to identifier boundaries
        (a match must be preceded and followed by a non-word character or
        the string edge).
        """
        if ignore_case and not fixed_strings:
            raise ValueError(
                "ignore_case requires fixed_strings=True (Lua patterns "
                "with case folding have unsafe semantics)"
            )
        root_norm = self._normalize(root).strip(".") if root else ""
        expr = f"game.{root_norm}" if root_norm else "game"
        code = _lua_script(
            "grep",
            expr=expr,
            pattern=json.dumps(pattern, ensure_ascii=False),
            plain="true" if fixed_strings else "false",
            icase="true" if ignore_case else "false",
            wb="true" if word_boundary else "false",
            max=int(max_results),
            before=int(before),
            after=int(after),
        )
        return self.execute(code)

    def grep_replace_mcp(self, root: str, pattern=None, *,
                          replacement=None,
                          mappings=None,
                          fixed_strings: bool = False,
                          ignore_case: bool = False,
                          word_boundary: bool = False,
                          max_replacements: int = 1000,
                          dry_run: bool = True) -> str:
        """Two-pass search-and-replace over LuaSourceContainers under `root`.

        Exactly one of `pattern` / `mappings` must be provided.
        `mappings` requires fixed_strings=True (Lua patterns cannot be applied
        as a set in one pass). `ignore_case` is not supported with `mappings`.
        `word_boundary` is honored in both modes.

        Pass 1 (always) counts replacements per file without writing.
        A gate rejects `__EMPTY__` (no matches) or `__OVERFLOW__` (total >
        max_replacements) before any write happens. Pass 2 writes .Source
        only when dry_run=False.

        Returns the raw two-pass output: `CHANGED\\t<path>\\t<count>` lines,
        a final `__SUMMARY__\\tfiles=N\\treplacements=M\\tapplied=...`, or
        one of `__EMPTY__` / `__MISSING__` / `__OVERFLOW__\\t<found>\\t<max>`.
        All transport is a single execute_luau call; .Source never crosses
        the bridge.
        """
        has_pattern = pattern is not None
        has_mappings = mappings is not None
        if has_pattern == has_mappings:
            raise ValueError("exactly one of pattern/mappings is required")
        if has_mappings:
            if not fixed_strings:
                raise ValueError(
                    "mappings require fixed_strings=True "
                    "(Lua patterns cannot be combined in one pass)"
                )
            if ignore_case:
                raise ValueError("ignore_case is not supported with mappings")
            if not mappings:
                raise ValueError("mappings must not be empty")
            mappings_lua = "{" + ",".join(
                "{" + json.dumps(m[0], ensure_ascii=False)
                + "," + json.dumps(m[1], ensure_ascii=False) + "}"
                for m in mappings
            ) + "}"
            pattern_lua = "nil"
            replacement_lua = "nil"
        else:
            if not pattern:
                raise ValueError("pattern must not be empty")
            if ignore_case and not fixed_strings:
                raise ValueError(
                    "ignore_case requires fixed_strings=True (Lua patterns "
                    "with case folding have unsafe semantics)"
                )
            pattern_lua = json.dumps(pattern, ensure_ascii=False)
            replacement_lua = json.dumps(replacement or "", ensure_ascii=False)
            mappings_lua = "nil"
        if max_replacements <= 0:
            raise ValueError("max_replacements must be > 0")
        root_norm = self._normalize(root).strip(".") if root else ""
        expr = f"game.{root_norm}" if root_norm else "game"
        code = _lua_script(
            "grep_replace",
            expr=expr,
            pattern=pattern_lua,
            replacement=replacement_lua,
            mappings=mappings_lua,
            plain="true" if fixed_strings else "false",
            icase="true" if ignore_case else "false",
            wb="true" if word_boundary else "false",
            max=int(max_replacements),
            dry="true" if dry_run else "false",
        )
        return self.execute(code)


    def create(self, path: str, content: str, class_name: str = "ModuleScript") -> None:
        """Create a new script instance at `path` via multi_edit.

        multi_edit is the only bridge tool that can create LuaSourceContainer
        instances: execute_luau is sandboxed away from script creation. It has
        a known bug where it may report success without changing .Source, so
        the content is read back and compared before returning.

        Studio must be in Edit mode. Play mode is rejected by the bridge.
        """
        norm = self._normalize(path)
        if self.exists(path):
            raise FileExistsError(f"already exists: {path}")
        for b in content.encode("utf-8"):
            if b < 0x20 and b not in (0x09, 0x0a, 0x0d):
                raise ValueError(
                    f"content has unsupported control byte 0x{b:02x} at create {path}"
                )
        entry = self._invoke("multi_edit", {
            "file_path": f"game.{norm}",
            "edits": [{"old_string": "", "new_string": content}],
            "className": class_name,
            "datamodel_type": "Edit",
        })
        texts = entry.get("result") or []
        text = texts[0] if texts else ""
        if entry.get("is_error"):
            raise RuntimeError(f"MCP create failed for {path}: {text[:200]}")
        # verify-after-write: multi_edit may lie; confirm the content.
        actual = self.read(path)
        if actual != content:
            raise RuntimeError(
                f"verify-after-write mismatch for {path} (create): "
                f"expected {len(content)} chars, got {len(actual)}"
            )

    def write(self, path: str, content: str) -> None:
        norm = self._normalize(path)
        # Sanity: source code should only have \t / \n / \r as control chars.
        for b in content.encode("utf-8"):
            if b < 0x20 and b not in (0x09, 0x0a, 0x0d):
                raise ValueError(
                    f"content has unsupported control byte 0x{b:02x} at write to {path}"
                )
        lua_literal = json.dumps(content, ensure_ascii=False)
        code = (
            f"local ok, t = pcall(function() return game.{norm} end)\n"
            f"if not ok or t == nil then return '__MISSING__' end\n"
            f"if typeof(t) ~= 'Instance' or not t:IsA('LuaSourceContainer') then return '__NOT_SOURCE__' end\n"
            f"t.Source = {lua_literal}\n"
            f"return '__OK__'"
        )
        entry = self._invoke("execute_luau", {
            "datamodel_type": "Edit",
            "code": code,
        })
        texts = entry.get("result") or []
        text = texts[0] if texts else ""
        if entry.get("is_error"):
            raise RuntimeError(f"MCP write failed for {path}: {text[:200]}")
        if text == "__MISSING__":
            raise FileNotFoundError(path)
        if text == "__NOT_SOURCE__":
            raise ValueError(f"{path} is not a script instance")
        if text != "__OK__":
            raise RuntimeError(f"unexpected write response for {path}: {text[:120]}")
        # verify-after-write: read the source back and compare.
        actual = self.read(path)
        if actual != content:
            raise RuntimeError(
                f"verify-after-write mismatch for {path}: "
                f"expected {len(content)} chars, got {len(actual)}"
            )

    def exists(self, path: str) -> bool:
        """True if `path` resolves to a LuaSourceContainer.

        Uses a minimal execute_luau that never transfers Source.
        Any error (missing instance, non-source instance, bridge failure)
        is reported as False, matching the previous read-based behaviour.
        """
        norm = self._normalize(path)
        try:
            text = self.execute(_lua_script("exists", expr=f"game.{norm}"))
        except Exception:
            return False
        return (text or "").strip() == "1"

    def stat(self, path: str) -> FileStat:
        norm = self._normalize(path)
        # Returns: size|lines|is_source. Empty source gives 0|0|1.
        code = (
            f"local ok, t = pcall(function() return game.{norm} end)\n"
            f"if not ok or t == nil then return \"__MISSING__\" end\n"
            f"if typeof(t) ~= 'Instance' then return \"__MISSING__\" end\n"
            f"local is_source = t:IsA('LuaSourceContainer')\n"
            f"local src = is_source and t.Source or \"\"\n"
            f"local n = 0\n"
            f"for _ in string.gmatch(src, '\\n') do n = n + 1 end\n"
            f"if #src > 0 and string.sub(src, -1) ~= '\\n' then n = n + 1 end\n"
            f"return #src .. '|' .. n .. '|' .. (is_source and '1' or '0')"
        )
        entry = self._invoke("execute_luau", {
            "datamodel_type": "Edit",
            "code": code,
        })
        texts = entry.get("result") or []
        text = texts[0] if texts else ""
        if entry.get("is_error"):
            raise FileNotFoundError(f"MCP stat failed for {path}: {text[:200]}")
        if text == "__MISSING__":
            raise FileNotFoundError(path)
        parts = text.split("|")
        if len(parts) != 3:
            raise RuntimeError(f"unexpected stat response for {path}: {text[:120]}")
        try:
            size = int(parts[0])
            lines = int(parts[1])
            is_source = parts[2] == "1"
        except ValueError as e:
            raise RuntimeError(f"cannot parse stat for {path}: {text[:120]}") from e
        # Studio does not expose mtime; use 0 as "unknown".
        return FileStat(size_bytes=size, lines=lines, mtime=0.0, is_file=is_source)

    def list(self, root: str = "", glob: str = "*") -> list[str]:
        root_norm = self._normalize(root).strip(".") if root else ""
        expr = f"game.{root_norm}" if root_norm else "game"
        code = (
            f"local ok, node = pcall(function() return {expr} end)\n"
            f"if not ok or node == nil then return \"__MISSING__\" end\n"
            f"local paths = {{}}\n"
            f"local n = 0\n"
            f"for _, inst in ipairs(node:GetDescendants()) do\n"
            f"    if inst:IsA('LuaSourceContainer') then\n"
            f"        table.insert(paths, inst:GetFullName())\n"
            f"        n = n + 1\n"
            f"        if n >= 500 then break end\n"
            f"    end\n"
            f"end\n"
            f"return table.concat(paths, '\\n')"
        )
        entry = self._invoke("execute_luau", {
            "datamodel_type": "Edit",
            "code": code,
        })
        texts = entry.get("result") or []
        text = texts[0] if texts else ""
        if entry.get("is_error"):
            raise RuntimeError(f"MCP list failed for {root!r}: {text[:200]}")
        if text == "__MISSING__":
            return []
        paths = [p for p in text.split("\n") if p]
        if glob and glob not in ("*", ""):
            import fnmatch
            paths = [
                p for p in paths
                if fnmatch.fnmatch(p.rsplit(".", 1)[-1], glob)
            ]
        return sorted(paths)

    def list_with_stat(self, root: str = "", glob: str = "*") -> list[tuple[str, int, int]]:
        """Like `list`, but returns (path, size_bytes, lines) per module in one call.

        Avoids N separate round-trips for `list_files show_size=True`.
        """
        root_norm = self._normalize(root).strip(".") if root else ""
        expr = f"game.{root_norm}" if root_norm else "game"
        code = _lua_script("list_with_stat", expr=expr)
        entry = self._invoke("execute_luau", {
            "datamodel_type": "Edit",
            "code": code,
        })
        texts = entry.get("result") or []
        text = texts[0] if texts else ""
        if entry.get("is_error"):
            raise RuntimeError(f"MCP list_with_stat failed for {root!r}: {text[:200]}")
        if text == "__MISSING__":
            return []
        rows: list[tuple[str, int, int]] = []
        for line in text.split("\n"):
            if not line:
                continue
            parts = line.rsplit("|", 2)
            if len(parts) != 3:
                continue
            try:
                size = int(parts[1])
                lines = int(parts[2])
            except ValueError:
                continue
            rows.append((parts[0], size, lines))
        if glob and glob not in ("*", ""):
            import fnmatch
            rows = [
                r for r in rows
                if fnmatch.fnmatch(r[0].rsplit(".", 1)[-1], glob)
            ]
        return sorted(rows, key=lambda r: r[0])


    def delete(self, path: str) -> None:
        norm = self._normalize(path)
        code = (
            f"local ok, t = pcall(function() return game.{norm} end)\n"
            f"if not ok or t == nil then return '__MISSING__' end\n"
            f"t:Destroy()\n"
            f"return '__OK__'"
        )
        entry = self._invoke("execute_luau", {
            "datamodel_type": "Edit",
            "code": code,
        })
        texts = entry.get("result") or []
        text = texts[0] if texts else ""
        if entry.get("is_error"):
            raise RuntimeError(f"MCP delete failed for {path}: {text[:200]}")
        if text == "__MISSING__":
            raise FileNotFoundError(path)
        if text != "__OK__":
            raise RuntimeError(f"unexpected delete response for {path}: {text[:120]}")

    def move(self, src: str, dst: str) -> None:
        src_norm = self._normalize(src)
        dst_norm = self._normalize(dst)
        if "." not in dst_norm:
            raise ValueError(f"dst must be nested path like Parent.Name, got {dst!r}")
        dst_parent, dst_name = dst_norm.rsplit(".", 1)
        if not dst_name:
            raise ValueError(f"dst missing new name: {dst!r}")
        safe_name = json.dumps(dst_name, ensure_ascii=False)
        code = (
            f"local ok1, s = pcall(function() return game.{src_norm} end)\n"
            f"if not ok1 or s == nil then return '__SRC_MISSING__' end\n"
            f"local ok2, p = pcall(function() return game.{dst_parent} end)\n"
            f"if not ok2 or p == nil then return '__DST_PARENT_MISSING__' end\n"
            f"local ok3, existing = pcall(function() return game.{dst_norm} end)\n"
            f"if ok3 and existing ~= nil then return '__DST_EXISTS__' end\n"
            f"local clone = s:Clone()\n"
            f"clone.Name = {safe_name}\n"
            f"clone.Parent = p\n"
            f"s:Destroy()\n"
            f"return '__OK__'"
        )
        entry = self._invoke("execute_luau", {
            "datamodel_type": "Edit",
            "code": code,
        })
        texts = entry.get("result") or []
        text = texts[0] if texts else ""
        if entry.get("is_error"):
            raise RuntimeError(f"MCP move failed for {src} -> {dst}: {text[:200]}")
        if text == "__SRC_MISSING__":
            raise FileNotFoundError(f"source not found: {src}")
        if text == "__DST_PARENT_MISSING__":
            raise FileNotFoundError(f"destination parent not found: {dst_parent}")
        if text == "__DST_EXISTS__":
            raise FileExistsError(f"destination already exists: {dst}")
        if text != "__OK__":
            raise RuntimeError(f"unexpected move response: {text[:120]}")

    def copy(self, src: str, dst: str) -> None:
        """Clone a DataModel instance. Source is preserved."""
        src_norm = self._normalize(src)
        dst_norm = self._normalize(dst)
        if "." not in dst_norm:
            raise ValueError(f"dst must be nested path like Parent.Name, got {dst!r}")
        dst_parent, dst_name = dst_norm.rsplit(".", 1)
        if not dst_name:
            raise ValueError(f"dst missing new name: {dst!r}")
        safe_name = json.dumps(dst_name, ensure_ascii=False)
        code = (
            f"local ok1, s = pcall(function() return game.{src_norm} end)\n"
            f"if not ok1 or s == nil then return '__SRC_MISSING__' end\n"
            f"local ok2, p = pcall(function() return game.{dst_parent} end)\n"
            f"if not ok2 or p == nil then return '__DST_PARENT_MISSING__' end\n"
            f"local ok3, existing = pcall(function() return game.{dst_norm} end)\n"
            f"if ok3 and existing ~= nil then return '__DST_EXISTS__' end\n"
            f"local clone = s:Clone()\n"
            f"clone.Name = {safe_name}\n"
            f"clone.Parent = p\n"
            f"return '__OK__'"
        )
        entry = self._invoke("execute_luau", {
            "datamodel_type": "Edit",
            "code": code,
        })
        texts = entry.get("result") or []
        text = texts[0] if texts else ""
        if entry.get("is_error"):
            raise RuntimeError(f"MCP copy failed for {src} -> {dst}: {text[:200]}")
        if text == "__SRC_MISSING__":
            raise FileNotFoundError(f"source not found: {src}")
        if text == "__DST_PARENT_MISSING__":
            raise FileNotFoundError(f"destination parent not found: {dst_parent}")
        if text == "__DST_EXISTS__":
            raise FileExistsError(f"destination already exists: {dst}")
        if text != "__OK__":
            raise RuntimeError(f"unexpected copy response: {text[:120]}")

    # --- filter ------------------------------------------------------------

    def execute(self, code: str, datamodel_type: str = "Edit") -> str:
        """Run arbitrary Luau code via MCP and return the first text result.

        Raises RuntimeError on is_error. Transient states are retried by
        _invoke. Useful for creating instances and other low-level ops that
        don't yet have a dedicated MCPBackend method.
        """
        entry = self._invoke("execute_luau", {
            "datamodel_type": datamodel_type,
            "code": code,
        })
        texts = entry.get("result") or []
        text = texts[0] if texts else ""
        if entry.get("is_error"):
            raise RuntimeError(f"execute_luau failed: {text[:200]}")
        return text

    def invoke_native(self, name: str, args: dict):
        """Invoke a native MCP tool by name.

        Returns Result on success/error, or None if the tool is not known
        to this backend (Patcher then falls through to "unknown action").

        Native tools bypass path policy entirely: the Roblox DataModel has no
        filesystem paths, and pretending otherwise would create a false sense
        of safety (a native tool can modify anything). Access is gated by
        `native_tools_enabled` and, if provided, `native_tools_allow`.
        """
        from ..core.models import Result
        if not self.native_tools_enabled:
            return Result(
                status="blocked",
                message=("native MCP tools disabled "
                         "(mcp.native_tools.enabled=false)"),
                action=name,
                error_code="native_tools_disabled",
            )
        allow = self.native_tools_allow
        if allow is not None and name not in allow:
            return None
        try:
            entry = self._invoke(name, args or {})
        except Exception as e:
            return Result(
                status="error",
                message=f"native tool {name!r} failed: {e}",
                action=name,
                error_code="native_error",
            )
        texts = entry.get("result") or []
        text = texts[0] if texts else ""
        if entry.get("is_error"):
            return Result(
                status="error",
                message=f"[native] {name}: {text[:500]}",
                action=name,
                error_code="native_error",
            )
        return Result(
            status="ok",
            message=f"[native] {name}: {text}",
            action=name,
        )


    def filter_check(self, path: str, op: str) -> str | None:
        """No path-level filtering for Roblox DataModel.

        Roblox paths are not filesystem paths and cannot be enforced the same
        way. Worse: with native MCP tools enabled, any path policy on the
        unified tools would be trivially bypassed, creating a false sense of
        safety. Access to Roblox is gated at the backend level instead:

          - mcp backend disabled in config, or
          - native_tools_enabled=false (blocks native passthrough).

        Returning None unconditionally is intentional.
        """
        return None

    # --- internals ---------------------------------------------------------

    @staticmethod
    def _normalize(path: str) -> str:
        p = path.strip()
        if p.startswith("game."):
            p = p[5:]
        return p

    def _reader_loop(self, stream) -> None:
        try:
            for line in iter(stream.readline, ""):
                if self._stop.is_set():
                    break
                # All bridge stdout is informational after startup; log it
                # to stderr with a prefix so timing/trace lines are visible.
                # Lines starting with "[bridge.timing]" or "[bridge]" are
                # useful for diagnostics; startup banner lines were already
                # consumed by _wait_ready (they go to the queue first, then
                # we still mirror them below for completeness).
                try:
                    sys.stderr.write(f"[bridge] {line}")
                    sys.stderr.flush()
                except Exception:
                    pass
                self._stdout_q.put(line)
        except Exception:
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _stderr_loop(self, stream) -> None:
        try:
            for line in iter(stream.readline, ""):
                if self._stop.is_set():
                    break
                sys.stderr.write(f"[mcp] {line}")
                sys.stderr.flush()
        except Exception:
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _append_timing(self, msg: str) -> None:
        """Write a timing line to both stderr and toolkit/runtime/logs/mcp_timings.log."""
        try:
            sys.stderr.write(msg + "\n")
            sys.stderr.flush()
        except Exception:
            pass
        try:
            from pathlib import Path as _P
            log_path = _P(__file__).resolve().parents[3] / "runtime" / "logs" / "mcp_timings.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            import datetime as _dt
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"{_dt.datetime.now().isoformat()}  {msg.strip()}\n")
        except Exception:
            pass

    def _wait_ready(self, timeout: float) -> str:
        deadline = time.time() + timeout
        buf: list[str] = []
        while time.time() < deadline:
            try:
                line = self._stdout_q.get(timeout=0.5)
            except queue.Empty:
                if self._proc is None or self._proc.poll() is not None:
                    raise RuntimeError(
                        f"bridge exited during startup (code={self._proc.poll() if self._proc else '?'}):\n"
                        + "".join(buf)
                    )
                continue
            buf.append(line)
            if "Мост готов" in line:
                return "".join(buf)
        raise TimeoutError(
            f"bridge did not become ready in {timeout}s:\n" + "".join(buf)
        )

    def _invoke(self, tool, args, timeout=None):
        attempts = max(1, self.max_retries + 1)
        last_entry: dict = {}
        for attempt in range(1, attempts + 1):
            last_entry = self._invoke_once(tool, args, timeout)
            if not self._is_transient(last_entry):
                return last_entry
            text = (last_entry.get("result") or [""])[0]
            sys.stderr.write(
                f"[mcp] transient studio state (attempt {attempt}/{attempts}): {text[:120]}\n"
            )
            sys.stderr.flush()
            if attempt < attempts:
                time.sleep(self.retry_delay)
        return last_entry

    def _is_transient(self, entry):
        if not entry.get("is_error"):
            return False
        texts = entry.get("result") or []
        text = texts[0] if texts else ""
        for marker in STUDIO_TRANSIENT_MARKERS:
            if marker in text:
                return True
        return False

    def _wait_studio_ready(self, timeout):
        deadline = time.time() + timeout
        last_err = ""
        while time.time() < deadline:
            try:
                entry = self._invoke_once("execute_luau", {
                    "datamodel_type": "Edit",
                    "code": "return '__studio_ready__'",
                }, timeout=min(30.0, timeout))
            except Exception as e:
                last_err = str(e)
                time.sleep(1.0)
                continue
            if not entry.get("is_error"):
                texts = entry.get("result") or []
                if texts and "__studio_ready__" in texts[0]:
                    return
            else:
                texts = entry.get("result") or []
                last_err = texts[0][:200] if texts else "unknown"
            time.sleep(1.0)
        raise RuntimeError(
            f"Studio not ready after {timeout}s. Last state: {last_err}"
        )

    def _invoke_once(self, tool, args, timeout=None):
        if self._proc is None or self._proc.poll() is not None:
            raise RuntimeError("bridge not alive")
        t = timeout if timeout is not None else self.call_timeout

        with self._lock:
            if self.outputs_file.exists():
                try:
                    self.outputs_file.unlink()
                except Exception:
                    pass

            self.patch_file.parent.mkdir(parents=True, exist_ok=True)
            self.patch_file.write_text(
                json.dumps({"tool": tool, "arguments": args}, ensure_ascii=False),
                encoding="utf-8",
            )

            try:
                self._proc.stdin.write("accept\n")
                self._proc.stdin.flush()
            except Exception as e:
                raise RuntimeError(f"cannot write to bridge stdin: {e}")

            deadline = time.time() + t
            while time.time() < deadline:
                if self._proc.poll() is not None:
                    raise RuntimeError("bridge died while waiting for outputs")
                if self.outputs_file.exists():
                    try:
                        raw = self.outputs_file.read_text(encoding="utf-8").strip()
                        if raw:
                            data = json.loads(raw)
                            if isinstance(data, list) and data:
                                return data[0]
                    except (json.JSONDecodeError, OSError):
                        pass
                time.sleep(0.1)
            raise TimeoutError(f"no valid outputs.json for {tool} after {t}s")
