-- include: _match
-- Grep over LuaSourceContainers under a root instance.
-- The root itself is included if it is a LuaSourceContainer.
-- Placeholders:
--   %EXPR%    — Lua expression resolving the root (e.g. "game.ReplicatedStorage.Shared")
--   %PATTERN% — JSON-encoded string pattern
--   %PLAIN%   — "true" (literal search) | "false" (Lua pattern)
--   %ICASE%   — "true" | "false"; only meaningful when PLAIN="true"
--   %WB%      — "true" | "false" (word boundary: match only between non-word chars)
--   %MAX%     — integer cap on matches (safety)
--   %BEFORE%  — lines of context before match (0 = none)
--   %AFTER%   — lines of context after match (0 = none)
-- Output: one line per match ("path:lineno: text"), "--" between context blocks,
-- or "__EMPTY__" if none, "__MISSING__" if root not found.
-- On truncation the final line is "__TRUNCATED_MATCHES__" (hit max_matches)
-- or "__TRUNCATED_BYTES__" (hit 100 KB byte cap).
local ok, root = pcall(function() return %EXPR% end)
if not ok or root == nil then return '__MISSING__' end

local pattern = %PATTERN%
local plain = %PLAIN%
local icase = %ICASE%
local wb = %WB%
local max_matches = %MAX%
local before_n = %BEFORE%
local after_n = %AFTER%
local byte_limit = 100000

local results = {}
local bytes = 0
local match_count = 0
local trunc_reason = nil

local function emit(s)
    local n = #s + 1
    if bytes + n > byte_limit then
        trunc_reason = 'bytes'
        return false
    end
    table.insert(results, s)
    bytes = bytes + n
    return true
end

-- Returns true if processing should stop (truncated).
local function process(inst)
    if not inst:IsA('LuaSourceContainer') then return false end
    local src = inst.Source or ''
    local path = inst:GetFullName()
    local lines = {}
    for line in (src .. '\n'):gmatch('([^\n]*)\n') do
        table.insert(lines, line)
    end
    for i = 1, #lines do
        local hay = icase and ascii_lower(lines[i]) or lines[i]
        local needle = icase and ascii_lower(pattern) or pattern
        local a = match_from(lines[i], hay, needle, 1, plain, wb)
        if a then
            match_count = match_count + 1
            if before_n > 0 or after_n > 0 then
                local s = math.max(1, i - before_n)
                local e = math.min(#lines, i + after_n)
                for j = s, e do
                    local mark = (j == i) and '>' or ' '
                    if not emit(path .. ':' .. j .. ': ' .. mark .. ' ' .. lines[j]) then
                        return true
                    end
                end
                if not emit('--') then return true end
            else
                if not emit(path .. ':' .. i .. ': ' .. lines[i]) then
                    return true
                end
            end
            if match_count >= max_matches then
                trunc_reason = 'matches'
                return true
            end
        end
    end
    return false
end

if process(root) then
    -- truncated on root itself
else
    for _, inst in ipairs(root:GetDescendants()) do
        if process(inst) then break end
    end
end

if #results == 0 then
    return '__EMPTY__'
end

local out = table.concat(results, string.char(10))
if trunc_reason == 'matches' then
    out = out .. string.char(10) .. '__TRUNCATED_MATCHES__'
elseif trunc_reason == 'bytes' then
    out = out .. string.char(10) .. '__TRUNCATED_BYTES__'
end
return out
