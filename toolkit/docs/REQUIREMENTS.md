# Requirements

<!-- summary: What the toolkit exists to solve; design targets and non-goals. -->
<!-- tags: requirements, design -->

Every feature in the toolkit must serve at least one of the requirements
below. A feature that does not is out of scope.

## 1. Patch outcome is answerable without a follow-up read
<!-- summary: After a patch, "did it apply and what changed" is in the result itself. -->

After a patch runs, the answer to *did it actually apply, and what
changed?* must be readable from the result — not from a second
`read_file`.

**Solved by:** structural `Delta` on every write result (lines / bytes /
occurrences), and the index diff rendered by `rebuild_index` /
`rebuild_code_index`. The `##RESULT:` marker carries the aggregate. No
round-trip required to know whether the file changed.

**Rationale:** the bridge (`multi_edit`, `script_read`) can report
`applied` while `.Source` was never written. A second read per patch
doubles the API cost and still only catches the case where the caller
remembers to ask.

## 2. Edits do not depend on text search or line numbers
<!-- summary: Every write targets a structural unit — section, symbol, or anchor block. -->

Every write targets a structural unit:

- a unit — markdown section, function, method, class — by qualname (`replace_unit`),
- a numbered block inside a unit's body (`replace_unit(block=...)`, `insert_block`),
- a delimited block between two anchors (`replace_between`),
- a position relative to an anchor (`insert_at_anchor`).

Text search (`replace_in_file`) and line ranges (`replace_range`) exist
as fallbacks for formats without a parser. They are not the default path.

**Rationale:** whitespace, escapes (`\u0413` ≠ `Г` in byte match),
and shifting line numbers make text search unreliable at scale. A bad
match corrupts the file silently; a bad structural call fails loudly.

## 3. Current map of the project for reconnaissance-free decisions
<!-- summary: Indexes list sections/symbols/sizes/summaries; refreshed on every structural change. -->

An up-to-date index — markdown sections, Python symbols, Lua symbols —
with size, line range, summary, and staleness markers, available at the
start of a session and refreshed after every structural change.

**Solved by:** `INDEX.md` (docs), `CODE_INDEX.md` + manifest (Python),
`CODE_INDEX_LUA.md` (Lua), all versioned with `[vN]` and a diff from the
previous rebuild.

**Rationale:** without a map, adding a feature to a large project costs
dozens of search queries and still misses sections. With one, the LLM
knows what to read before reading it.

## 4. Tool ordering reflects reliability
<!-- summary: Structural > anchor > text search > line ranges; documented explicitly. -->

The more reliable tool is the default; the less reliable one is
documented as a fallback. Order: structural (section / symbol) → anchor
(`replace_between`, `insert_at_anchor`) → text search
(`replace_in_file`) → line ranges (`replace_range` with
`expected_first_line` as a guard).

New LLM sessions receive this ordering explicitly in `LLM_START.*.md`.

## 5. Staleness is tracked, not assumed
<!-- summary: `⚠ stale` is computed from content hashes, not from write-tool discipline. -->

A section's summary is marked `⚠ stale` when the body changed after the
summary was last verified. The check runs on rebuild, using content
hashes in a sidecar (`.index_meta.json`), so it does not depend on any
write tool remembering to update state.

- `set_annotation` clears it by changing the summary text (new
  `summary_hash`).
- Clearing it without touching the file (the old `verify_section`) is
  **not implemented** in the current unit model — an open task.

## 6. Extension seams hold without architectural breakage
<!-- summary: Six extension points the architecture must support without breaking: Rojo, new indexes, Unity bridge, new tools, headless, agent mode. -->

Architecture must absorb future extensions without breaking changes. Six
points, ordered by proximity:

| # | Seam | Status | What changes on add |
|---|---|---|---|
| 1 | Rojo + Luau over FS | holds | `LuauBackend` implements `Backend`; `rebuild_lua_code_index` gets a factory (`mcp` vs `rojo`). |
| 2 | New indexes (e.g. `cs`) | holds w/ prep | Add `Format`, indexer, tool, router entry. `GetStatusTool.set_context(index_paths=)` currently fixed to 3 keys — accept iterable of `(kind, path)`. |
| 3 | Unity bridge (MCP-like) | holds w/ prep | Extract `BridgeBackend` base + `RobloxSpec`/`UnitySpec`. 80% of `MCPBackend` (patch.json/outputs.json protocol, retry, verify) is domain-agnostic. `build_backend_for_config` → registry of builders. |
| 4 | New tools | holds | `TOOL_MAP` is a dict; `patch_runner.apply_patch` takes it as argument. |
| 5 | Headless (no GUI) | holds | `patch_runner.apply_patch`, `presenters/*` are Tk-free; CLI proven end-to-end. |
| 6 | Agent mode (LLM drives tools directly) | holds | `apply_one(session, action, *, notify)` alongside `apply_patch`. `notify(kind, payload)` is the streaming seam: `notify("tool_result", result)` per action. |

**What “holds” means.** Adding the seam touches one place (tool / backend
/ registry), existing code compiles and runs unchanged. New domains slot
into `Backend` / `Format` / `Tool` protocols; nothing in `core/` or
`patch_runner.py` needs modification.

**What “holds w/ prep” means.** A preparatory change is recommended
before the extension lands, but it is small and localized. The extension
itself does not require refactoring of unrelated code.

## Goals (how success is measured)
<!-- summary: Three things we want to improve over the pre-index era. -->

- **Minimize reconnaissance.** Fewer read/grep calls before the first
  edit.
- **Increase information coverage.** Nothing important missed — indexes
  list all sections, not just recent ones; symbol trees include nested
  functions and methods.
- **Minimize token cost.** Smaller payloads for the same coverage: read
  by section, not by whole file; diffs instead of re-reads.

## Non-goals
<!-- summary: Deliberately out of scope. -->

- Concurrent sessions. One `Session` = one `Backend`.
- Concurrent patches. One patch at a time.
- Session persistence across GUI restarts. The bridge restarts with the
  GUI.
- A parser for exotic formats. Text search is the fallback there.
