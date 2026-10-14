-- include: _match
-- grep_replace.lua — two-pass search-and-replace over LuaSourceContainers.
--
-- Pass 1 (always): count replacements per file. No writes.
-- Gate: if total == 0 -> __EMPTY__. If total > MAX -> __OVERFLOW__ (nothing written).
-- Pass 2 (only when dry=false): recompute and write .Source.
--
-- Per-line: each line is processed independently, matching grep.lua's
-- view of the source. A pattern that spans a newline will not match.
--
-- Placeholders:
--   %EXPR%        root expression ("game.ReplicatedStorage.Shared")
--   %PATTERN%     JSON-encoded pattern string, or "nil" in mappings mode
--   %REPLACEMENT% JSON-encoded replacement string, or "nil"
--   %MAPPINGS%    Lua table literal {{from,to},...}, or "nil" in pattern mode
--   %PLAIN%       "true" (literal) | "false" (Lua pattern). Ignored in mappings mode.
--   %ICASE%       "true" | "false". Not allowed with mappings (Python rejects).
--   %WB%          "true" | "false" — word boundary check
--   %MAX%         int gate: total replacements cap
--   %DRY%         "true" (scan-only) | "false" (scan + write)
--
-- Output:
--   CHANGED\t<path>\t<count>   (one line per matched file)
--   __SUMMARY__\tfiles=N\treplacements=M\tapplied=true|false
-- Or: __EMPTY__ | __MISSING__ | __OVERFLOW__\t<found>\t<max>

local ok, root = pcall(function() return %EXPR% end)
if not ok or root == nil then return '__MISSING__' end

local pattern = %PATTERN%
local replacement = %REPLACEMENT%
local mappings = %MAPPINGS%
local plain = %PLAIN%
local icase = %ICASE%
local wb = %WB%
local max_repl = %MAX%
local dry = %DRY%

-- Sort mappings longest-first; ties broken alphabetically for determinism.
local function sort_mappings(m)
    local out = {}
    for _, pair in ipairs(m) do out[#out + 1] = {pair[1], pair[2]} end
    table.sort(out, function(a, b)
        if #a[1] ~= #b[1] then return #a[1] > #b[1] end
        return a[1] < b[1]
    end)
    return out
end

local sorted_mappings = mappings and sort_mappings(mappings) or nil

-- Split source into lines, keeping the EOL as part of each entry.
-- Empty source -> empty list. A source that does not end with \n yields
-- a last entry with no EOL.
local function split_lines_keepends(s)
    local lines = {}
    if s == '' then return lines end
    local pos = 1
    while pos <= #s do
        local nl = s:find('\n', pos, true)
        if nl then
            lines[#lines + 1] = s:sub(pos, nl)
            pos = nl + 1
        else
            lines[#lines + 1] = s:sub(pos)
            break
        end
    end
    return lines
end

-- Apply to a single line (no trailing newline). Returns (new_line, count).
local function apply_to_line(line)
    local out = {}
    local count = 0
    local n = #line
    if sorted_mappings then
        local i = 1
        local from_start = 1
        while i <= n do
            local matched = false
            for _, m in ipairs(sorted_mappings) do
                local flen = #m[1]
                if flen > 0 and line:sub(i, i + flen - 1) == m[1] then
                    local b = i + flen - 1
                    local ok_l = (i == 1) or not is_word(line:sub(i - 1, i - 1))
                    local ok_r = (b == n) or not is_word(line:sub(b + 1, b + 1))
                    if (not wb) or (ok_l and ok_r) then
                        table.insert(out, line:sub(from_start, i - 1))
                        table.insert(out, m[2])
                        i = b + 1
                        from_start = i
                        count = count + 1
                        matched = true
                        break
                    end
                end
            end
            if not matched then i = i + 1 end
        end
        table.insert(out, line:sub(from_start))
    else
        local hay = icase and ascii_lower(line) or line
        local needle = icase and ascii_lower(pattern) or pattern
        local i = 1
        local from_start = 1
        while i <= n do
            local a, b = match_from(line, hay, needle, i, plain, wb)
            if not a then break end
            table.insert(out, line:sub(from_start, a - 1))
            table.insert(out, replacement)
            i = b + 1
            from_start = i
            count = count + 1
        end
        table.insert(out, line:sub(from_start))
    end
    return table.concat(out), count
end

-- Apply to a full source, line by line, preserving EOLs.
local function apply_to_source(src)
    local total = 0
    local parts = {}
    for _, line in ipairs(split_lines_keepends(src)) do
        local content, eol
        if line:sub(-1) == '\n' then
            content = line:sub(1, -2)
            eol = '\n'
        else
            content = line
            eol = ''
        end
        local new_line, c = apply_to_line(content)
        parts[#parts + 1] = new_line
        parts[#parts + 1] = eol
        total = total + c
    end
    return table.concat(parts), total
end

local targets = {}
local function collect(inst)
    if inst:IsA('LuaSourceContainer') then targets[#targets + 1] = inst end
end
collect(root)
for _, inst in ipairs(root:GetDescendants()) do collect(inst) end

local entries = {}
local total = 0
for _, inst in ipairs(targets) do
    local _, c = apply_to_source(inst.Source or '')
    if c > 0 then
        entries[#entries + 1] = {inst = inst, count = c}
        total = total + c
    end
end

if total == 0 then return '__EMPTY__' end
if total > max_repl then
    return '__OVERFLOW__\t' .. total .. '\t' .. max_repl
end

if not dry then
    for _, e in ipairs(entries) do
        local new_src = apply_to_source(e.inst.Source or '')
        e.inst.Source = new_src
    end
end

local results = {}
for _, e in ipairs(entries) do
    results[#results + 1] = 'CHANGED\t' .. e.inst:GetFullName() .. '\t' .. e.count
end
results[#results + 1] = '__SUMMARY__\tfiles=' .. #entries ..
    '\treplacements=' .. total ..
    '\tapplied=' .. tostring(not dry)
return table.concat(results, string.char(10))
