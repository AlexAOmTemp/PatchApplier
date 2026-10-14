-- Shared matcher primitives for grep and grep_replace.
--
-- Included by both scripts via `-- include: _match` at the top.
-- Kept minimal: ascii_lower, is_word, match_from. Both callers are
-- per-line, so `match_from` scans one line at a time.

local function ascii_lower(s)
    return (s:gsub('%u', function(c) return string.char(string.byte(c) + 32) end))
end

local function is_word(c)
    if c == '' then return false end
    return c:match('[%w_]') ~= nil
end

-- Returns (a, b) — 1-based inclusive indexes of the next match on
-- `orig` starting at `pos`, or nil. `hay` is `orig` lowercased when
-- icase; `needle` is the pattern likewise. `plain=true` means literal
-- match. `wb=true` requires a non-word char on each side.
local function match_from(orig, hay, needle, pos, plain, wb)
    while pos <= #orig do
        local a, b = string.find(hay, needle, pos, plain)
        if not a then return nil end
        if not wb then return a, b end
        local ok_l = (a == 1) or not is_word(orig:sub(a - 1, a - 1))
        local ok_r = (b == #orig) or not is_word(orig:sub(b + 1, b + 1))
        if ok_l and ok_r then
            return a, b
        end
        pos = a + 1
    end
    return nil
end
