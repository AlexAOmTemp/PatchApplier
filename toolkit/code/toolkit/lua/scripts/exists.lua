-- Check whether a DataModel path resolves to a LuaSourceContainer.
-- Returns '1' if yes, '0' otherwise. Never transfers Source.
-- Placeholder: %EXPR% — Lua expression resolving the instance.
local ok, t = pcall(function() return %EXPR% end)
if not ok or t == nil then return '0' end
if typeof(t) ~= 'Instance' then return '0' end
if not t:IsA('LuaSourceContainer') then return '0' end
return '1'
