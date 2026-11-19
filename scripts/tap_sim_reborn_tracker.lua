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

local SCRIPT_VERSION = "2.2.0"

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

local lastCatalogScanAt = 0

local function discoverGamePetCatalog()
    if os.time() - lastCatalogScanAt < 30 then
        return
    end
    lastCatalogScanAt = os.time()

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

    -- 3. Scan getgc(true) for static Pet Catalog definition tables
    if type(getgc) == "function" then
        pcall(function()
            local objs = getgc(true)
            local scanned = 0
            for _, tbl in ipairs(objs) do
                if type(tbl) == "table" then
                    scanned = scanned + 1
                    if scanned > 15000 then
                        break
                    end
                    local okIter, _ = pcall(function()
                        for k, v in pairs(tbl) do
                            if type(v) == "table" then
                                local rawName = rawget(v, "Name") or rawget(v, "name") or rawget(v, "DisplayName") or rawget(v, "displayName") or (type(k) == "string" and k)
                                local rawRarity = tostring(rawget(v, "Rarity") or rawget(v, "rarity") or rawget(v, "Tier") or rawget(v, "tier") or "")
                                local rawImg = extractAssetId(rawget(v, "Image") or rawget(v, "image") or rawget(v, "Icon") or rawget(v, "icon") or rawget(v, "Thumbnail") or rawget(v, "AssetId"))
                                local known = (type(rawName) == "string" and matchKnownSecret(rawName, rawImg)) or (type(k) == "string" and matchKnownSecret(k, rawImg))
                                if known or rawRarity:lower():find("secret", 1, true) then
                                    local finalName = (known and known.name) or (type(rawName) == "string" and not isBogusPetName(rawName) and rawName) or nil
                                    if finalName then
                                        local mult = parseFloatCompact(rawget(v, "Multiplier") or rawget(v, "multiplier") or rawget(v, "Power") or rawget(v, "power"))
                                        local info = {
                                            name = finalName,
                                            tier = detectTier(rawRarity) or (known and known.tier) or "Secret",
                                            egg = rawget(v, "Egg") or rawget(v, "egg") or (known and known.egg),
                                            imageAssetId = rawImg or (known and known.imageAssetId),
                                            multiplier = (mult and mult > 1) and mult or (known and known.multiplier),
                                        }
                                        registerKnownPet(finalName, info)
                                        if type(k) == "string" then
                                            registerKnownPet(k, info)
                                        end
                                        local rawId = rawget(v, "Id") or rawget(v, "id")
                                        if type(rawId) == "string" then
                                            registerKnownPet(rawId, info)
                                        end
                                    end
                                end
                            end
                        end
                    end)
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

-- Strategy 1: Read player's owned Pet Inventory directly from client memory (getgc) even when Pet UI is closed!
local function collectPetsFromGc()
    if type(getgc) ~= "function" then
        return nil, {}, 0, 0
    end
    local foundInventoryTable = false
    local aggregatedSecrets = {}
    local equippedList = {}
    local invCount = 0
    local totalPower = 0

    pcall(function()
        local objs = getgc(true)
        local scanned = 0
        for _, tbl in ipairs(objs) do
            if type(tbl) == "table" then
                scanned = scanned + 1
                if scanned > 18000 then
                    break
                end
                -- Look for a PlayerData / Replica / Profile / Inventory container table
                local petsSub = nil
                local equippedMap = nil
                pcall(function()
                    petsSub = rawget(tbl, "Pets") or rawget(tbl, "pets") or rawget(tbl, "OwnedPets") or rawget(tbl, "ownedPets") or rawget(tbl, "PetInventory")
                    local eqRaw = rawget(tbl, "EquippedPets") or rawget(tbl, "equippedPets") or rawget(tbl, "Equipped")
                    if type(eqRaw) == "table" then
                        equippedMap = {}
                        for ek, ev in pairs(eqRaw) do
                            if type(ev) == "string" then
                                equippedMap[ev] = true
                            elseif type(ek) == "string" and ev == true then
                                equippedMap[ek] = true
                            end
                        end
                    end
                end)

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
        pcall(function()
            for _, child in ipairs(ReplicatedStorage:GetChildren()) do
                table.insert(dump.replicatedStorageItems, { name = child.Name, className = child.ClassName, children = #child:GetChildren() })
            end
        end)
    end

    local pg = LocalPlayer:FindFirstChildOfClass("PlayerGui")
    if pg then
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

-- Start Reporter
attachHatchListeners()
if CONFIG.INSPECT_ON_START then
    task.spawn(sendInspectorSnapshot)
end

local keyStatus = (#CONFIG.API_KEY > 0) and "Key: set" or "Key: open"
print("[TrackStats v" .. SCRIPT_VERSION .. "] Live read-only telemetry started -> " .. CONFIG.ENDPOINT_URL .. " (" .. keyStatus .. ")")

task.spawn(function()
    while _G.__TapSimTrackStats_Token == RUN_TOKEN do
        local ok, err = pcall(function()
            local core = collectCoreStats()
            local secretPets, equippedPets, invCount, totalPetPower = collectPetsReadOnly()
            local boosts = collectActiveBoosts()

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
            }

            if secretPets ~= nil then
                payload.secretPets = secretPets
            end

            local okPost, resp = postJson(CONFIG.ENDPOINT_URL, payload)
            if CONFIG.AUTO_RELOAD and okPost and type(resp) == "table" and type(resp.Body) == "string" then
                local okDec, bodyTbl = pcall(function() return HttpService:JSONDecode(resp.Body) end)
                if okDec and type(bodyTbl) == "table" and type(bodyTbl.script_version) == "string" and bodyTbl.script_version ~= SCRIPT_VERSION then
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
