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

local CONFIG = {
    ENDPOINT_URL = "http://127.0.0.1:3883/api/v1/telemetry",
    INSPECT_URL = "http://127.0.0.1:3883/api/v1/connector/inspect",
    SEND_INTERVAL = 2.0,
    INSPECT_ON_START = true,
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

local Players = game:GetService("Players")
local HttpService = game:GetService("HttpService")
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

local function postJson(url, tableBody)
    local encoded = HttpService:JSONEncode(tableBody)
    local reqFn = getHttpRequestFn()
    if reqFn then
        local ok, resp = pcall(reqFn, {
            Url = url,
            Method = "POST",
            Headers = { ["Content-Type"] = "application/json" },
            Body = encoded,
        })
        return ok, resp
    end
    -- Fallback for Roblox Studio HttpService testing
    local ok, resp = pcall(function()
        return HttpService:RequestAsync({
            Url = url,
            Method = "POST",
            Headers = { ["Content-Type"] = "application/json" },
            Body = encoded,
        })
    end)
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

-- Finds candidate Pet Inventory ScrollingFrame/Container in PlayerGui
local function findPetContainer()
    if CONFIG.PATHS.PetListGui then
        return resolvePath(CONFIG.PATHS.PetListGui)
    end
    local pg = LocalPlayer:FindFirstChildOfClass("PlayerGui")
    if not pg then
        return nil
    end
    for _, gui in ipairs(pg:GetChildren()) do
        if gui:IsA("ScreenGui") and gui.Enabled then
            local gName = gui.Name:lower()
            for _, desc in ipairs(gui:GetDescendants()) do
                if desc:IsA("ScrollingFrame") and isGuiActuallyVisible(desc) then
                    local dName = desc.Name:lower()
                    local pName = desc.Parent and desc.Parent.Name:lower() or ""
                    if gName:find("pet", 1, true) or dName:find("pet", 1, true) or pName:find("pet", 1, true) or dName:find("inventory", 1, true) then
                        if #desc:GetChildren() > 0 then
                            return desc
                        end
                    end
                end
            end
        end
    end
    return nil
end

-- Collects pets ONLY when the inventory UI is visibly open (AFK Closed-Inventory Guard!)
-- Returns: (secretPetsOrNil, equippedPets, totalInvCount, totalPetPower)
local function collectPetsReadOnly()
    local container = findPetContainer()
    if not container or not isGuiActuallyVisible(container) then
        -- AFK Closed-Inventory Guard: return nil for secretPets so backend preserves Vault!
        return nil, {}, 0, 0
    end

    local secretPets = {}
    local equippedPets = {}
    local invCount = 0
    local totalPower = 0

    for _, card in ipairs(container:GetChildren()) do
        if card:IsA("GuiObject") and card.Visible and not card:IsA("UILayout") then
            invCount = invCount + 1
            local labels = {}
            local assetId = nil
            local isEquipped = false

            for _, desc in ipairs(card:GetDescendants()) do
                if (desc:IsA("TextLabel") or desc:IsA("TextButton")) and desc.Text and desc.Text ~= "" then
                    table.insert(labels, desc.Text)
                elseif (desc:IsA("ImageLabel") or desc:IsA("ImageButton")) and desc.Image and desc.Image ~= "" then
                    local extracted = extractAssetId(desc.Image)
                    if extracted and not assetId then
                        assetId = extracted
                    end
                    local nm = desc.Name:lower()
                    if (nm:find("equip", 1, true) or nm:find("check", 1, true)) and desc.Visible then
                        isEquipped = true
                    end
                end
            end

            local joined = table.concat(labels, " | ")
            local lowerJoined = joined:lower()
            local matchedKnown = nil
            for key, info in pairs(KNOWN_SECRETS) do
                if lowerJoined:find(key, 1, true) then
                    matchedKnown = info
                    break
                end
            end

            local isSecret = (matchedKnown ~= nil) or (lowerJoined:find("secret", 1, true) ~= nil)
            local petName = matchedKnown and matchedKnown.name or (labels[1] or card.Name)
            local variant = detectVariant(joined .. " " .. card.Name)
            local tier = detectTier(joined) or (matchedKnown and matchedKnown.tier) or (isSecret and "Secret" or nil)

            local mult = 1.0
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
            totalPower = totalPower + (power * count)

            if isSecret then
                table.insert(secretPets, {
                    id = card.Name,
                    name = petName,
                    rarity = "Secret",
                    variant = variant,
                    tier = tier,
                    count = count,
                    multiplier = mult,
                    power = power,
                    isEquipped = isEquipped,
                    eggSource = matchedKnown and matchedKnown.egg or nil,
                    imageAssetId = assetId,
                })
            end

            if isEquipped then
                table.insert(equippedPets, {
                    id = card.Name,
                    name = petName,
                    rarity = isSecret and "Secret" or "Mythic",
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

    return secretPets, equippedPets, invCount, totalPower
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
    if not (lower:find("hatched", 1, true) or lower:find("secret", 1, true)) then
        return
    end
    -- Only attribute messages that mention LocalPlayer or appear in LocalPlayer's own hatch popup
    local matchedKnown = nil
    for key, info in pairs(KNOWN_SECRETS) do
        if lower:find(key, 1, true) then
            matchedKnown = info
            break
        end
    end
    if not matchedKnown and not lower:find("secret", 1, true) then
        return
    end
    local petName = matchedKnown and matchedKnown.name or rawText:match("[Hh]atched%s+a?n?%s*([A-Za-z0-9%s]+)") or "Unknown Secret"
    petName = petName:gsub("^%s+", ""):gsub("%s+$", "")
    local variant = detectVariant(rawText)
    local odds = rawText:match("(1%s+in%s+[%d%.,]+[KMBT]?)")

    table.insert(pendingHatches, {
        petName = petName,
        rarity = "Secret",
        variant = variant,
        tier = detectTier(rawText) or (matchedKnown and matchedKnown.tier) or "Secret",
        eggName = matchedKnown and matchedKnown.egg or nil,
        odds = odds,
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

-- Inspector Mode: dumps bounded read-only hierarchy so user can configure CONFIG.PATHS in Web UI
local function sendInspectorSnapshot()
    local dump = {
        leaderstats = {},
        attributes = {},
        candidatePetGuis = {},
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

    local pg = LocalPlayer:FindFirstChildOfClass("PlayerGui")
    if pg then
        for _, gui in ipairs(pg:GetChildren()) do
            if gui:IsA("ScreenGui") then
                table.insert(dump.screenGuis, { name = gui.Name, enabled = gui.Enabled })
                for _, desc in ipairs(gui:GetDescendants()) do
                    if desc:IsA("ScrollingFrame") and #dump.candidatePetGuis < 20 then
                        local full = desc:GetFullName():gsub("^Players%.[^%.]+%.", "")
                        table.insert(dump.candidatePetGuis, {
                            path = full,
                            visible = isGuiActuallyVisible(desc),
                            children = #desc:GetChildren(),
                        })
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

print("[TrackStats v2] Live read-only telemetry started -> " .. CONFIG.ENDPOINT_URL)

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

            -- AFK Closed-Inventory Guard: only include secretPets when inventory UI is visibly open
            if secretPets ~= nil then
                payload.secretPets = secretPets
            end

            postJson(CONFIG.ENDPOINT_URL, payload)
        end)
        if not ok then
            logDebug("Tick error: " .. tostring(err))
        end
        task.wait(CONFIG.SEND_INTERVAL)
    end

    for _, conn in ipairs(connections) do
        pcall(function() conn:Disconnect() end)
    end
    print("[TrackStats v2] Stopped previous reporter instance.")
end)
