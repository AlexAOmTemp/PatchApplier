-- Enumerate LuaSourceContainers under a root instance.
-- Returns one line per module: "FullName|size_bytes|lines".
-- Placeholder: %EXPR% — Lua expression that resolves the root instance
--   (e.g. "game.ReplicatedStorage.Shared" or "game").
local ok, node = pcall(function() return %EXPR% end)
if not ok or node == nil then return '__MISSING__' end
local out = {}
local n = 0
for _, inst in ipairs(node:GetDescendants()) do
    if inst:IsA('LuaSourceContainer') then
        local src = inst.Source or ''
        local lines = 0
        for i = 1, #src do
            if string.byte(src, i) == 10 then lines = lines + 1 end
        end
        if #src > 0 and string.byte(src, #src) ~= 10 then lines = lines + 1 end
        table.insert(out, inst:GetFullName() .. '|' .. #src .. '|' .. lines)
        n = n + 1
        if n >= 500 then break end
    end
end
return table.concat(out, string.char(10))
