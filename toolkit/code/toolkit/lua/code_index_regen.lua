-- code_index_regen.lua
-- Chunked index builder.
--
-- Contract with Python:
--     Expects `parse(src)` to be already defined in scope (Python concatenates
--     flattened lua_symbols.lua before this file).
--     Expects a global `__cursor` (integer, 0-based start index). Python
--     injects `__cursor = N` at the top of the payload.
--     Returns JSON: {items, next_cursor, done, total}.
--         items        : array of module records
--         next_cursor  : index to pass in the next call (0-based count consumed)
--         done         : true if this was the last chunk
--         total        : total number of modules discovered (for logging)
--
-- The chunk is bounded by BUDGET (bytes, JSON-encoded estimate). This keeps the
-- MCP response well under the ~100 KB text-response limit, regardless of
-- project size. 260 modules -> 1 call. 1000 modules -> a few calls.
--
-- Module records:
--     {path, hash, len, imports: [...], symbols: [
--         {qualname, kind, line_start, line_end, hash}]}
-- Fields are deliberately narrow: signature/parent/name are dropped to shrink
-- each record; Python reconstructs them from qualname when needed.

local BUDGET = 80000

local ROOTS = {
    "ReplicatedStorage",
    "ServerScriptService",
    "ServerStorage",
    "StarterPlayer",
}

local IMPORTS_LIMIT = 6

-- -- helpers --------------------------------------------------------------

local function source_hash(source)
    local h = 17
    for i = 1, #source do
        h = (h * 31 + string.byte(source, i)) % 2147483647
    end
    return h, #source
end

local function extract_imports(source)
    local out = {}
    local seen = {}
    for target in string.gmatch(source, "require%s*%(%s*([^%)]+)") do
        local t = string.match(target, "^%s*(.-)%s*$") or ""
        if t ~= "" and not seen[t] then
            seen[t] = true
            table.insert(out, t)
            if #out >= IMPORTS_LIMIT then
                break
            end
        end
    end
    return out
end

local function short_path(inst)
    local parts = { inst.Name }
    local node = inst.Parent
    while node and node ~= game do
        table.insert(parts, 1, node.Name)
        node = node.Parent
    end
    return table.concat(parts, ".")
end

local function count_lines(s)
    if #s == 0 then return 0 end
    local n = 0
    local pos = 1
    while true do
        local nl = string.find(s, "\n", pos, true)
        if not nl then break end
        n = n + 1
        pos = nl + 1
    end
    if string.sub(s, -1) ~= "\n" then n = n + 1 end
    return n
end

-- -- collect all modules ------------------------------------------------

local all = {}
for _, rootName in ipairs(ROOTS) do
    local root = game:FindFirstChild(rootName)
    if root then
        for _, inst in ipairs(root:GetDescendants()) do
            if inst:IsA("LuaSourceContainer") then
                table.insert(all, inst)
            end
        end
    end
end

-- Sort deterministically by path so cursor-by-index is stable across calls.
table.sort(all, function(a, b)
    return short_path(a) < short_path(b)
end)

local total = #all
local HttpService = game:GetService("HttpService")

-- -- chunk building ------------------------------------------------------

local start_index = tonumber(__cursor) or 0
if start_index < 0 then start_index = 0 end
if start_index > total then start_index = total end

-- Reserve a small envelope for the outer JSON: keys + total + cursor + done.
local envelope_reserve = 64
local size = envelope_reserve
local items = {}
local i = start_index + 1

while i <= total do
    local inst = all[i]
    local src = inst.Source or ""
    local syms = parse(src)

    local syms_out = {}
    for _, s in ipairs(syms) do
        table.insert(syms_out, {
            qualname = s.qualname,
            kind = s.kind,
            line_start = s.line_start,
            line_end = s.line_end,
            hash = s.hash or 0,
        })
    end

    local h, n = source_hash(src)
    local item = {
        path = short_path(inst),
        hash = h,
        len = n,
        lines = count_lines(src),
        imports = extract_imports(src),
        symbols = syms_out,
    }

    local encoded = HttpService:JSONEncode(item)
    local piece_size = #encoded + 1  -- +1 for comma / array separator

    if size + piece_size > BUDGET and #items > 0 then
        -- Would overflow. Emit what we have; Python will continue with cursor.
        break
    end

    -- Guarantee forward progress: if a single item is larger than BUDGET,
    -- we still emit it (as its own chunk) rather than looping forever.
    table.insert(items, item)
    size = size + piece_size
    i = i + 1

    if size + piece_size > BUDGET then
        -- Next iteration would overflow; emit now.
        break
    end
end

local next_cursor = i - 1
local done = (next_cursor >= total)

local result = {
    items = items,
    next_cursor = next_cursor,
    done = done,
    total = total,
}

return HttpService:JSONEncode(result)
