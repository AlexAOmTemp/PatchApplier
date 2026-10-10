local M = {}

--- Adds two numbers.
--- @param a number
--- @param b number
--- @return number
function M.add(a, b)
    return a + b
end

--[[ Computes the peak power of a signal.
     Longer description here. ]]
function M.calculatePeakPower(signal, dt)
    local peak = 0
    for i = 1, #signal do
        local v = math.abs(signal[i])
        if v > peak then
            peak = v
        end
    end
    return peak
end

local function helper(x)
    return x * 2
end

return M
