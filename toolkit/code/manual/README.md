# Manual smokes

Standalone scripts for interactive testing against a **live Roblox Studio**.

They are not part of `TOOL_MAP` and not registered in `run_all.py`. Run them by hand when Studio is open:

```
python toolkit/manual/mcp_smoke.py
python toolkit/manual/mcp_write_smoke.py
python toolkit/manual/mcp_lua_smoke.py
python toolkit/manual/mcp_lua_index_smoke.py
python toolkit/manual/lua_index_via_lua.py
python toolkit/manual/lua_parser_in_studio.py
python toolkit/manual/lua_parser_smoke.py
python toolkit/manual/parity_check.py
python toolkit/manual/verify_grep_replace_mcp.py
python toolkit/manual/verify_grep_replace_mcp_errors.py
```


See each file's docstring for what it does.

## Not to be confused with

- `toolkit/tests/` — automated, run by `run_all.py` (no Studio required).
- `toolkit/tests/smoke_fs.py`, `toolkit/tests/smoke_patcher.py` — these are automated despite the name; they exercise the FS backend, not MCP.
