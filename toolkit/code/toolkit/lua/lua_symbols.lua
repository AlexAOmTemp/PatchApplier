-- lua_symbols.lua
-- Lua/Luau parser -- symbol extraction via token scanning.
--
-- Port of toolkit/formats/lua.py. Identical output shape: array of
-- {name, qualname, kind, line_start, line_end, hash, signature, docstring,
--  decorators, parent}.
--
-- Handled forms:
--   local function name(...) ... end
--   function name(...) ... end
--   function M.name(...) ... end
--   function M:method(...) ... end
--   Name = function(...) ... end
--   local Name = function(...) ... end
--
-- Ignores comments and string literals. No AST.
--
-- This file is meant to be inlined into a larger execute_luau payload.
-- Do not `require` -- the sandbox creates a fresh VM copy per require.
--
-- Returns the module table with a single `parse(src)` function.

local M = {}

local KEYWORDS = {
    ["and"] = true, ["break"] = true, ["do"] = true, ["else"] = true,
    ["elseif"] = true, ["end"] = true, ["false"] = true, ["for"] = true,
    ["function"] = true, ["if"] = true, ["in"] = true, ["local"] = true,
    ["nil"] = true, ["not"] = true, ["or"] = true, ["repeat"] = true,
    ["return"] = true, ["then"] = true, ["true"] = true, ["until"] = true,
    ["while"] = true,
}

local OPENERS = { ["function"] = true, ["if"] = true, ["do"] = true, ["repeat"] = true }
local CLOSERS = { ["end"] = true, ["until"] = true }

-- -- tokenize ------------------------------------------------------------

local function tokenize(src)
    local tokens = {}
    local i = 1
    local n = #src
    while i <= n do
        local c = string.sub(src, i, i)
        if string.match(c, "%s") then
            i = i + 1
        elseif c == "-" and string.sub(src, i + 1, i + 1) == "-" then
            local j = i + 2
            local eq = 0
            while string.sub(src, j, j) == "=" do
                eq = eq + 1
                j = j + 1
            end
            if string.sub(src, j, j) == "[" then
                local closer = "]" .. string.rep("=", eq) .. "]"
                local k = string.find(src, closer, j + 1, true)
                if not k then break end
                i = k + #closer
            else
                local k = string.find(src, "\n", i, true)
                if not k then break end
                i = k + 1
            end
        elseif c == "[" then
            local j = i + 1
            local eq = 0
            while string.sub(src, j, j) == "=" do
                eq = eq + 1
                j = j + 1
            end
            if string.sub(src, j, j) == "[" then
                local closer = "]" .. string.rep("=", eq) .. "]"
                local k = string.find(src, closer, j + 1, true)
                if not k then
                    table.insert(tokens, { kind = "string", text = string.sub(src, i), pos = i })
                    i = n + 1
                else
                    table.insert(tokens, { kind = "string", text = string.sub(src, i, k + #closer - 1), pos = i })
                    i = k + #closer
                end
            else
                table.insert(tokens, { kind = "punct", text = c, pos = i })
                i = i + 1
            end
        elseif c == "'" or c == '"' then
            local quote = c
            local j = i + 1
            while j <= n do
                local ch = string.sub(src, j, j)
                if ch == "\\" and j + 1 <= n then
                    j = j + 2
                elseif ch == quote then
                    j = j + 1
                    break
                elseif ch == "\n" then
                    break
                else
                    j = j + 1
                end
            end
            table.insert(tokens, { kind = "string", text = string.sub(src, i, j - 1), pos = i })
            i = j
        elseif string.match(c, "[%a_]") then
            local j = i + 1
            while j <= n and string.match(string.sub(src, j, j), "[%w_]") do
                j = j + 1
            end
            local word = string.sub(src, i, j - 1)
            local kind = KEYWORDS[word] and "keyword" or "ident"
            table.insert(tokens, { kind = kind, text = word, pos = i })
            i = j
        elseif string.match(c, "%d") then
            local j = i + 1
            while j <= n do
                local ch = string.sub(src, j, j)
                if string.match(ch, "[%w%.]") or ch == "_" then
                    j = j + 1
                else
                    break
                end
            end
            table.insert(tokens, { kind = "number", text = string.sub(src, i, j - 1), pos = i })
            i = j
        else
            table.insert(tokens, { kind = "punct", text = c, pos = i })
            i = i + 1
        end
    end
    return tokens
end

-- -- line index ----------------------------------------------------------

local function make_line_of(src)
    local line_starts = { 1 }
    local pos = 1
    while true do
        local nl = string.find(src, "\n", pos, true)
        if not nl then break end
        table.insert(line_starts, nl + 1)
        pos = nl + 1
    end
    return function(p)
        local lo, hi = 1, #line_starts
        while lo < hi do
            local mid = math.floor((lo + hi + 1) / 2)
            if line_starts[mid] <= p then
                lo = mid
            else
                hi = mid - 1
            end
        end
        return lo
    end
end

-- -- signature extraction -------------------------------------------------

local function slice_signature(src, tokens, func_idx, prefix)
    local j = func_idx + 1
    while j <= #tokens do
        local tok = tokens[j]
        if tok.kind == "punct" and tok.text == "(" then break end
        j = j + 1
    end
    if j > #tokens then
        return prefix .. "(...)"
    end
    local depth = 0
    local close_pos = nil
    while j <= #tokens do
        local tok = tokens[j]
        if tok.kind == "punct" and tok.text == "(" then
            depth = depth + 1
        elseif tok.kind == "punct" and tok.text == ")" then
            depth = depth - 1
            if depth == 0 then
                close_pos = tok.pos
                break
            end
        end
        j = j + 1
    end
    if not close_pos then
        return prefix .. "(...)"
    end
    local raw = string.sub(src, tokens[func_idx].pos, close_pos)
    raw = string.gsub(raw, "[\n\r]", " ")
    return prefix .. raw
end

-- -- name reading ---------------------------------------------------------

local function last_segment(s)
    -- Match after last '.' or ':'. Return s if no separator.
    local tail = string.match(s, "[%.:]([^%.:]+)$")
    return tail or s
end

local function read_function_name(tokens, src, func_idx)
    -- Form 1: function [Name|M.Name|M:Name] (...)
    local j = func_idx + 1
    local parts = {}
    local colon_used = false
    while j <= #tokens do
        local tok = tokens[j]
        if tok.kind == "punct" and tok.text == "(" then
            local qualname = table.concat(parts)
            if qualname == "" then break end
            local name = last_segment(qualname)
            local sym_kind = colon_used and "method" or "function"
            if func_idx > 1
                and tokens[func_idx - 1].kind == "keyword"
                and tokens[func_idx - 1].text == "local" then
                sym_kind = "local_function"
            end
            local sig = slice_signature(src, tokens, func_idx, "")
            return qualname, name, sym_kind, sig
        end
        if tok.kind == "ident" then
            table.insert(parts, tok.text)
            j = j + 1
        elseif tok.kind == "punct" and (tok.text == "." or tok.text == ":") then
            table.insert(parts, tok.text)
            if tok.text == ":" then colon_used = true end
            j = j + 1
        else
            break
        end
    end

    -- Form 2: Name = function(...)   (incl. local Name = function)
    local k = func_idx - 1
    if k >= 1 and tokens[k].kind == "punct" and tokens[k].text == "=" then
        k = k - 1
        local rev = {}
        while k >= 1 do
            local tok = tokens[k]
            if tok.kind == "ident" then
                table.insert(rev, 1, tok.text)
                k = k - 1
            elseif tok.kind == "punct" and (tok.text == "." or tok.text == ":") then
                table.insert(rev, 1, tok.text)
                k = k - 1
            else
                break
            end
        end
        local qualname = table.concat(rev)
        if qualname == "" then return nil end
        local name = last_segment(qualname)
        local sym_kind = string.find(qualname, ":") and "method" or "assigned"
        local sig = slice_signature(src, tokens, func_idx, qualname .. " = ")
        return qualname, name, sym_kind, sig
    end
    return nil
end

-- -- block boundary -------------------------------------------------------

local function find_block_end(tokens, func_idx)
    local depth = 0
    local j = func_idx
    while j <= #tokens do
        local tok = tokens[j]
        if tok.kind == "keyword" then
            if OPENERS[tok.text] then
                depth = depth + 1
            elseif CLOSERS[tok.text] then
                depth = depth - 1
                if depth == 0 then return j end
            end
        end
        j = j + 1
    end
    return nil
end

-- -- main -----------------------------------------------------------------

local function source_hash(source)
    local h = 17
    for i = 1, #source do
        h = (h * 31 + string.byte(source, i)) % 2147483647
    end
    return h
end

local function collect(tokens, src, line_of)
    local symbols = {}
    local i = 1
    while i <= #tokens do
        local tok = tokens[i]
        if tok.kind == "keyword" and tok.text == "function" then
            local qualname, name, kind, sig = read_function_name(tokens, src, i)
            local end_idx = find_block_end(tokens, i)
            if qualname and end_idx then
                local end_tok = tokens[end_idx]
                local sym_text = string.sub(src, tok.pos, end_tok.pos + #end_tok.text - 1)
                table.insert(symbols, {
                    name = name,
                    qualname = qualname,
                    kind = kind,
                    line_start = line_of(tok.pos),
                    line_end = line_of(end_tok.pos),
                    signature = sig,
                    hash = source_hash(sym_text),
                    docstring = nil,
                    decorators = {},
                    parent = nil,
                })
                i = end_idx + 1
            else
                i = i + 1
            end
        else
            i = i + 1
        end
    end
    return symbols
end

function M.parse(src)
    local tokens = tokenize(src)
    local line_of = make_line_of(src)
    return collect(tokens, src, line_of)
end

return M
