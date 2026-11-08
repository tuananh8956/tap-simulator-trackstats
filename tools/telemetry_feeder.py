#!/usr/bin/env python3
import time
import argparse
import random
import sys
import httpx
from typing import Dict, Any, List

SAMPLE_PETS = [
    {"id": "p_hydra", "name": "Dark Hydra", "rarity": "Mythic", "multiplier": 500.0, "power": 12500.0},
    {"id": "p_demon", "name": "Inferno Demon", "rarity": "Legendary", "multiplier": 200.0, "power": 5000.0},
    {"id": "p_dragon", "name": "Cyber Dragon", "rarity": "Epic", "multiplier": 75.0, "power": 1800.0},
    {"id": "p_hound", "name": "Neon Hound", "rarity": "Rare", "multiplier": 25.0, "power": 500.0},
    {"id": "p_cat", "name": "Lucky Cat", "rarity": "Common", "multiplier": 5.0, "power": 100.0}
]

def generate_payload(user_id: int, state: Dict[str, Any], delta_taps: int, delta_time: float, is_rebirth: bool = False) -> Dict[str, Any]:
    state["total_taps"] += delta_taps
    
    if is_rebirth:
        state["current_taps"] = 0
        state["rebirths"] += 1
        state["currency"] += int(delta_taps * 10)
        state["wins"] += 1
    else:
        state["current_taps"] += delta_taps
        state["currency"] += int(delta_taps * 2.5)

    now = time.time()
    pets = state.get("pets", [SAMPLE_PETS[0], SAMPLE_PETS[1]])
    total_power = sum(p.get("power", 0.0) for p in pets)

    return {
        "userId": user_id,
        "currentTaps": state["current_taps"],
        "totalTaps": state["total_taps"],
        "currentRebirths": state["rebirths"],
        "totalRebirths": state["rebirths"],
        "currentWins": state["wins"],
        "totalWins": state["wins"],
        "currentCurrency": state["currency"],
        "equippedPets": pets,
        "petInventoryCount": len(pets) + 10,
        "totalPetPower": total_power,
        "timestamp": now
    }

def run_feeder(url: str, user_id: int, target_tps: float, interval_sec: float, rebirth_interval_sec: float, count: int = -1):
    print("=" * 65)
    print("  TAP SIMULATOR REBORN – TELEMETRY FEEDER")
    print("=" * 65)
    print(f"  [+] Target URL:          {url}")
    print(f"  [+] Target User ID:      {user_id}")
    print(f"  [+] Simulating TPS:      {target_tps}")
    print(f"  [+] Telemetry Interval:  {interval_sec}s")
    print(f"  [+] Rebirth Interval:    {rebirth_interval_sec}s")
    print(f"  [+] Payload Count:       {'Infinite' if count < 0 else count}")
    print("=" * 65)
    print("  Streaming live telemetry... (Press Ctrl+C to stop)\n")

    state = {
        "current_taps": 5000,
        "total_taps": 100000,
        "rebirths": 5,
        "wins": 15,
        "currency": 2500000,
        "pets": [SAMPLE_PETS[0], SAMPLE_PETS[1], SAMPLE_PETS[2]]
    }

    sent = 0
    last_rebirth_time = time.time()
    client = httpx.Client(timeout=5.0)

    try:
        while count < 0 or sent < count:
            now = time.time()
            is_rebirth = (now - last_rebirth_time) >= rebirth_interval_sec
            if is_rebirth:
                last_rebirth_time = now

            # Calculate taps for this interval with slight jitter
            jitter = random.uniform(0.9, 1.1)
            delta_taps = int(target_tps * interval_sec * jitter)

            payload = generate_payload(user_id, state, delta_taps, interval_sec, is_rebirth=is_rebirth)
            
            t0 = time.time()
            try:
                resp = client.post(url, json=payload)
                elapsed_ms = round((time.time() - t0) * 1000, 1)
                res_data = resp.json() if resp.status_code == 200 else {}
                server_tps = res_data.get("tps", 0.0)
                status_badge = "REBIRTH!" if is_rebirth else "OK"
                
                print(f"[{time.strftime('%H:%M:%S')}] #{sent+1:04d} | Status: {status_badge:<8} | Taps: {state['current_taps']:,} | Total: {state['total_taps']:,} | Rebirths: {state['rebirths']} | Ingest TPS: {server_tps} | Latency: {elapsed_ms}ms")
            except Exception as e:
                print(f"[{time.strftime('%H:%M:%S')}] Connection error: {e}")

            sent += 1
            time.sleep(interval_sec)
    except KeyboardInterrupt:
        print("\n[!] Feeder stopped by user.")
    finally:
        client.close()

def main():
    parser = argparse.ArgumentParser(description="Live Telemetry Feeder for Tap Simulator Reborn TrackStats")
    parser.add_argument("--url", type=str, default="http://127.0.0.1:3883/api/v1/telemetry", help="Target endpoint")
    parser.add_argument("--user-id", type=int, default=12345678, help="Target Roblox User ID")
    parser.add_argument("--rate", type=float, default=25.0, help="Target Taps Per Second")
    parser.add_argument("--interval", type=float, default=1.0, help="Send interval in seconds")
    parser.add_argument("--rebirth-interval", type=float, default=90.0, help="Simulate rebirth every N seconds")
    parser.add_argument("--count", type=int, default=-1, help="Number of payloads to send (-1 for infinite)")
    args = parser.parse_args()

    run_feeder(
        url=args.url,
        user_id=args.user_id,
        target_tps=args.rate,
        interval_sec=args.interval,
        rebirth_interval_sec=args.rebirth_interval,
        count=args.count
    )

if __name__ == "__main__":
    main()
