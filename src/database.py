import sqlite3
import json
import csv
import io
import uuid
import time
from typing import List, Dict, Optional, Any
from pathlib import Path
from src.models import TelemetryPayload, AccountInfo

class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL,
                    display_name TEXT,
                    avatar_url TEXT,
                    is_tracking INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    start_time REAL NOT NULL,
                    end_time REAL,
                    initial_taps INTEGER DEFAULT 0,
                    final_taps INTEGER DEFAULT 0,
                    taps_gained INTEGER DEFAULT 0,
                    initial_rebirths INTEGER DEFAULT 0,
                    final_rebirths INTEGER DEFAULT 0,
                    rebirths_gained INTEGER DEFAULT 0,
                    max_tps REAL DEFAULT 0.0,
                    avg_tps REAL DEFAULT 0.0,
                    FOREIGN KEY(user_id) REFERENCES accounts(user_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    timestamp REAL NOT NULL,
                    current_taps INTEGER NOT NULL,
                    total_taps INTEGER DEFAULT 0,
                    tps REAL NOT NULL,
                    current_rebirths INTEGER DEFAULT 0,
                    current_wins INTEGER DEFAULT 0,
                    current_currency INTEGER DEFAULT 0,
                    total_pet_power REAL DEFAULT 0.0,
                    equipped_pets_json TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_snapshots_user_time ON snapshots(user_id, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, start_time DESC);
            """)

    def upsert_account(self, user_id: int, username: str, display_name: Optional[str] = None, avatar_url: Optional[str] = None) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO accounts (user_id, username, display_name, avatar_url, last_seen)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    display_name = COALESCE(excluded.display_name, accounts.display_name),
                    avatar_url = COALESCE(excluded.avatar_url, accounts.avatar_url),
                    last_seen = CURRENT_TIMESTAMP;
            """, (user_id, username, display_name, avatar_url))

    def set_account_tracking(self, user_id: int, is_tracking: bool) -> None:
        with self._get_connection() as conn:
            conn.execute("UPDATE accounts SET is_tracking = ? WHERE user_id = ?", (1 if is_tracking else 0, user_id))

    def get_accounts(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM accounts ORDER BY last_seen DESC;")
            return [dict(row) for row in cur.fetchall()]

    def get_account(self, user_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM accounts WHERE user_id = ?;", (user_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def delete_account(self, user_id: int) -> bool:
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM accounts WHERE user_id = ?;", (user_id,))
            return cur.rowcount > 0

    def start_session(self, user_id: int, start_time: float, initial_taps: int, initial_rebirths: int) -> str:
        session_id = str(uuid.uuid4())
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO sessions (session_id, user_id, start_time, initial_taps, initial_rebirths)
                VALUES (?, ?, ?, ?, ?);
            """, (session_id, user_id, start_time, initial_taps, initial_rebirths))
        return session_id

    def end_session(self, session_id: str, end_time: float, final_taps: int, final_rebirths: int, max_tps: float, avg_tps: float) -> None:
        with self._get_connection() as conn:
            cur = conn.execute("SELECT initial_taps, initial_rebirths FROM sessions WHERE session_id = ?;", (session_id,))
            row = cur.fetchone()
            if row:
                taps_gained = max(0, final_taps - row["initial_taps"])
                rebirths_gained = max(0, final_rebirths - row["initial_rebirths"])
                conn.execute("""
                    UPDATE sessions SET
                        end_time = ?,
                        final_taps = ?,
                        taps_gained = ?,
                        final_rebirths = ?,
                        rebirths_gained = ?,
                        max_tps = ?,
                        avg_tps = ?
                    WHERE session_id = ?;
                """, (end_time, final_taps, taps_gained, final_rebirths, rebirths_gained, max_tps, avg_tps, session_id))

    def get_active_session(self, user_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cur = conn.execute("""
                SELECT * FROM sessions WHERE user_id = ? AND end_time IS NULL ORDER BY start_time DESC LIMIT 1;
            """, (user_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def close_dangling_sessions(self) -> int:
        """Closes any sessions left open from prior unexpected shutdowns."""
        now = time.time()
        with self._get_connection() as conn:
            cur = conn.execute("""
                UPDATE sessions SET end_time = ? WHERE end_time IS NULL;
            """, (now,))
            return cur.rowcount

    def insert_snapshot(self, session_id: str, payload: TelemetryPayload, tps: float) -> None:
        pets_json = json.dumps([p.model_dump() for p in payload.equippedPets])
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO snapshots (
                    session_id, user_id, timestamp, current_taps, total_taps, tps,
                    current_rebirths, current_wins, current_currency, total_pet_power, equipped_pets_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                session_id, payload.userId, payload.timestamp, payload.currentTaps,
                payload.totalTaps, tps, payload.currentRebirths, payload.currentWins,
                payload.currentCurrency, payload.totalPetPower, pets_json
            ))

    def get_recent_snapshots(self, user_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cur = conn.execute("""
                SELECT * FROM snapshots WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?;
            """, (user_id, limit))
            rows = cur.fetchall()
            return [dict(r) for r in reversed(rows)]

    def get_sessions(self, user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cur = conn.execute("""
                SELECT * FROM sessions WHERE user_id = ? ORDER BY start_time DESC LIMIT ?;
            """, (user_id, limit))
            return [dict(r) for r in cur.fetchall()]

    def export_data(self, format: str = "json") -> str:
        with self._get_connection() as conn:
            accounts = [dict(r) for r in conn.execute("SELECT * FROM accounts;").fetchall()]
            sessions = [dict(r) for r in conn.execute("SELECT * FROM sessions;").fetchall()]
            snapshots = [dict(r) for r in conn.execute("SELECT * FROM snapshots ORDER BY id ASC;").fetchall()]

        if format.lower() == "json":
            return json.dumps({
                "accounts": accounts,
                "sessions": sessions,
                "snapshots": snapshots
            }, indent=2)
        elif format.lower() == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["--- ACCOUNTS ---"])
            if accounts:
                writer.writerow(list(accounts[0].keys()))
                for a in accounts:
                    writer.writerow(list(a.values()))
            
            writer.writerow([])
            writer.writerow(["--- SESSIONS ---"])
            if sessions:
                writer.writerow(list(sessions[0].keys()))
                for s in sessions:
                    writer.writerow(list(s.values()))

            writer.writerow([])
            writer.writerow(["--- SNAPSHOTS ---"])
            if snapshots:
                writer.writerow(list(snapshots[0].keys()))
                for sn in snapshots:
                    writer.writerow(list(sn.values()))

            return output.getvalue()
        else:
            raise ValueError(f"Unsupported format: {format}")

    def restore_data(self, json_str: str) -> bool:
        try:
            data = json.loads(json_str)
            with self._get_connection() as conn:
                for a in data.get("accounts", []):
                    conn.execute("""
                        INSERT OR REPLACE INTO accounts (user_id, username, display_name, avatar_url, is_tracking, created_at, last_seen)
                        VALUES (?, ?, ?, ?, ?, ?, ?);
                    """, (a["user_id"], a["username"], a.get("display_name"), a.get("avatar_url"), a.get("is_tracking", 1), a.get("created_at"), a.get("last_seen")))

                for s in data.get("sessions", []):
                    conn.execute("""
                        INSERT OR REPLACE INTO sessions (session_id, user_id, start_time, end_time, initial_taps, final_taps, taps_gained, initial_rebirths, final_rebirths, rebirths_gained, max_tps, avg_tps)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, (s["session_id"], s["user_id"], s["start_time"], s.get("end_time"), s.get("initial_taps", 0), s.get("final_taps", 0), s.get("taps_gained", 0), s.get("initial_rebirths", 0), s.get("final_rebirths", 0), s.get("rebirths_gained", 0), s.get("max_tps", 0.0), s.get("avg_tps", 0.0)))

                for sn in data.get("snapshots", []):
                    conn.execute("""
                        INSERT OR REPLACE INTO snapshots (id, session_id, user_id, timestamp, current_taps, total_taps, tps, current_rebirths, current_wins, current_currency, total_pet_power, equipped_pets_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, (sn.get("id"), sn["session_id"], sn["user_id"], sn["timestamp"], sn["current_taps"], sn.get("total_taps", 0), sn["tps"], sn.get("current_rebirths", 0), sn.get("current_wins", 0), sn.get("current_currency", 0), sn.get("total_pet_power", 0.0), sn.get("equipped_pets_json")))
            return True
        except Exception as e:
            return False
