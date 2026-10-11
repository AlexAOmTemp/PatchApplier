# Patch Applier — Starter Guide for LLMs

## 1. What this is and why
<!-- summary: Patch Applier is a JSON-patch tool over four sources (Docs, Python, Luau code, Roblox scene); Luau code lives in one of two modes (MCP/Rojo); index as map, structural units, deterministic result. -->
<!-- tags: overview, purpose -->

**Patch Applier** lets an LLM work on a project through **JSON patches**: one LLM reply = a list of actions, each a read or an edit. Patches apply to four sources: **Docs** and **Python** live on disk; **Luau code** lives either on disk (Rojo mode) or in Studio (MCP mode); the **Roblox scene** (Parts, GUI, Folders) always lives in Studio and is reached through the MCP bridge. The user picks the Luau mode; it is fixed in the status line `luau:`.

**Axis: where Luau code lives.** Two mutually exclusive modes:

- **MCP mode** (`luau: mcp`) — code in Studio, instance `.Source`; path like `Service.X.Y`; edits go through the bridge.
- **Rojo mode** (`luau: rojo`) — source of truth is `.luau` on disk; ordinary filesystem paths; edits go through the same AST tools as Python. A copy of the code exists in Studio but **mirrors the disk** and is not the source of truth.

**`MCP` ≠ `Roblox`.** MCP is the transport to the Studio DataModel. A Roblox path `Service.X.Y` is a marker of MCP mode. The scene (Parts, GUI, Folders) goes through MCP in both modes — orthogonal to the Luau-code mode. Docs and Python always live on disk; the mode does not touch them.

Three load-bearing ideas:

1. **Index as map.** `INDEX.md` (docs), `CODE_INDEX.md` (Python), `CODE_INDEX_LUA.md` (Luau) list every file, its sections/symbols, size, line range, summary, and the import graph. You decide what to read from the index, without opening the whole project. Markers (`◉`, `← N imp`, `→ N users`, `⚠ large`, `⚠ cycle`, `[tests/]`, `[vendor/]`) are facts about a file; see §10. The index is rebuilt after every structural change.

2. **A unit model, not text or line numbers.** An edit is addressed by unit (wholesale, or one of its parts `head`/`annotation`/`body`), or by a block inside body. The model is the same for `.py`, `.lua`, `.md`. Text tools (`replace_in_file`, `replace_between`) are for what the model does not address (comments, individual lines). Not by line `N`, not by a substring. This removes failures caused by whitespace, escapes, and line-number drift.

3. **Deterministic result.** After a patch you get a structural `Result` (delta, error_code, `##RESULT`) and an index diff — "what applied and what changed" with no second read.

More on requirements — `docs/REQUIREMENTS.md`. Internal design — `docs/ARCHITECTURE.md`.

**What arrives in the starter message.** At the very bottom of this starter text the first `get_status` snapshot is attached — the active backend, index versions, path policy, and the `run_python` flag. Read it first: it tells you what is available in this session before you spend a request. You can request a fresh status at any time via the `get_status` action.

## 2. How to read this document
<!-- summary: This file covers the toolkit; Roblox code rules and bridge rules are optional addenda below; toolkit wins on conflict. Tool priority: unified tools first, native bridge tools only when no unified one exists. -->
<!-- tags: nav, reading-order -->

This file describes the **toolkit**. Three blocks follow, in this order:

1. **This document (LLM_START).** Patch format, tools, strategies, error codes. Always applicable.

2. **`RobloxCodeRules.md` (optional).** Appears below when the user enables Roblox mode. Roblox code rules: Edit vs Play, `script_read` vs `.Source`, constraints, UI layout, JSON escaping, and other common pitfalls.

3. **`MCPBridgeRules.md` (optional).** Also Roblox mode. Working with the manual bridge chat↔Studio: native call formats, `multi_edit` / `execute_luau` / `script_read`, known bridge bugs and workarounds.

**Precedence.** If a rule from an optional addendum conflicts with a toolkit rule — **the toolkit rule wins**. Addenda describe **what** to write in a patch (domain); the toolkit describes **how** the patch is applied.

**Reading order with Roblox mode on.** "What this is" → "Paradigm" (how to build patches) → `RobloxCodeRules.md` → `MCPBridgeRules.md` → "Strategies" and "Error codes" as needed.

**If Roblox mode is off** — read this document only; no addenda will follow.

**Tool priority.** Always prefer **unified toolkit tools** — the unit model (`list_units`, `read_unit`, `replace_unit`, `replace_block`, `delete_block`, `insert_block`, `set_annotation`); call graph and module search (`find_symbol`, `find_usages`, `symbol_graph`, `copy_unit`); text escape hatch (`read_file`, `grep`, `replace_in_file`, `replace_between`, `insert_at_anchor`, `replace_range`); indexes and execution (`rebuild_index`, `rebuild_code_index`, `rebuild_lua_code_index`, `get_status`, `get_index`, `run_python`). They are covered by path policy, logged, pass verify-after-write, and **handle backend quirks themselves** — including known bridge bugs: the toolkit hides those inside, you never work around them by hand.

**Native MCP bridge tools** (`multi_edit`, `execute_luau`, `script_read`, `search_game_tree`, `insert_asset`, `generate_mesh`, `inspect_instance`, `http_get`, ...) are for cases **where no unified tool exists** for the operation. That covers:

- direct work with instance properties and the DataModel (`execute_luau`);
- generative tools (`generate_mesh`, `generate_material`, `segment_mesh`, `generate_texture`, `generate_procedural_model`);
- operations with no toolkit equivalent (`search_asset`, `insert_asset`, `inspect_instance`, `http_get`, `list_roblox_studios`).

If a unified tool solves the task — **do not** switch to a native one, even if the native looks simpler. "Simpler" here means "no policy, no verify, no log".

**Example of the conflict.** `MCPBridgeRules.md` §5 says: "edits to existing `Script.Source` go through `execute_luau` + `string.gsub`". That rule applies to **native** calls. Unified `replace_unit` / `replace_block` do exactly that internally — you do not write gsub by hand. The toolkit wins: use `replace_unit` / `replace_block`; `execute_luau`+gsub only for a chunk of `.Source` with no structural tool of its own.

**The schemas live in different places.** Unified tools are listed in this document (§Available actions). Native tools are in `tools_schema.json`, attached to the starter text when the user enabled `mcp.native_tools.enabled`. If the gate is off, a native call returns `error_code="native_tools_disabled"` — that is a gate, not an error.

## 3. Contents
<!-- summary: Map of LLM_START plus contents of the two optional addenda (RobloxCodeRules, MCPBridgeRules). -->
<!-- tags: nav, contents -->

> **This document:**
>
> 1. What this is and why
> 2. How to read this document
> 3. Contents
> 4. First steps in a new session
> 5. Patch format
> 6. Paradigm: work through structural units
> 7. Available actions
> 8. Index versions and diffs
> 9. Markdown document format
> 10. Index markers
> 11. Strategies
> 12. What to remember
> 13. Error codes
> 14. What not to do
> 15. Where to start
> 16. Patch examples
>
> **Optional addenda** (appear below the `---` marker, only in Roblox mode):
>
> - `RobloxCodeRules.md` — Roblox code rules: common pitfalls, Edit vs Play, constraints, UI, JSON escaping.
> - `MCPBridgeRules.md` — manual bridge chat↔Studio: call formats, `multi_edit`/`execute_luau`/`script_read`, known bridge bugs.

## 4. First steps in a new session

**1. Check the project status.**

The user's starter message normally already contains the output of `get_status` — produced by the "Starter Text" button in the GUI. **The snapshot describes the session configuration, not runtime.** Live bridge state is not part of the snapshot: the LLM works asynchronously (a human may apply a patch an hour or a day later), and a live status would be stale. If the bridge is down, a patch will fail with `backend_not_ready`, and the LLM will honestly report "Studio is not connected". What matters in the snapshot:

- `backend` — `filesystem` / `mcp` / `composite`.
- `luau:` — **where the Luau code lives**: `mcp` (Studio, `.Source`) or `rojo` (disk, `.luau`). Determines path format and edit backend (see §1).
- The list of indexes with versions `[vN]`.
- `## Policy Filesystem` — policy for **filesystem paths only** (docs, Python, `.luau`-on-disk in Rojo mode).
- `## MCP` — policy for the Studio DataModel. Filesystem policy does **not** apply to `Service.X.Y` paths.
- The `run_python` flag.

If the status is not in the starter message, request it yourself:

```json
[{"id": 1, "action": "get_status", "arguments": {}}]
```

**Policy flags.** In the `## Policy Filesystem` block each path carries a flag list: `R` = read, `W` = write, `I` = index. `[RW]` — read and write allowed, index not; `[RWI]` — all three; `[]` — all denied. An operation is `■ blocked` if its flag is not in the list for that path. The three policy dictionaries are independent: read permission does not imply write or index permission. A path may be declared in policy even if the directory does not physically exist on disk — policy is declarative.

**2. Fetch the index:**

```json
[{"id": 1, "action": "get_index", "arguments": {"kind": ["docs", "code"]}}]
```

`kind` is `docs` / `code` / `lua`, or a list. **`kind` is required** — do not request everything at once; pick a domain explicitly. The index is returned in full; `max_bytes` is an optional ceiling for when the response would be enormous.

The index is the map of the world: files, sections, line ranges, sizes, dependencies. Use it to find what to read and where. Don't read whole files without need.

## 5. Patch format

**Every action requires an `id`.** Any value — number, string, `null`. The type is not validated; it is used purely as a label to correlate your action with the response.

```json
[{"id": 1, "action": "read_file", "arguments": {"file_path": "a.py"}}]
[{"id": 2, "action": "replace_in_file", "arguments": {...}}]
[{"id": "fix-import", "action": "replace_symbol", "arguments": {...}}]
```

**Format is groups.** Each action in its own `[...]`; groups go one after another. The separator (newline or comma) does not matter. A single action is also one group.

**One fence for the whole patch, not per group.** Put the whole reply in one fence with all groups inside. **Do not wrap each `[...]` in its own fence** — that splits the patch into several documents on the user's side, which have to be copied one by one. Correct shape:

- one fence, all groups inside, each group with its own `[...]`;
- or no fence at all;
- one fence per group is a mistake — it breaks copying.

**One action — one group.** Never merge several actions into a single array. Groups give independence (see below).

**Why groups.** Each group parses independently. An error in one group (missing comma, bracket, unclosed quote, missing `id`) **does not affect the others**: valid actions apply, the problem group is ignored and described in the `=== Compiler messages ===` block after the log.

**What the compiler shows.** Exactly compiler-style, `line N, col M` — three kinds of messages.

| kind | when | what to do |
|---|---|---|
| `syntax` | fragment does not parse as JSON | check commas, brackets, quote escaping on the given line and column |
| `missing_id` | valid JSON object but no `id` field | add `id` — any unique value |
| `duplicate_id` | two actions share the same `id` | not an error: both applied, but the label is now ambiguous |

Example output:

```
[1] ✓ read_file toolkit/code/toolkit/__init__.py
[2] ✓ replace_in_file toolkit/code/toolkit/core/patchparse.py
[4] ✓ read_file toolkit/docs/DECISIONS.md

=== Compiler messages ===
  line 9, col 105      syntax: Expecting ',' delimiter
  line 15, col 3       missing_id: object has no 'id' field
  line 27, col 3       duplicate_id: id=4 already seen at line 21
```

**Per-action results:** `✓ ok` / `✗ error` / `■ blocked` (policy or sandbox) / `– skipped` (unknown action or missing arguments). The `[N]` prefix is your `id`, not the position in the patch. If `id` is missing, the parser substitutes the position, but under the new format that is always a `missing_id` error.

**The `##RESULT:{...}` marker** — structured summary:

```json
{"ok": N, "errors": N, "skipped": N, "failed": [<indices>], "blocked": [<indices>], "diagnostics": [...]}
```

`failed` and `blocked` are action numbers (1-based within this patch) that ended as `error` / `blocked`. `diagnostics` appears only when there are compiler messages.

By construction `errors == len(failed)` — `errors` is a counter, `failed` is the list of the same indices. There is no separate `blocked_count`. The marker prefix is exactly `##RESULT:` (with a colon).


## 6. Paradigm: work through structural units

**The main rule: edit files through structural units, not through text and not by line numbers.**

The tools `replace_range` (by line numbers) and `replace_in_file` (by text) exist, but they are **unreliable** and often crash patches:

- **`replace_range`** — line numbers shift after any previous edit. Several `replace_range` calls on the same file in one patch easily delete the wrong block. Extra protection — the `expected_first_line` parameter: if the text at `start_line` does not match, the patch fails with `content_mismatch` and **the file is not touched**.
- **`replace_in_file`** — fails on whitespace, indentation, invisible characters; the same string may appear in several places, `occurrence` helps but is not always enough. A separate pitfall is escapes: `\u0413` in JSON and the character `Г` in the source produce the same text, but `replace_in_file` matches **file bytes**, and `\u0413` is not there.

For **every supported format** (`.py`, `.lua`, `.luau`, `.md`) use the unit model: `read_unit` / `replace_unit` / `replace_block` / `delete_block` / `insert_block` / `set_annotation`. Address by qualname (Python/Lua) or `section_number` / `section_title` (md); parts `head` / `annotation` / `body`; blocks inside body. These tools recompute positions from the AST or the document structure and are independent of prior edits.

**Text escape hatch** (`replace_between`, `replace_in_file`, `insert_at_anchor`, `replace_range`) — only for what the unit model does not address: comments between units, individual lines inside a statement, files without a parser, fenced blocks inside md.

**Text tools work on any source.** `replace_in_file`, `replace_range`, `replace_between`, `insert_at_anchor` are format-agnostic — they operate on the text that `read_file` returned (for Roblox paths, `.Source`). On Roblox they apply exactly as on `.md`/`.py`.

**Exact read → exact replace (`escape=perline` + `search_repr`).** By default `read_file` returns **per-line repr**: every line is its own Python literal with a line number (`45: 'def foo():   \n'`). Everything invisible is visible — `\n` vs `\r\n`, trailing whitespace, tabs — and line numbers are still there. Copy the line (or several consecutive lines for a multi-line `search`) into `replace_in_file` — the tool unwraps the literal via `ast.literal_eval` and matches **exact bytes**.

Two `read_file` axes: `numbered` (default `true` — `N: ` prefix) and `escape` (`perline` default / `blob` / `none`). `blob` — the whole fragment as one literal (handy for copying a multi-line `search`); `none` — raw text, no escaping (for reading to understand). `numbered=true` + `escape=blob` is an error. CRLF is preserved: if the file had `\r\n`, the edit keeps `\r\n`.

**⚠ Path format depends on the Luau mode.** In MCP mode (`luau: mcp`), a Roblox path uses dot-notation: `ReplicatedStorage.X.Y`, first segment is a service name. In Rojo mode (`luau: rojo`), Luau files are addressed by filesystem path, like `.py` modules (`src/ServerScriptService/Foo/init.luau`).

**⚠ Names with dots/special chars (MCP mode only).** In `luau: mcp` a dot is a **separator**. If **one instance name** contains `.`, `-`, `@` or whitespace, the path cannot be read (`read_file`, `read_unit`, `file_exists`, `grep_mcp`). This is a Luau limitation (identifier = `[A-Za-z0-9_]`), not the toolkit's. Typical case — Wally packages under `_Index`. Workaround: `inspect_instance` or reading from disk.

**⚠ Open Studio tabs.** If the user keeps a Roblox module open in the Studio editor, saving from the editor (Ctrl+S or closing the tab) writes the editor buffer back to `.Source`, overwriting LLM changes. Before patching a Roblox module, **ask the user whether the tab is closed**; if open, ask them to close it. After the patch, if the tab was open, ask them to reopen it to sync the buffer with `.Source`.

Keep `replace_range` and `replace_in_file` for cases where no structural tool exists: a one-off edit inside the module-level top region of a Python file, exotic formats without a parser, or replacing exactly one line with guaranteed-unique text.

## 7. Available actions

### Reading

| Action | Arguments |
|---|---|
| `read_file` | `file_path` + one of: `section_number` (`"4"`, `"4.1"`), `section_title` (substring), `start_line`+`end_line`; otherwise the whole file. Optional `numbered` (default `true`), `escape` (default `perline`), `max_bytes`. Legacy `raw` (`repr`/`text`/`numbered`) is accepted |
| `file_stat` | `file_path` — size and section breakdown |
| `file_exists` | `file_path` |
| `list_files` | `directory`, optional `show_size` |
| `grep` | `pattern` + (`paths`: list / `directory`+`file_glob`); `regex=true` by default, `fixed_strings` for a literal substring; optional `ignore_case`, `before`, `after`, `max_results`, `exclude_glob`. **Filesystem only.** Roblox path → `wrong_domain` error, use `grep_mcp` |
| `grep_mcp` | `pattern` + `directory` (Roblox path: **a module or a folder** — if it is the script itself, it is searched too); optional `fixed_strings` (default `false`), `ignore_case` (only with `fixed_strings=true`), `before`, `after`, `max_results` (default 200). **Roblox only.** Single `execute_luau` for the whole search. Pattern is **Lua patterns**, not Python regex: `%d`, `%w`, `%.`, `.-` (lazy). For `\d`, `\w`, `\b`, `|`, groups — use `grep` over exported code, or a simple literal |

**`Result` fields.** `status` (`ok` / `error` / `skipped` / `blocked`), `message`, `delta` (for write tools, `None` for reads), `verified` (`bool` for write tools with read-after-write, `None` otherwise), `error_code`, `action`.

`read_file` with no arguments reads the whole file — only for small ones. For a section inside a multi-file index use `section_number` (numbers are more reliable than titles: titles can repeat).

**About `grep`.** `paths` is a list of **files**, not directories; a directory in `paths` silently becomes "skipped files". For recursion use `directory` + `file_glob`. By default `regex=true` — `pattern` is treated as a regular expression. For a literal substring pass `fixed_strings=true` (in that mode `regex` is ignored).

### Writing (text tools, escape hatch)

**Escape hatch for what the unit model does not address** — comments between units, individual lines inside a statement, files without a parser, fenced blocks inside md. For anything addressable as a unit or block — use the unit tools (§Unit operations).

| Action | Arguments |
|---|---|
| `replace_in_file` | `file_path`, `search`, `replace`, optional `occurrence` (number or `"all"`), `search_repr` (default `true`), `regex` (default `false`) |
| `replace_range` | `file_path`, `start_line`, `end_line`, `new_content`, **strongly recommended** `expected_first_line` |
| `replace_between` | `file_path`, `start_anchor`, `end_anchor`, `new_content`, optional `include_start` (`true`), `include_end` (`true`), `occurrence` (`1`) |
| `insert_at_anchor` | `file_path`, `anchor`, `position` (`"before"` / `"after"`), `new_content`, optional `occurrence` (`1`) |

**`occurrence`.** For `replace_in_file` — an integer ≥1 or `"all"`.

**`replace_in_file` — three matching tiers.**

- **Tier 1 — byte-exact.** Like Ctrl+F: `search` contains exactly the bytes that are in the file. `foo()` is a substring of `foo()  `, so it matches; the trailing spaces stay. On a match we apply silently.
- **Tier 2 — trailing-whitespace tolerance.** If exact does not match, we normalise trailing whitespace per line in both `search` and the file, then search again. **Leading (indent) is not normalised** — it is meaningful. Unique match — apply, message carries the note `(matched with trailing-whitespace normalisation; verify the line above)`. Multiple matches — `bad_occurrence`, same mechanism as in Tier 1.
- **Tier 3 — no match.** Return `no_match` with `Searched: <repr>` and the top-3 similar lines from the file, with invisible characters marked: `␣` (trailing space), `⇥` (tab). The marker tells you at a glance why the line did not match.

**Regex mode.** `regex: true` — `search` is a Python regex, `replace` supports `\1` backrefs. `occurrence` behaves as in literal mode: `"all"` for every match, a number for the N-th. A bad pattern returns `bad_regex`. Useful for "any `def <name>():`" without hand-managing anchors.

 For `replace_between` / `insert_at_anchor` — an integer ≥1.

**`replace_between`** — replaces a block between two short unique anchors. `include_start` / `include_end` control whether the anchors themselves are consumed. The primary text tool for multi-line replacements. Anchors should be short phrases, no emoji.

**`insert_at_anchor`** — inserts text before or after a unique anchor, without replacing.

**`replace_in_file`** for precise edits — 2–3 lines of context, one is not enough. **Copy `search` from `read_file` output, do not type it by hand** — that avoids whitespace and escape misses.

**`expected_first_line`** in `replace_range` verifies the first line of the range. On mismatch → `content_mismatch`, file untouched.

**`replace_range` and `replace_in_file` are unreliable.** Use them only when no structural tool exists.

### Roblox: bulk replace via bridge (`grep_replace_mcp`)
<!-- summary: grep_replace_mcp — bulk replace over .Source of Roblox scripts via bridge. Shared matcher with grep_mcp, two-pass gate (no_matches / too_many_replacements before writing), strategies A (two patches) / B (max_replacements). Not to be confused with replace_in_file. -->
<!-- tags: roblox, tools, bulk-replace -->

**`grep_replace_mcp`** — find-and-replace over `.Source` of Roblox scripts in a single call. Runs through the bridge; source never leaves Studio. Shares the matcher with `grep_mcp` — same `pattern`, `fixed_strings`, `ignore_case`, `word_boundary`, same scope traversal. **What `grep_mcp` finds, `grep_replace_mcp` finds with the same arguments.**

**Contract.** Exactly one of `pattern` / `mappings`:

- `pattern` + `replacement` — single replacement (Lua pattern, or literal when `fixed_strings=true`).
- `mappings` — an array of `[{"from": "...", "to": "..."}]`. All pairs are applied **in a single pass, simultaneously** (longest-first, no cascade). `mappings` requires `fixed_strings=true`; `ignore_case` is not supported with `mappings`.

**Two-pass gate.** Pass 1 counts replacements without writing. If `total == 0` → `no_matches`, if `total > max_replacements` (default 1000) → `too_many_replacements`. In both cases **no `.Source` is touched**. Pass 2 writes, only when `dry_run=false`.

**Strategy.**

- **A (safe, two patches).** First `grep_mcp` — see where and how many matches. Then `grep_replace_mcp(..., dry_run=true)` — see per-file counts. If they match — `dry_run=false`. This is the norm for unfamiliar cases and wide scopes.
- **B (fast, one patch).** Call `grep_replace_mcp(..., dry_run=false, max_replacements=N)` directly, where `N` is the expected number of replacements. If reality exceeds it, the tool refuses without writing. For familiar identifiers and narrow scopes.

**Limits.** Text replacement, no AST: comments and string literals are included in the search by definition (`include_comments` / `include_strings` are not supported — they cannot be separated without AST). Does not distinguish `local X` from a global `X`. Wally packages under `_Index` are protected because their names contain `.` / `-` / `@` and are not addressable via dotted paths.

**Do not confuse with `replace_in_file`.** That one is a precise edit in a single file, with `search_repr` and `occurrence`; it also works on `.Source`. `grep_replace_mcp` is a bulk refactor across the tree, with a gate and a matcher shared with `grep_mcp`.

### File operations

| Action | Arguments |
|---|---|
| `create_file` | `file_path`, `file_content`; optional `class_name` (for Roblox — defaults to `ModuleScript`, also `Script` / `LocalScript`). Errors if the file exists |
| `overwrite_file` | `file_path`, `file_content` |
| `delete_file` | `file_path` |
| `move_file` | `source_path`, `destination_path`. **Cross-domain forbidden** (FS ↔ Roblox) |
| `copy_file` | `source_path`, `destination_path` — byte-exact copy, source preserved. **Cross-domain forbidden**: FS ↔ Roblox does not copy (incompatible storage models) |

### Unit operations: a unified model for `.py` / `.lua` / `.md` (priority)

**Model.** A file is a tree of **units**. A unit is a named entity:

- **kind**: `module` / `function` / `method` / `class` / `section`.
- **address** (JSON): `{"qualname": "Foo.bar"}` — Python/Lua; `{"section_number": "3.1"}` or `{"section_title": "Format"}` — markdown; `{"qualname": "<module>"}` — module.
- **three parts**: `head` — the declaration (`def f():`, `class C:`, `function f(x)`, `## 3.1 Title`); `annotation` — a short description right after head (docstring `"""..."""`, `--[[ ]]` / `---` in Lua, `<!-- summary: ... -->` in md; may be absent); `body` — everything after head and annotation.
- **blocks** — numbered elements inside body: statements in a function, methods/attributes in a class, subsections in a section. `block=3`, range `"1-10"`, list `[1,3,7]`.

**Decorators (Python).** A function's / class's head **includes** `@decorator` lines. A module's head does not: the decorator of the first def/class belongs to its block. The asymmetry is deliberate, see MODEL.md §2.

**Module:** head up to the **first** def/class/function; everything from there is body (a global between classes is a block in body, not head).

**The model is the same for `.py`, `.lua`, `.luau`, `.md`.** Where annotation lives physically (AST / comment / HTML) is the tool's business. **Comments between units, individual lines, the contents of a markdown fenced block** are not addressable — use the text tools below. If a unit has no docstring, `part=annotation` returns empty (not an error).

**`part`** — a string or a list (`"head"`, `"head,annotation"`, `["head","body"]`), canonical order `head → annotation → body`. **`block`** — body only (`not_applicable` otherwise). `part` and `block` cannot be combined. On ambiguity — `occurrence=N` (otherwise `ambiguous_symbol`).

| Action | Arguments |
|---|---|
| `list_units` | `file_path` — map of units: qualname + kind + L-range + block count |
| `read_unit` | `file_path`, `address` (JSON); optional `part`, `block`. Text. Block range — with `=== block N ===` markers |
| `replace_unit` | `file_path`, `address`, `new_text`; optional `part` (`all` default — replace entirely; `"body"` — body only, head and annotation preserved) |
| `replace_block` | `file_path`, `address`, `block` (int / `"1-4"` / list), `new_text`. Contiguous range; a gap → `bad_block_range`. Empty `new_text` = delete. Comment above the block is preserved |
| `delete_block` | same as `replace_block` with empty `new_text` |
| `insert_block` | `file_path`, `address`, `new_text`, `position` (`start`/`end`/`before`/`after`); `anchor` — block number or qualname of a child unit (required for `before`/`after`) |
| `set_annotation` | `file_path`, `address`, `text` — replace annotation. **Only if it already exists** (otherwise `no_annotation`). Form is chosen by the tool |

**Write tools.** After the write the source is parsed again; if the new text breaks parsing or loses the unit — `result_syntax_error` / `result_missing_symbol`, file **untouched**. First-line indent and EOL (`\n` vs `\r\n`) are preserved.

**Lua.** Blocks inside functions are **not numbered yet** (`blocks=0`, `replace_block` → `not_applicable`) — the token parser does not surface statement boundaries. To edit a body — `replace_unit part="body"`. `insert_block position="end"` inserts before `return M` when present.

**Lua in both modes.** Rojo-mode: the path is an ordinary file path (`.luau`), the extension is detected as for `.py`. MCP-mode: the path is `Service.X.Y` without an extension; `.Source` is Luau. The tool detects MCP paths itself (via `is_mcp_path`); a single adapter (`adapter_lua`) serves both modes. `list_units` / `read_unit` behave identically in either mode.

### Call graph and module-level search

| Action | Arguments |
|---|---|
| `find_symbol` | `query` (qualname substring or module path); optional `manifest_path` |
| `find_usages` | `query` (module path substring); optional `manifest_path`, `limit`, `local`. **Module-level**: `imports` / `used by` |
| `symbol_graph` | `qualname`; optional `occurrence`, `depth` (`1`), `max_nodes` (`300`), `manifest_path`, `kind` (`code`/`lua`), `local`. BFS: callees down to `depth`, callers — one level up |
| `copy_unit` | `source_file`, `target_file`, `selector`, optional `position`, `anchor`, `container`. Copies a unit without touching source |

`find_symbol`, `find_usages`, `symbol_graph` read the manifest (`rebuild_code_index`; for Lua — `kind="lua"`).

**`symbol_graph` is a traversal, not a search.** `find_symbol` looks up by name; `symbol_graph` walks from a known symbol along call edges. The graph is heuristic: `self.X`, local names, `import X`, `from X import Y` resolve; `getattr`, `from X import *`, calls on locals land in `unresolved`.

### Indexes

| Action | Arguments |
|---|---|
| `get_index` | `kind` (`docs`/`code`/`lua`/list) — **required**; optional `max_bytes` (no default — the index is returned in full) |
| `get_status` | optional `sections` (`session`/`indexes`/`policy`) |
| `rebuild_index` | optional `docs_dir`, `output`, `skip_files` |
| `rebuild_code_index` | optional `code_dir`, `output`, `manifest_output`, `skip_files`, `skip_dirs` |
| `rebuild_lua_code_index` | requires MCP (Roblox) |

`rebuild_*` return `[vN]` — the index version — and a structured diff against what was on disk before the rebuild.

**`⚠` at the end of the diff line** means there were **removals** (`-N`). Removals are the one type of change a write tool should not produce without intent: adding or editing is normal, dropping an unrelated unit is an anomaly. If you see `⚠` — check that what disappeared was meant to disappear before moving on. Normal rebuilds (only `~` and `+`) show no `⚠`.

### Execution

| Action | Arguments |
|---|---|
| `run_python` | one of `script` (a `.py` path inside the project) / `module` (dotted name); optional `args` (list of strings), `cwd`, `timeout`, `max_bytes`, `env` |

### Native Roblox tools (when enabled)

If the user enabled `mcp.native_tools.enabled` in the config, you can call native Roblox tools through the same patch format, under their original names: `{"action": "insert_asset", "arguments": {"assetId": "..."}}`. Usage rules live in `MCPBridgeRules.md`, schemas — in `tools_schema.json`. Both are appended to the starter text when the user enables Roblox mode via the GUI checkbox. If the config doesn't allow it, you get `error_code="native_tools_disabled"` — that's a gate, not an error.

Works only if `exec.enabled=true` in the config. Constraints: only `sys.executable`, only inside the project, hard timeout, output cap. This is **not a sandbox** — it runs arbitrary Python inside the project.

**`run_python` is not under `filter.read` / `filter.write`.** It has its own gate — `exec.enabled`. Both `script` and `cwd` are checked against "inside `project_dir`", not against `FilterSpec`: `script` must be a `.py` inside the project, `cwd` must be an existing directory inside the project. So tests that write to temporary subdirectories of the project work even when the `write` policy does not allow those subdirectories.

## 8. Index versions and diffs

Each index has one **monotonic version counter**: `[v1]`, `[v2]`, ..., `[v42]`. It grows on every rebuild and never resets. The counter is visible in `get_status`, `get_index`, and every `rebuild_*` output.

After a patch the GUI rebuilds the indexes automatically. The trigger is a **successfully applied write**: a tool with `op="write"` and `Result.status="ok"`. Read-only tools, index tools, and empty patches do not trigger.

What gets rebuilt is decided by the domain of the touched paths (via the tool's `path_args`):

- **docs** (`INDEX.md`) — a path ending in `.md`.
- **code** (`CODE_INDEX.md`) — a path ending in `.py`.
- **lua** (`CODE_INDEX_LUA.md`) — Luau code. In MCP mode: a Roblox path (starts with a service name), requires a live bridge. In Rojo mode: a filesystem path (`.luau` on disk), no bridge required.

A write with no declared `path_args` (e.g. `run_python`) is treated as "could have touched anything" and triggers all enabled domains. Native MCP tools: the read-only whitelist does not trigger; everything else (including `execute_luau`) triggers lua only.

Each domain is enabled separately (`index_docs` / `index_python` / `index_lua`). Right in the patch output you see `rebuild_index ... [v45, +2 ~1]` with a fresh diff.

**Symbol hash in the Lua index.** Each symbol in `CODE_INDEX_LUA.md` carries a hash — `- qualname [kind] (Lx–Ly) H1234567`. It is a hash of the source fragment (signature + body). It lets the diff see edits that **do not shift lines**: if a function body changes by a few characters without changing line count, the L-range stays the same but the hash changes → the symbol appears in the diff as `~ qualname ... (changed)`. `CODE_INDEX.md` (Python) has no per-symbol hash — its diff relies on the L-range.

- The diff is **cumulative from what was on disk** before the current rebuild, not from what you remember.
- If the patch did not change structure, the diff is empty: `[без изменений]` / `[no changes]`.
- You remember `[v42]` from your last `get_index`. You see `[v45, +2]` — three rebuilds happened in between, you missed two. A small gap — trust the diff. A large or suspicious gap — call `get_index` again. Do not stack diffs from memory — overlay of several diffs is error-prone.

## 9. Markdown document format

The index parses headings strictly:

```
## N. Title                 ← top-level section
<!-- summary: one line -->   ← required for ##
<!-- tags: a, b -->          ← optional

body

### N.M Title              ← subsection
<!-- summary: ... -->       ← optional
```

- Headings: `## N.`, `### N.M`, `#### N.M.K` (space after the number, trailing dot only on `##`).
- `summary` — one line, no line breaks.
- `tags` — comma-separated, optional.

## 10. Index markers

Markers are **facts**, not judgements. Each comes from the AST, the import graph, or the path; interpretation ("this is a hub", "this is dead code") is up to the reader.

**Documents (markdown).**

- `⚠ no summary` — the section has no `<!-- summary -->`. Add one via `set_annotation`.
- `⚠ stale` — the body changed since the summary was last confirmed. Applies **only to markdown sections** (`## N.`, `### N.M`). Read the section and refresh the annotation via `set_annotation` (if the description is outdated). Confirming without touching the file is not yet available in the new model (a `verify_section` analogue).
- `⚠ large` — leaf section >16 KB. Split it into `### N.M` subsections or leave as is.

**Code (Python and Lua).** Module-level: suffix on the header line `## path  (N lines, M KB) <markers>`. Symbol-level: suffix after the L-range.

| Marker | Level | Meaning |
|---|---|---|
| `◉` | module | has `if __name__ == "__main__":`. Fact from AST. Lua modules never have it |
| `← N imp` | module | imports N other modules **inside the index**. External imports (stdlib, third-party) do not count. Hidden when N=0 |
| `→ N users (M tests)` | module | imported by N other modules of the index; M of them are tests (by path `tests/`, `test_*`). Hidden when N=0 |
| `[tests/]` | module | file lives in a test directory or is named `test_*` |
| `[vendor/]` | module | path contains `vendor/`, `_Index/`, or `node_modules/` |
| `⚠ large` | module | > 300 lines or > 16 KB. Hint: don't read whole, read by sections/symbols |
| `⚠ large` | symbol | definition is longer than 100 lines |
| `⚠ cycle` | module | participates in an import cycle inside the index |

**`→ N users` is approximate for Lua.** The Luau graph is built from `require` and misses dynamic loads and external consumers. In Python it is exact (AST). In Lua — a lower bound.

**Suppression.** In the file head (first 20 lines) markers can be muted with a directive:

```python
# pa: no-users, no-large
```

Names: `main`, `imports`, `users`, `tests`, `vendor`, `large`, `cycle`. `all` mutes everything. Multiple lines merge. The directive is a **fact about the file** (lives with it, versioned), not a toolkit setting.

Why mute: the file itself knows it's generated data (`# pa: no-large`) or a public API whose consumers aren't visible in the index (`# pa: no-users`).

## 11. Strategies

**Understand mechanic X:**
1. `grep pattern="X"` over the index — every section across all docs at once.
2. `read_file section_number="N"` — precisely.
3. Follow links from what you read — that is where to go next.

**Make an edit:**
1. `read_file section_number="N"` — read the section.
2. If `⚠ stale` — rewrite the annotation via `set_annotation` (if the description is outdated). Confirming without touching the file (a `verify_section` analogue) is not yet available in the new model.
3. Build the patch.
4. Verify with another `read_file`.

**Find a unit (symbol / section):**
1. `list_units file_path=...` — map of the file: qualname + kind + line-range + block count.
2. `read_unit file_path=..., address={...}` — text of the unit or its parts.
3. To search by name without a file — `find_symbol query="..."` (manifest).

**Read a unit in parts:**
1. `part="head"` — signature / heading.
2. `part="annotation"` — docstring / summary.
3. `part="body"` — body.
4. `part="head,annotation"` or a list — several parts.
5. `block="1-5"` — a block range in body.

**Edit a unit:**
1. `read_unit` — see the current state.
2. `replace_unit` — replace the whole unit (`part=all`) or only a part (`part="body"` keeps head and annotation).
3. `replace_block` — replace a block or a range in body. Empty `new_text` deletes (or use `delete_block`).
4. `insert_block` — insert a block at `start` / `end` / `before anchor` / `after anchor`.
5. `set_annotation` — replace docstring / summary. **Only if the annotation already exists** — creating one from scratch is not supported.

**Graph navigation:**
1. `find_symbol query="X"` — where X is defined (name → module).
2. `find_usages query="path/to/mod"` — module-level walk: who imports me (`used by`), whom I import (`imports`).
3. `symbol_graph qualname="X" depth=2` — from a known symbol: callees down, callers up. The graph is heuristic (see §7).

**Symbol-level boundary.** Symbolic reverse ("where is `X.foo` called") is implemented for Python only. For Lua, `symbol_graph kind="lua"` returns the symbol's module without callees/callers — the Lua manifest carries no `calls` field. Module-level reverse (`find_usages`) works for Lua over `require` and is approximate.

**Bulk edit across the project:**
1. Filesystem — `grep` finds matches, `replace_in_file` with `occurrence="all"` edits all in one file.
2. Roblox — `grep_replace_mcp` in a single call (strategies A / B from §7).

## 12. What to remember

- **Do not rely on memory.** If a fact matters for a decision — re-read it.
- **`⚠ stale` ≠ "outdated".** It means "not verified after an edit". Refresh the annotation via `set_annotation` if the description is stale.
- **`blocked` ≠ `error`.** `blocked` is policy or sandbox; do not retry, tell the user.
- **Files >100 KB** — read by sections or with `max_bytes`. `read_file` without limits reads the whole file — for a large one that floods context. Check the size in the index first (`⚠ large`, metrics in the header).
- **Read the current state before editing.** `read_unit` / `read_file` → then `replace_*` / `insert_*` / `delete_*`. The index may be stale, the previous patch may not have applied, the file may have changed. Exception — idempotent operations like `create_file` for a file that certainly does not exist.
- **One patch = one logical action.** Do not mix reading and writing without a reason.
- **Check the diff from `rebuild_*`.** It shows what actually changed in the index.
- **Hidden = closed.** Paths in `.patchignore` at the project root (dotdirs, `__pycache__`, `node_modules`, `venv` by default) are closed for read / write / index. If access is needed, the user opens them via the GUI. Hidden in the tree means "not reachable", not "not important".

## 13. Error codes

`Result` carries `error_code` — a machine-readable tag. What to do:

**Patch parsing:**
- Compiler messages about bad groups arrive in a separate `=== Compiler messages ===` block after the log, plus a `diagnostics` field in `##RESULT`. Three kinds: `syntax` (the fragment does not parse as JSON), `missing_id` (valid object without the required `id`), `duplicate_id` (two actions share a label). Each message carries `line`, `column`, `message`. The rest of the patch applies normally — the bad group is simply skipped.

**Target not found or ambiguous:**
- `not_found` — unit / section / file not found. Check the address, name, number. Make sure the index is current (`get_index`).
- `ambiguous_symbol` — the address matches N times. The message lists the L-ranges. Pass `occurrence=N` (N-th top-down).
- `occurrence_out_of_range` — N out of range; the message says how many matches.
- `block_out_of_range` — block number exceeds the body's block count (the message says how many).
- `not_applicable` — a block op on a unit with no blocks (Lua function without statement boundaries, head/annotation instead of body).
- `no_annotation` — `set_annotation` on a unit without an existing annotation; creating one from scratch is not supported.
- `no_parts` — `replace_unit part=[...]` — none of the requested parts exist on the unit.
- `anchor_not_found` — no anchor block for `position=before|after` (block number or a child unit qualname).
- `no_match` — `replace_in_file`: `search` not found.
- `kind_required` — `get_index`: `kind` missing but required.
- `unknown_kind` / `bad_kind` — `get_index`: invalid `kind`.
- `unknown_section` — `get_status`: invalid `sections`.

**Call shape:**
- `empty_input` — `new_text` / `new_code` / `new_body` / `new_content` are empty.
- `bad_position` — `position` is not one of `start|end|before|after`.
- `anchor_required` — `position=before|after` without `anchor`.
- `anchor_not_allowed` — `position=start|end` with `anchor`.
- `bad_occurrence` — `occurrence` is not an integer.
- `bad_part` — `part` is not one of `all|head|annotation|body`.
- `bad_block` — the `block` string did not parse (`block="abc"`).
- `bad_block_range` — `replace_block` / `delete_block` received non-adjacent blocks (`"1,3"`); only a contiguous range is allowed.
- `ambiguous_input` — `run_python`: both or neither of `script`/`module`.

**Parsing:**
- `syntax_error` — the source file does not parse. File untouched.
- `result_syntax_error` — the proposed content does not parse. Patch cancelled, file untouched. Fix `new_text` / `new_code`.
- `result_missing_symbol` / `result_missing_section` — the edit dropped the unit/section from the file. Patch cancelled, file untouched.

**Manifest (`find_symbol` / `find_usages` / `symbol_graph`):**
- `empty_query` — empty `query`.
- `manifest_not_found` — manifest file missing; run `rebuild_code_index`.
- `manifest_read_error` — cannot read the manifest.
- `manifest_invalid` — manifest is not JSON or not a list of modules.

**Policy and sandbox (`status=blocked`, do not retry):**
- `filter` — path blocked by policy or hidden via `.patchignore`. Tell the user; opened via the GUI.
- `sandbox` — path outside the project.
- `backend_not_ready` — MCP (Roblox) not up yet or crashed. Wait, or hit `↻` in the GUI.
- `native_tools_disabled` — a native MCP tool was called but `mcp.native_tools.enabled=false` in config. A gate, not an error.
- `exec_disabled` — `run_python` is off in config.
- `script_outside_project` / `cwd_outside_project` — `run_python` paths outside the project.

**Execution:**
- `timeout` — script killed on timeout (message contains `TIMED_OUT`).
- `nonzero_exit` — non-zero return code; message contains `exit=N`.
- `script_not_python` / `script_not_found` — `run_python` parameters.

**File operations:**
- `already_exists` — `create_file`: file already exists.
- `source_not_found` / `destination_exists` — `move_file` and `copy_file`.
- `backend_not_supported` — `copy_file`: backend cannot `copy()` (e.g. MCP without clone semantics for this instance type).

**Roblox: `grep_mcp` / `grep_replace_mcp`:**
- `wrong_domain` — not a Roblox path (`Service.X.Y` required). For the filesystem use `grep` / `replace_in_file`.
- `empty_pattern` — `grep_mcp`: empty `pattern`.
- `bad_options` — `ignore_case` without `fixed_strings=true`; `max_replacements <= 0`; `ignore_case` with `mappings`.
- `bad_input` — `grep_replace_mcp`: exactly one of `pattern` / `mappings` is required.
- `empty_mappings` / `patterns_in_mappings_not_supported` / `bad_mapping` / `empty_mapping` / `noop_mapping` / `duplicate_mapping` — `mappings` shape problems.
- `no_matches` — `grep_replace_mcp`: no matches. Nothing written.
- `too_many_replacements` — total matches exceed `max_replacements`. Nothing written. Narrow the scope, add `word_boundary=true`, refine `pattern`, or raise the limit.
- `backend_not_supported` — backend does not support `grep_mcp` / `grep_replace_mcp` (MCP required).

**Copying structural units:**
- `bad_selector` — `copy_unit`: `selector` is not a dict or does not have exactly one of `section_number` / `section_title` / `qualname`.
- `unknown_unit` — `copy_unit`: `source_file` extension is not `.md`/`.py`/`.lua`/`.luau`; or the section is not in source.
- `wrong_selector` — `copy_unit`: the key does not match the extension (`.md` + `qualname`, or `.py`/`.lua` + `section_*`).
- `container_not_supported` — `copy_unit`: `container` passed for `.md` or Lua.
- `no_format` — `rebuild_*` / `copy_unit`: `fmt=None` (uninitialized `Format` in session).
- `result_parse_error` — `lua_copy_symbol`: new target does not parse; file untouched.

**Native calls:**
- `native_error` — exception inside a native MCP bridge tool (`execute_luau`, `multi_edit`, ...). Check `message` — it has the class and text.
- `requires_mcp` — `rebuild_lua_code_index`: backend has no `execute()` (no MCP).

## 14. What not to do

- **Do not use `replace_in_file` for multi-line replacements.** Even 2–3 lines of context easily miss on whitespace, invisible characters, or escapes. For block edits, use `replace_between` — two short anchors instead of a long `search`.
- **Do not use `replace_range` on supported formats.** For `.py` / `.lua` / `.md` there is always the unit model (`replace_unit`, `replace_block`, `delete_block`, `insert_block`) and `replace_between`. `replace_range` is only for the module-level top region and for formats without a parser. If you do need it, pass `expected_first_line`.
- **Do not use `replace_range` more than once per file per patch.** Line numbers shift between actions.
- **Do not confuse `part` and `block`.** `part` is `head` / `annotation` / `body` (the unit's three parts). `block` is a numbered element **inside** body. They cannot be combined: `part`+`block` in one call is an error.
- **Do not try to write an annotation where none exists.** `set_annotation` only **replaces an existing one**. If absent — `no_annotation`. To create one — `replace_unit part="body"` (insert by hand) or `insert_block`.
- **Do not use `replace_block` for a non-contiguous range.** `"1,3"` → `bad_block_range`. Only contiguous (`"1-3"`). For gaps — several calls.
- **Do not stack diffs from memory.** If the version gap is more than 1–2, re-read `get_index`.
- **Do not build call chains through a series of `read_unit`.** If you need "who calls X" or "what X calls" — `symbol_graph qualname="X"` in a single call.
- **Do not ignore `⚠ stale`.** Before editing a section, refresh the annotation via `set_annotation`.
- **Do not retry `blocked`.** `■ blocked` is a policy decision (including `.patchignore`), not a transient error.
- **Do not try to fix syntax through `replace_unit`.** If the file fails to parse — that is `syntax_error`; read it as text (`read_file`).
- **Do not guess.** On `not_found` or `ambiguous_symbol`, read the index, unit, or section — do not guess the address.

## 15. Where to start

1. Read the status — it is normally attached at the bottom of the starter text; if not, call `get_status`.
2. `get_index` — see the map.
3. Read section → edit section → verify.
4. If something is unclear — ask the user, do not guess.

## 16. Patch examples

All examples carry the required `id`. One action — one `[...]` group; groups go one after another.

**Editing an md section — refresh body and annotation:**

```json
[{"id": 1, "action": "read_unit",
  "arguments": {"file_path": "docs/CONFIG.md",
                "address": {"section_number": "3"},
                "part": "head,annotation"}}]

[{"id": 2, "action": "replace_unit",
  "arguments": {"file_path": "docs/CONFIG.md",
                "address": {"section_number": "3"},
                "part": "body",
                "new_text": "New section body.\n\n### 3.1 Subsection\n\nsubsection body"}}]

[{"id": 3, "action": "set_annotation",
  "arguments": {"file_path": "docs/CONFIG.md",
                "address": {"section_number": "3"},
                "text": "Refreshed section description"}}]
```

Order matters: actions run in sequence. `replace_unit part="body"` preserves `head` and `annotation` — the heading and summary stay intact.

**Editing a Python function — replace the body, keep the signature:**

```json
[{"id": "read", "action": "read_unit",
  "arguments": {"file_path": "toolkit/core/patcher.py",
                "address": {"qualname": "Patcher._apply_one"},
                "part": "head,annotation"}}]

[{"id": "body", "action": "replace_unit",
  "arguments": {"file_path": "toolkit/core/patcher.py",
                "address": {"qualname": "Patcher._apply_one"},
                "part": "body",
                "new_text": "return self._dispatch(patch)"}}]
```

**Replace one block (statement) in a large body:**

```json
[{"id": "read", "action": "read_unit",
  "arguments": {"file_path": "toolkit/core/patcher.py",
                "address": {"qualname": "Patcher._apply_one"},
                "block": "1-5"}}]

[{"id": "repl", "action": "replace_block",
  "arguments": {"file_path": "toolkit/core/patcher.py",
                "address": {"qualname": "Patcher._apply_one"},
                "block": 3,
                "new_text": "return self._short_circuit(patch)"}}]
```

`block=3` is the third top-level statement. For several edits, replace a range (`block="3-5"`) or the **whole body** via `replace_unit part="body"` (one call instead of several `replace_block` with index shifts in between).

**Insert a block at start / end / next to an anchor:**

```json
[{"id": "ins", "action": "insert_block",
  "arguments": {"file_path": "toolkit/core/patcher.py",
                "address": {"qualname": "Patcher._apply_one"},
                "new_text": "self._trace(patch)",
                "position": "before",
                "anchor": 1}}]
```

`anchor` is a block number or a child unit's qualname (for a class — a method). For `start` / `end`, no anchor is needed.

**Delete a block:**

```json
[{"id": "del", "action": "delete_block",
  "arguments": {"file_path": "toolkit/core/patcher.py",
                "address": {"qualname": "Patcher._legacy_log"},
                "block": 2}}]
```

**Trace a symbol's call chain:**

```json
[{"id": "read", "action": "read_unit",
  "arguments": {"file_path": "toolkit/core/patcher.py",
                "address": {"qualname": "Patcher._apply_one"},
                "part": "head,annotation"}}]

[{"id": "trace", "action": "symbol_graph",
  "arguments": {"qualname": "Patcher._apply_one", "depth": 2}}]
```

`read_unit` shows the signature; `symbol_graph` — what it calls two levels down and who calls it, with line addresses. Instead of a chain of `read_unit → find_symbol → read_unit` per neighbour — one `symbol_graph`. If something interesting turns up — `read_unit` precisely on that symbol.

**Copy a function to another file:**

```json
[{"id": "copy", "action": "copy_unit",
  "arguments": {"source_file": "toolkit/utils.py",
                "target_file": "toolkit/config.py",
                "selector": {"qualname": "parse_config"},
                "position": "end"}}]

[{"id": "rebuild", "action": "rebuild_code_index", "arguments": {}}]
```

`copy_unit` copies the whole unit (with body and annotation) and **does not touch** the source. Transitive dependencies (imports, `common.X`) are **not** carried over — add them via a separate `replace_unit` / `insert_block`.

**Create a file and rebuild the docs index:**

```json
[{"id": 1, "action": "create_file",
  "arguments": {"file_path": "docs/NEW.md",
                "file_content": "# NEW\n\n## 1. Section\n<!-- summary: ... -->\n\nbody\n"}}]

[{"id": 2, "action": "rebuild_index", "arguments": {}}]
```

In the output you will see `+ docs/NEW.md  (N lines, M KB, mtime ...)` and version `[vN]` — that confirms the index caught up with reality.
