import time
import threading
from typing import Dict, Any, Optional, List
from src.database import Database
from src.rate_engine import RateEngine
from src.models import TelemetryPayload

class SessionManager:
    def __init__(self, db: Database, rate_engine: RateEngine, poller: Optional[Any] = None,
                 stale_timeout_sec: float = 15.0, disconnect_timeout_sec: float = 60.0):
        self.db = db
        self.rate_engine = rate_engine
        self.poller = poller
        self.stale_timeout_sec = stale_timeout_sec
        self.disconnect_timeout_sec = disconnect_timeout_sec

        self._lock = threading.Lock()
        self._last_payload: Dict[int, TelemetryPayload] = {}
        self._last_seen: Dict[int, float] = {}
        self._active_sessions: Dict[int, Optional[str]] = {}
        self._session_start_times: Dict[int, float] = {}
        self._connection_state: Dict[int, str] = {}

        # Clean any dangling sessions from a prior crash/restart
        self.db.close_dangling_sessions()

    def process_telemetry(self, payload: TelemetryPayload) -> Dict[str, Any]:
        with self._lock:
            user_id = payload.userId
            now = payload.timestamp

            # Ensure account exists in database
            acc = self.db.get_account(user_id)
            if not acc:
                self.db.upsert_account(user_id, f"Player_{user_id}", f"Player_{user_id}", "")
                acc = self.db.get_account(user_id)

            if not acc.get("is_tracking", 1):
                self._connection_state[user_id] = "PAUSED"
                return {"status": "paused", "user_id": user_id}

            # Check or create active session
            session_id = self._active_sessions.get(user_id)
            if not session_id:
                existing = self.db.get_active_session(user_id)
                if existing:
                    session_id = existing["session_id"]
                    self._session_start_times[user_id] = existing["start_time"]
                else:
                    session_id = self.db.start_session(user_id, now, payload.totalTaps, payload.currentRebirths)
                    self._session_start_times[user_id] = now
                self._active_sessions[user_id] = session_id

            # Update rate engine
            rate_res = self.rate_engine.add_record(user_id, payload)
            tps = rate_res["tps"]

            # Insert snapshot
            self.db.insert_snapshot(session_id, payload, tps)

            # Update in-memory state
            self._last_seen[user_id] = now
            self._last_payload[user_id] = payload
            self._connection_state[user_id] = "LIVE"

            return {
                "status": "processed",
                "user_id": user_id,
                "session_id": session_id,
                "tps": tps
            }

    def check_timeouts(self, now: Optional[float] = None) -> List[Dict[str, Any]]:
        current_time = now if now is not None else time.time()
        events = []

        with self._lock:
            # Check all tracked accounts
            accounts = self.db.get_accounts()
            for acc in accounts:
                user_id = acc["user_id"]
                if not acc["is_tracking"]:
                    self._connection_state[user_id] = "PAUSED"
                    continue

                session_id = self._active_sessions.get(user_id)
                last = self._last_seen.get(user_id)

                if session_id and last:
                    elapsed = current_time - last
                    if elapsed >= self.disconnect_timeout_sec:
                        # Session disconnect
                        rates = self.rate_engine.get_rates(user_id)
                        last_p = self._last_payload.get(user_id)
                        final_taps = last_p.totalTaps if last_p else 0
                        final_rebirths = last_p.currentRebirths if last_p else 0

                        self.db.end_session(
                            session_id, current_time, final_taps, final_rebirths,
                            rates["max_tps"], rates["avg_tps"]
                        )
                        self._active_sessions[user_id] = None
                        self._connection_state[user_id] = "DISCONNECTED"
                        self.rate_engine.reset_account(user_id)
                        events.append({"user_id": user_id, "event": "DISCONNECTED", "session_id": session_id})
                    elif elapsed >= self.stale_timeout_sec:
                        self._connection_state[user_id] = "STALE"
                        events.append({"user_id": user_id, "event": "STALE", "session_id": session_id})
                    else:
                        self._connection_state[user_id] = "LIVE"
                elif not session_id:
                    if user_id not in self._connection_state:
                        self._connection_state[user_id] = "IDLE"

        return events

    def get_live_state(self, user_id: int, now: Optional[float] = None) -> Dict[str, Any]:
        current_time = now if now is not None else time.time()
        with self._lock:
            acc = self.db.get_account(user_id) or {
                "user_id": user_id,
                "username": f"Player_{user_id}",
                "display_name": f"Player_{user_id}",
                "avatar_url": "",
                "is_tracking": 1
            }

            status = self._connection_state.get(user_id, "IDLE")
            last_p = self._last_payload.get(user_id)
            rates = self.rate_engine.get_rates(user_id)
            session_id = self._active_sessions.get(user_id)
            start_t = self._session_start_times.get(user_id, current_time)
            duration = max(0.0, current_time - start_t) if session_id else 0.0

            equipped = [p.model_dump() for p in last_p.equippedPets] if last_p else []

            return {
                "user_id": user_id,
                "username": acc.get("username", f"Player_{user_id}"),
                "display_name": acc.get("display_name", acc.get("username")),
                "avatar_url": acc.get("avatar_url", ""),
                "is_tracking": bool(acc.get("is_tracking", 1)),
                "connection_status": status,
                "active_session_id": session_id,
                "session_duration_sec": round(duration, 1),
                "current_taps": last_p.currentTaps if last_p else 0,
                "total_taps": last_p.totalTaps if last_p else 0,
                "current_rebirths": last_p.currentRebirths if last_p else 0,
                "total_rebirths": last_p.totalRebirths if last_p else 0,
                "current_wins": last_p.currentWins if last_p else 0,
                "total_wins": last_p.totalWins if last_p else 0,
                "current_currency": last_p.currentCurrency if last_p else 0,
                "equipped_pets": equipped,
                "pet_inventory_count": last_p.petInventoryCount if last_p else 0,
                "total_pet_power": last_p.totalPetPower if last_p else 0.0,
                "tps": rates.get("tps", 0.0),
                "max_tps": rates.get("max_tps", 0.0),
                "avg_tps": rates.get("avg_tps", 0.0),
                "rates": rates.get("windows", {}),
                "last_seen": self._last_seen.get(user_id, 0.0)
            }

    def toggle_tracking(self, user_id: int, is_tracking: bool) -> bool:
        with self._lock:
            self.db.set_account_tracking(user_id, is_tracking)
            if not is_tracking:
                session_id = self._active_sessions.get(user_id)
                if session_id:
                    now = time.time()
                    rates = self.rate_engine.get_rates(user_id)
                    last_p = self._last_payload.get(user_id)
                    final_taps = last_p.totalTaps if last_p else 0
                    final_rebirths = last_p.currentRebirths if last_p else 0

                    self.db.end_session(
                        session_id, now, final_taps, final_rebirths,
                        rates["max_tps"], rates["avg_tps"]
                    )
                    self._active_sessions[user_id] = None
                    self.rate_engine.reset_account(user_id)
                self._connection_state[user_id] = "PAUSED"
            else:
                self._connection_state[user_id] = "IDLE"
            return True

    def remove_account(self, user_id: int) -> None:
        """Cleans up all in-memory tracking structures when an account is deleted."""
        with self._lock:
            self._active_sessions.pop(user_id, None)
            self._last_seen.pop(user_id, None)
            self._last_payload.pop(user_id, None)
            self._session_start_times.pop(user_id, None)
            self._connection_state.pop(user_id, None)
            self.rate_engine.reset_account(user_id)
