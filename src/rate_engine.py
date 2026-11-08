from collections import deque
import threading
from typing import Dict, List, Optional, Any
from src.models import TelemetryPayload

class RateEngine:
    def __init__(self, max_window_sec: int = 900):
        self.max_window_sec = max_window_sec
        # user_id -> deque of records
        self._buffers: Dict[int, deque] = {}
        self._stats: Dict[int, Dict[str, float]] = {}
        self._lock = threading.Lock()

    def add_record(self, user_id: int, payload: TelemetryPayload) -> Dict[str, Any]:
        with self._lock:
            if user_id not in self._buffers:
                self._buffers[user_id] = deque()
                self._stats[user_id] = {
                    "max_tps": 0.0,
                    "total_tps_samples": 0.0,
                    "sample_count": 0
                }

            buf = self._buffers[user_id]
            stats = self._stats[user_id]

            if len(buf) == 0:
                tps = 0.0
                dt = 0.0
            else:
                prev = buf[-1]
                dt = payload.timestamp - prev["timestamp"]
                if dt < 0.001:
                    tps = prev["tps"]
                else:
                    if payload.currentTaps < prev["current_taps"]:
                        # Rebirth occurred: current taps reset, use total taps
                        delta_taps = max(0, payload.totalTaps - prev["total_taps"])
                    else:
                        delta_taps = payload.currentTaps - prev["current_taps"]

                    tps = round(delta_taps / dt, 2)

            if tps > 0:
                if tps > stats["max_tps"]:
                    stats["max_tps"] = tps
                stats["total_tps_samples"] += tps
                stats["sample_count"] += 1

            record = {
                "timestamp": payload.timestamp,
                "current_taps": payload.currentTaps,
                "total_taps": payload.totalTaps,
                "current_currency": payload.currentCurrency,
                "current_rebirths": payload.currentRebirths,
                "tps": tps
            }
            buf.append(record)

            # Prune records older than max_window_sec
            cutoff = payload.timestamp - self.max_window_sec
            while len(buf) > 1 and buf[0]["timestamp"] < cutoff:
                buf.popleft()

            return {"tps": tps, "delta_time": dt}

    def get_rates(self, user_id: int) -> Dict[str, Any]:
        with self._lock:
            buf = self._buffers.get(user_id)
            stats = self._stats.get(user_id, {"max_tps": 0.0, "total_tps_samples": 0.0, "sample_count": 0})
            
            if not buf:
                return {
                    "tps": 0.0,
                    "max_tps": 0.0,
                    "avg_tps": 0.0,
                    "windows": {
                        "1m": {"taps_gained": 0, "currency_gained": 0, "rebirths_gained": 0, "tps": 0.0},
                        "5m": {"taps_gained": 0, "currency_gained": 0, "rebirths_gained": 0, "tps": 0.0},
                        "15m": {"taps_gained": 0, "currency_gained": 0, "rebirths_gained": 0, "tps": 0.0}
                    }
                }

            latest = buf[-1]
            current_tps = latest["tps"]
            max_tps = stats["max_tps"]
            avg_tps = round(stats["total_tps_samples"] / max(1, stats["sample_count"]), 2)

            now = latest["timestamp"]
            windows = {}
            for name, duration in [("1m", 60), ("5m", 300), ("15m", 900)]:
                target_time = now - duration
                # Find oldest record >= target_time
                oldest = buf[0]
                for rec in buf:
                    if rec["timestamp"] >= target_time:
                        oldest = rec
                        break

                dt = max(1.0, now - oldest["timestamp"])
                # Use total_taps delta to correctly account for rebirth resets
                taps_gained = max(0, latest["total_taps"] - oldest["total_taps"])
                currency_gained = max(0, latest["current_currency"] - oldest["current_currency"])
                rebirths_gained = max(0, latest["current_rebirths"] - oldest["current_rebirths"])
                window_tps = round(taps_gained / dt, 2)

                windows[name] = {
                    "taps_gained": taps_gained,
                    "currency_gained": currency_gained,
                    "rebirths_gained": rebirths_gained,
                    "tps": window_tps
                }

            return {
                "tps": current_tps,
                "max_tps": max_tps,
                "avg_tps": avg_tps,
                "windows": windows
            }

    def reset_account(self, user_id: int) -> None:
        with self._lock:
            if user_id in self._buffers:
                del self._buffers[user_id]
            if user_id in self._stats:
                del self._stats[user_id]
