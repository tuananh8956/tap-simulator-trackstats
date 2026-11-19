#!/usr/bin/env python3
import time
import argparse
import random
import httpx
from typing import Dict, Any, List

SAMPLE_PETS = [
    {"id": "p_hydra", "name": "Dark Hydra", "rarity": "Mythic", "variant": "Rainbow", "multiplier": 500.0, "power": 12500.0},
    {"id": "p_demon", "name": "Inferno Demon", "rarity": "Legendary", "variant": "Golden", "multiplier": 200.0, "power": 5000.0},
    {"id": "p_dragon", "name": "Cyber Dragon", "rarity": "Epic", "variant": "Normal", "multiplier": 75.0, "power": 1800.0},
    {"id": "p_hound", "name": "Neon Hound", "rarity": "Rare", "variant": "Normal", "multiplier": 25.0, "power": 500.0},
    {"id": "p_cat", "name": "Lucky Cat", "rarity": "Common", "variant": "Normal", "multiplier": 5.0, "power": 100.0},
]

SAMPLE_SECRETS = [
    {
        "id": "s_dark_cat",
        "name": "Dark Cat",
        "rarity": "Secret",
        "variant": "Rainbow",
        "tier": "Secret III",
        "count": 2,
        "multiplier": 28500.0,
        "power": 145000.0,
        "isEquipped": True,
        "eggSource": "Void Egg",
    },
    {
        "id": "s_king_of_hell",
        "name": "King Of Hell",
        "rarity": "Secret",
        "variant": "Golden",
        "tier": "Secret III",
        "count": 1,
        "multiplier": 22000.0,
        "power": 118000.0,
        "isEquipped": True,
        "eggSource": "Volcanic Egg",
    },
    {
        "id": "s_sanguine_heart",
        "name": "Sanguine Heart",
        "rarity": "Secret",
        "variant": "Diamond",
        "tier": "Secret III",
        "count": 2,
        "multiplier": 19500.0,
        "power": 98000.0,
        "isEquipped": True,
        "eggSource": "Crimson Egg",
    },
    {
        "id": "s_forsaken_knight",
        "name": "Forsaken Knight",
        "rarity": "Secret",
        "variant": "Shiny",
        "tier": "Secret III",
        "count": 1,
        "multiplier": 16000.0,
        "power": 82000.0,
        "isEquipped": False,
        "eggSource": "Void Egg",
    },
    {
        "id": "s_chronos",
        "name": "Chronos",
        "rarity": "Secret",
        "variant": "Golden",
        "tier": "Secret II",
        "count": 2,
        "multiplier": 12000.0,
        "power": 64000.0,
        "isEquipped": False,
        "eggSource": "Chronos Egg",
    },
    {
        "id": "s_void_overseer",
        "name": "Void Overseer",
        "rarity": "Secret",
        "variant": "Normal",
        "tier": "Secret II",
        "count": 3,
        "multiplier": 8500.0,
        "power": 46000.0,
        "isEquipped": False,
        "eggSource": "Void Egg",
    },
    {
        "id": "s_shinigami",
        "name": "Shinigami",
        "rarity": "Secret",
        "variant": "Rainbow",
        "tier": "Secret II",
        "count": 1,
        "multiplier": 14500.0,
        "power": 74000.0,
        "isEquipped": True,
        "eggSource": "Void Egg",
    },
    {
        "id": "s_void_wraith",
        "name": "Void Wraith",
        "rarity": "Secret",
        "variant": "Normal",
        "tier": "Secret I",
        "count": 4,
        "multiplier": 4200.0,
        "power": 21000.0,
        "isEquipped": False,
        "eggSource": "Void Egg",
    },
]

SAMPLE_WORLDS = ["Void Island", "Chronos Realm", "Draconic Volcano", "Crimson Citadel", "Celestial Sanctuary"]


def generate_payload(
    user_id: int,
    state: Dict[str, Any],
    delta_taps: int,
    delta_time: float,
    is_rebirth: bool = False,
    simulate_secret_hatch: bool = False,
) -> Dict[str, Any]:
    state["total_taps"] += delta_taps

    if is_rebirth:
        state["current_taps"] = 0
        state["rebirths"] += 1
        state["currency"] += int(delta_taps * 10)
        state["wins"] += 1
    else:
        state["current_taps"] += delta_taps
        state["currency"] += int(delta_taps * 2.5)

    state["eggs_hatched"] = state.get("eggs_hatched", 0) + max(1, int(delta_time * random.randint(4, 10)))

    now = time.time()
    pets = state.get("pets", [SAMPLE_PETS[0], SAMPLE_PETS[1]])
    secrets = state.get("secrets")
    recent_hatches: List[Dict[str, Any]] = []

    if simulate_secret_hatch:
        chosen = dict(random.choice(SAMPLE_SECRETS))
        chosen["count"] = 1
        if secrets is not None:
            merged = False
            for s in secrets:
                if s["name"] == chosen["name"] and s.get("variant", "Normal") == chosen["variant"]:
                    s["count"] = int(s.get("count", 1)) + 1
                    merged = True
                    break
            if not merged:
                secrets.append(chosen)
        recent_hatches.append(
            {
                "petName": chosen["name"],
                "rarity": "Secret",
                "variant": chosen.get("variant", "Normal"),
                "tier": chosen.get("tier", "Secret"),
                "eggName": chosen.get("eggSource", "Void Egg"),
                "odds": "1 in 4M" if chosen.get("tier") == "Secret III" else "1 in 1M",
                "timestamp": now,
            }
        )

    total_power = sum(p.get("power", 0.0) for p in pets)
    if secrets:
        total_power += sum(s.get("power", 0.0) * s.get("count", 1) for s in secrets if s.get("isEquipped"))

    boosts = state.get(
        "boosts",
        [
            {"name": "2x Luck Potion", "multiplier": "2x", "remainingSec": 900.0},
            {"name": "2x Taps Boost", "multiplier": "2x", "remainingSec": 540.0},
        ],
    )
    for b in boosts:
        b["remainingSec"] = max(60.0, float(b.get("remainingSec", 600.0)) - delta_time)

    payload: Dict[str, Any] = {
        "userId": user_id,
        "currentTaps": state["current_taps"],
        "totalTaps": state["total_taps"],
        "currentRebirths": state["rebirths"],
        "totalRebirths": state["rebirths"],
        "currentWins": state["wins"],
        "totalWins": state["wins"],
        "currentCurrency": state["currency"],
        "equippedPets": pets,
        "petInventoryCount": len(pets) + (sum(s.get("count", 1) for s in secrets) if secrets else 10),
        "totalPetPower": total_power,
        "eggsHatched": state["eggs_hatched"],
        "world": state.get("world", "Void Island"),
        "activeBoosts": boosts,
        "recentHatches": recent_hatches,
        "clientSource": "feeder",
        "timestamp": now,
    }
    if secrets is not None:
        payload["secretPets"] = secrets
    return payload


def _build_initial_account_state(idx: int) -> Dict[str, Any]:
    secret_slice = [dict(SAMPLE_SECRETS[(idx + offset) % len(SAMPLE_SECRETS)]) for offset in range(3)]
    for s in secret_slice:
        s["count"] = random.randint(1, 3)
    return {
        "current_taps": 50000 + idx * 125000,
        "total_taps": 1500000 + idx * 4500000,
        "rebirths": 12 + idx * 9,
        "wins": 40 + idx * 25,
        "currency": 8500000 + idx * 3200000,
        "eggs_hatched": 15000 + idx * 18400,
        "world": SAMPLE_WORLDS[idx % len(SAMPLE_WORLDS)],
        "pets": [SAMPLE_PETS[0], SAMPLE_PETS[1], SAMPLE_PETS[2]],
        "secrets": secret_slice,
        "boosts": [
            {"name": "Ultra Luck", "multiplier": "3x", "remainingSec": 1200.0 - idx * 120.0},
            {"name": "Super Taps", "multiplier": "2x", "remainingSec": 750.0 + idx * 90.0},
        ],
    }


def run_feeder(
    url: str,
    user_ids: List[int],
    target_tps: float,
    interval_sec: float,
    rebirth_interval_sec: float,
    hatch_interval_sec: float = 20.0,
    count: int = -1,
    ingest_key: str = "",
):
    print("=" * 72)
    print("  TAP SIMULATOR REBORN – TRACKSTATS v2 TELEMETRY FEEDER")
    print("=" * 72)
    print(f"  [+] Target URL:          {url}")
    print(f"  [+] Accounts ({len(user_ids)}):         {', '.join(map(str, user_ids))}")
    print(f"  [+] Simulating TPS/acc:  {target_tps}")
    print(f"  [+] Interval:            {interval_sec}s | Hatch Event: every {hatch_interval_sec}s")
    print("=" * 72)
    print("  Streaming live Secret + Farm telemetry... (Press Ctrl+C to stop)\n")

    states = {uid: _build_initial_account_state(idx) for idx, uid in enumerate(user_ids)}
    sent = 0
    last_rebirth = time.time()
    last_hatch = time.time()
    headers = {"X-TrackStats-Key": ingest_key} if ingest_key else {}
    client = httpx.Client(timeout=5.0, headers=headers)

    try:
        while count < 0 or sent < count:
            now = time.time()
            is_rebirth = (now - last_rebirth) >= rebirth_interval_sec
            if is_rebirth:
                last_rebirth = now

            trigger_hatch = (now - last_hatch) >= hatch_interval_sec
            if trigger_hatch:
                last_hatch = now

            hatch_lucky_uid = random.choice(user_ids) if trigger_hatch else None

            for uid in user_ids:
                jitter = random.uniform(0.85, 1.15)
                delta_taps = max(1, int(target_tps * interval_sec * jitter))
                do_hatch = uid == hatch_lucky_uid
                payload = generate_payload(
                    uid,
                    states[uid],
                    delta_taps,
                    interval_sec,
                    is_rebirth=is_rebirth,
                    simulate_secret_hatch=do_hatch,
                )
                try:
                    resp = client.post(url, json=payload)
                    res_data = resp.json() if resp.status_code == 200 else {}
                    tag = "SECRET!" if do_hatch else ("REBIRTH" if is_rebirth else "OK")
                    print(
                        f"[{time.strftime('%H:%M:%S')}] #{sent+1:04d} | UID:{uid} | {tag:<7} | "
                        f"Secrets:{res_data.get('secret_count', 0):<3} | TPS:{res_data.get('tps', 0.0):<6} | "
                        f"Eggs:{states[uid]['eggs_hatched']:,}"
                    )
                except Exception as e:
                    print(f"[{time.strftime('%H:%M:%S')}] UID:{uid} Connection error: {e}")

            sent += 1
            time.sleep(interval_sec)
    except KeyboardInterrupt:
        print("\n[!] Feeder stopped by user.")
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description="Live Telemetry Feeder for Tap Simulator Reborn TrackStats v2")
    parser.add_argument("--url", type=str, default="http://127.0.0.1:3883/api/v1/telemetry", help="Target endpoint")
    parser.add_argument("--user-id", type=int, default=12345678, help="Single Roblox User ID")
    parser.add_argument("--accounts", type=str, default="", help="Comma-separated Roblox User IDs")
    parser.add_argument("--multi", type=int, default=0, help="Simulate N accounts automatically")
    parser.add_argument("--rate", type=float, default=35.0, help="Target Taps Per Second per account")
    parser.add_argument("--interval", type=float, default=1.0, help="Send interval in seconds")
    parser.add_argument("--rebirth-interval", type=float, default=90.0, help="Simulate rebirth every N seconds")
    parser.add_argument("--hatch-interval", type=float, default=18.0, help="Simulate Secret hatch every N seconds")
    parser.add_argument("--count", type=int, default=-1, help="Number of ticks (-1 for infinite)")
    parser.add_argument("--key", type=str, default="", help="Optional X-TrackStats-Key for protected servers")
    args = parser.parse_args()

    if args.accounts.strip():
        user_ids = [int(x.strip()) for x in args.accounts.split(",") if x.strip()]
    elif args.multi > 0:
        user_ids = [10010001 + i for i in range(args.multi)]
    else:
        user_ids = [args.user_id]

    import os
    ingest_key = args.key.strip() or os.environ.get("TRACKSTATS_INGEST_KEY", "").strip()

    run_feeder(
        url=args.url,
        user_ids=user_ids,
        target_tps=args.rate,
        interval_sec=args.interval,
        rebirth_interval_sec=args.rebirth_interval,
        hatch_interval_sec=args.hatch_interval,
        count=args.count,
        ingest_key=ingest_key,
    )


if __name__ == "__main__":
    main()
