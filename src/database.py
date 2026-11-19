import sqlite3
import json
import csv
import io
import uuid
import time
import hashlib
from typing import List, Dict, Optional, Any
from pathlib import Path
from src.models import (
    TelemetryPayload,
    AccountInfo,
    BOGUS_SECRET_SLUGS,
    is_bogus_secret_name,
    slugify_pet_name,
    normalize_variant,
    sanitize_image_url,
    extract_asset_id,
)


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

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, column_ddl: str) -> None:
        cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table});").fetchall()}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_ddl};")

    def init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL,
                    display_name TEXT,
                    avatar_url TEXT,
                    is_tracking INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP,
                    world TEXT,
                    eggs_hatched INTEGER DEFAULT 0,
                    secret_count INTEGER DEFAULT 0,
                    last_client_source TEXT DEFAULT 'telemetry'
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
                    eggs_hatched INTEGER DEFAULT 0,
                    secret_count INTEGER DEFAULT 0,
                    world TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS account_secrets (
                    user_id INTEGER NOT NULL,
                    pet_key TEXT NOT NULL,
                    name TEXT NOT NULL,
                    variant TEXT NOT NULL DEFAULT 'Normal',
                    tier TEXT,
                    count INTEGER NOT NULL DEFAULT 1,
                    multiplier REAL DEFAULT 1.0,
                    power REAL DEFAULT 0.0,
                    is_equipped INTEGER DEFAULT 0,
                    egg_source TEXT,
                    image_asset_id INTEGER,
                    image_url TEXT,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (user_id, pet_key),
                    FOREIGN KEY (user_id) REFERENCES accounts(user_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS pet_catalog (
                    slug TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    rarity TEXT NOT NULL DEFAULT 'Secret',
                    tier TEXT,
                    default_egg TEXT,
                    odds TEXT,
                    image_asset_id INTEGER,
                    resolved_image_url TEXT,
                    custom_image_url TEXT,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS hatch_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT UNIQUE,
                    user_id INTEGER NULL,
                    actor_name TEXT,
                    pet_name TEXT NOT NULL,
                    rarity TEXT NOT NULL DEFAULT 'Secret',
                    variant TEXT NOT NULL DEFAULT 'Normal',
                    tier TEXT,
                    egg_name TEXT,
                    odds TEXT,
                    image_url TEXT,
                    source TEXT NOT NULL DEFAULT 'telemetry',
                    timestamp REAL NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES accounts(user_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS settings_kv (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS inspector_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    place_id INTEGER,
                    structure_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_snapshots_user_time ON snapshots(user_id, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, start_time DESC);
                CREATE INDEX IF NOT EXISTS idx_account_secrets_user ON account_secrets(user_id);
                CREATE INDEX IF NOT EXISTS idx_hatch_events_time ON hatch_events(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_hatch_events_user_time ON hatch_events(user_id, timestamp DESC);
                """
            )
            # Safe migrations for pre-v2 databases
            self._ensure_column(conn, "accounts", "world", "TEXT")
            self._ensure_column(conn, "accounts", "eggs_hatched", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "accounts", "secret_count", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "accounts", "last_client_source", "TEXT DEFAULT 'telemetry'")
            self._ensure_column(conn, "snapshots", "eggs_hatched", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "snapshots", "secret_count", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "snapshots", "world", "TEXT")
        self.purge_bogus_secrets()

    def purge_bogus_secrets(self) -> int:
        removed = 0
        with self._get_connection() as conn:
            sec_rows = conn.execute("SELECT user_id, pet_key, name FROM account_secrets;").fetchall()
            for r in sec_rows:
                if is_bogus_secret_name(r["name"]):
                    cur = conn.execute(
                        "DELETE FROM account_secrets WHERE user_id = ? AND pet_key = ?;",
                        (r["user_id"], r["pet_key"]),
                    )
                    removed += cur.rowcount

            hatch_rows = conn.execute("SELECT id, pet_name FROM hatch_events;").fetchall()
            for r in hatch_rows:
                if is_bogus_secret_name(r["pet_name"]):
                    cur = conn.execute("DELETE FROM hatch_events WHERE id = ?;", (r["id"],))
                    removed += cur.rowcount

            cat_rows = conn.execute("SELECT slug, name FROM pet_catalog;").fetchall()
            for r in cat_rows:
                if is_bogus_secret_name(r["name"]) or is_bogus_secret_name(r["slug"]):
                    cur = conn.execute("DELETE FROM pet_catalog WHERE slug = ?;", (r["slug"],))
                    removed += cur.rowcount

            if removed > 0:
                conn.execute(
                    """
                    UPDATE accounts
                    SET secret_count = COALESCE(
                        (SELECT SUM(count) FROM account_secrets WHERE account_secrets.user_id = accounts.user_id),
                        0
                    );
                    """
                )
        return removed

    def upsert_account(
        self,
        user_id: int,
        username: str,
        display_name: Optional[str] = None,
        avatar_url: Optional[str] = None,
    ) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO accounts (user_id, username, display_name, avatar_url, last_seen)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    display_name = COALESCE(excluded.display_name, accounts.display_name),
                    avatar_url = COALESCE(excluded.avatar_url, accounts.avatar_url),
                    last_seen = CURRENT_TIMESTAMP;
                """,
                (user_id, username, display_name, avatar_url),
            )

    def update_account_stats(
        self,
        user_id: int,
        world: Optional[str] = None,
        eggs_hatched: Optional[int] = None,
        secret_count: Optional[int] = None,
        client_source: Optional[str] = None,
    ) -> None:
        updates = []
        params: List[Any] = []
        if world is not None:
            updates.append("world = ?")
            params.append(world)
        if eggs_hatched is not None:
            updates.append("eggs_hatched = ?")
            params.append(int(eggs_hatched))
        if secret_count is not None:
            updates.append("secret_count = ?")
            params.append(max(0, int(secret_count)))
        if client_source is not None:
            updates.append("last_client_source = ?")
            params.append(client_source)
        if not updates:
            return
        updates.append("last_seen = CURRENT_TIMESTAMP")
        params.append(user_id)
        with self._get_connection() as conn:
            conn.execute(f"UPDATE accounts SET {', '.join(updates)} WHERE user_id = ?;", tuple(params))

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

    # --- Secret Vault persistence ---

    def replace_account_secrets(
        self,
        user_id: int,
        secrets: List[Dict[str, Any]],
        updated_at: Optional[float] = None,
        explicit_total_count: Optional[int] = None,
    ) -> int:
        ts = updated_at if updated_at is not None else time.time()
        aggregated: Dict[str, Dict[str, Any]] = {}
        for item in secrets:
            raw_name = (item.get("name") or "Unknown Secret").strip() or "Unknown Secret"
            variant = normalize_variant(item.get("variant"))
            pet_key = f"{slugify_pet_name(raw_name)}::{variant.lower()}"
            count = max(1, int(item.get("count", 1) or 1))
            multiplier = float(item.get("multiplier", 1.0) or 1.0)
            power = float(item.get("power", 0.0) or 0.0)
            is_equipped = 1 if (item.get("is_equipped") or item.get("isEquipped")) else 0
            tier = item.get("tier")
            egg_source = item.get("egg_source") or item.get("eggSource")
            asset_id = extract_asset_id(item.get("image_asset_id") or item.get("imageAssetId"))
            img_url = sanitize_image_url(item.get("image_url") or item.get("imageUrl"))

            if pet_key in aggregated:
                agg = aggregated[pet_key]
                agg["count"] += count
                agg["multiplier"] = max(agg["multiplier"], multiplier)
                agg["power"] = max(agg["power"], power)
                agg["is_equipped"] = max(agg["is_equipped"], is_equipped)
                if not agg["tier"] and tier:
                    agg["tier"] = tier
                if not agg["egg_source"] and egg_source:
                    agg["egg_source"] = egg_source
                if not agg["image_asset_id"] and asset_id:
                    agg["image_asset_id"] = asset_id
                if not agg["image_url"] and img_url:
                    agg["image_url"] = img_url
            else:
                aggregated[pet_key] = {
                    "pet_key": pet_key,
                    "name": raw_name,
                    "variant": variant,
                    "tier": tier,
                    "count": count,
                    "multiplier": multiplier,
                    "power": power,
                    "is_equipped": is_equipped,
                    "egg_source": egg_source,
                    "image_asset_id": asset_id,
                    "image_url": img_url,
                }

        summed = sum(v["count"] for v in aggregated.values())
        total_count = int(explicit_total_count) if (explicit_total_count is not None and explicit_total_count >= 0) else summed

        with self._get_connection() as conn:
            conn.execute("DELETE FROM account_secrets WHERE user_id = ?;", (user_id,))
            for agg in aggregated.values():
                conn.execute(
                    """
                    INSERT INTO account_secrets (
                        user_id, pet_key, name, variant, tier, count, multiplier, power,
                        is_equipped, egg_source, image_asset_id, image_url, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        user_id,
                        agg["pet_key"],
                        agg["name"],
                        agg["variant"],
                        agg["tier"],
                        agg["count"],
                        agg["multiplier"],
                        agg["power"],
                        agg["is_equipped"],
                        agg["egg_source"],
                        agg["image_asset_id"],
                        agg["image_url"],
                        ts,
                    ),
                )
            conn.execute("UPDATE accounts SET secret_count = ? WHERE user_id = ?;", (total_count, user_id))
        return total_count

    def increment_account_secret(
        self,
        user_id: int,
        name: str,
        variant: str = "Normal",
        tier: Optional[str] = None,
        egg_source: Optional[str] = None,
        image_asset_id: Optional[int] = None,
        image_url: Optional[str] = None,
        updated_at: Optional[float] = None,
        delta: int = 1,
    ) -> int:
        ts = updated_at if updated_at is not None else time.time()
        clean_name = (name or "Unknown Secret").strip() or "Unknown Secret"
        norm_variant = normalize_variant(variant)
        pet_key = f"{slugify_pet_name(clean_name)}::{norm_variant.lower()}"
        safe_url = sanitize_image_url(image_url)
        asset_id = extract_asset_id(image_asset_id)
        step = max(1, int(delta))

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO account_secrets (
                    user_id, pet_key, name, variant, tier, count, multiplier, power,
                    is_equipped, egg_source, image_asset_id, image_url, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1.0, 0.0, 0, ?, ?, ?, ?)
                ON CONFLICT(user_id, pet_key) DO UPDATE SET
                    count = account_secrets.count + excluded.count,
                    tier = COALESCE(excluded.tier, account_secrets.tier),
                    egg_source = COALESCE(excluded.egg_source, account_secrets.egg_source),
                    image_asset_id = COALESCE(excluded.image_asset_id, account_secrets.image_asset_id),
                    image_url = COALESCE(excluded.image_url, account_secrets.image_url),
                    updated_at = excluded.updated_at;
                """,
                (user_id, pet_key, clean_name, norm_variant, tier, step, egg_source, asset_id, safe_url, ts),
            )
            row = conn.execute(
                "SELECT COALESCE(SUM(count), 0) AS total FROM account_secrets WHERE user_id = ?;",
                (user_id,),
            ).fetchone()
            new_total = int(row["total"]) if row else 0
            conn.execute("UPDATE accounts SET secret_count = ? WHERE user_id = ?;", (new_total, user_id))
            return new_total

    def get_account_secrets(self, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            if user_id is not None:
                cur = conn.execute(
                    """
                    SELECT s.*, a.username, a.display_name, a.avatar_url
                    FROM account_secrets s
                    LEFT JOIN accounts a ON a.user_id = s.user_id
                    WHERE s.user_id = ?
                    ORDER BY s.count DESC, s.power DESC, s.name ASC;
                    """,
                    (user_id,),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT s.*, a.username, a.display_name, a.avatar_url
                    FROM account_secrets s
                    LEFT JOIN accounts a ON a.user_id = s.user_id
                    ORDER BY s.count DESC, s.power DESC, s.name ASC;
                    """
                )
            return [dict(r) for r in cur.fetchall()]

    # --- Pet Catalog persistence ---

    def upsert_pet_catalog(
        self,
        slug: str,
        name: str,
        rarity: str = "Secret",
        tier: Optional[str] = None,
        default_egg: Optional[str] = None,
        odds: Optional[str] = None,
        image_asset_id: Optional[int] = None,
        resolved_image_url: Optional[str] = None,
        custom_image_url: Optional[str] = None,
        overwrite_custom: bool = False,
    ) -> Dict[str, Any]:
        ts = time.time()
        clean_slug = slugify_pet_name(slug or name)
        safe_resolved = sanitize_image_url(resolved_image_url)
        safe_custom = sanitize_image_url(custom_image_url)
        clean_asset = extract_asset_id(image_asset_id)

        with self._get_connection() as conn:
            if overwrite_custom:
                conn.execute(
                    """
                    INSERT INTO pet_catalog (
                        slug, name, rarity, tier, default_egg, odds,
                        image_asset_id, resolved_image_url, custom_image_url, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(slug) DO UPDATE SET
                        name = COALESCE(excluded.name, pet_catalog.name),
                        rarity = COALESCE(excluded.rarity, pet_catalog.rarity),
                        tier = COALESCE(excluded.tier, pet_catalog.tier),
                        default_egg = COALESCE(excluded.default_egg, pet_catalog.default_egg),
                        odds = COALESCE(excluded.odds, pet_catalog.odds),
                        image_asset_id = COALESCE(excluded.image_asset_id, pet_catalog.image_asset_id),
                        resolved_image_url = COALESCE(excluded.resolved_image_url, pet_catalog.resolved_image_url),
                        custom_image_url = excluded.custom_image_url,
                        updated_at = excluded.updated_at;
                    """,
                    (clean_slug, name, rarity, tier, default_egg, odds, clean_asset, safe_resolved, safe_custom, ts),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO pet_catalog (
                        slug, name, rarity, tier, default_egg, odds,
                        image_asset_id, resolved_image_url, custom_image_url, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(slug) DO UPDATE SET
                        tier = COALESCE(pet_catalog.tier, excluded.tier),
                        default_egg = COALESCE(pet_catalog.default_egg, excluded.default_egg),
                        odds = COALESCE(pet_catalog.odds, excluded.odds),
                        image_asset_id = COALESCE(excluded.image_asset_id, pet_catalog.image_asset_id),
                        resolved_image_url = COALESCE(excluded.resolved_image_url, pet_catalog.resolved_image_url),
                        custom_image_url = COALESCE(excluded.custom_image_url, pet_catalog.custom_image_url),
                        updated_at = excluded.updated_at;
                    """,
                    (clean_slug, name, rarity, tier, default_egg, odds, clean_asset, safe_resolved, safe_custom, ts),
                )
            row = conn.execute("SELECT * FROM pet_catalog WHERE slug = ?;", (clean_slug,)).fetchone()
            return dict(row)

    def get_pet_catalog_item(self, slug: str) -> Optional[Dict[str, Any]]:
        clean_slug = slugify_pet_name(slug)
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM pet_catalog WHERE slug = ?;", (clean_slug,)).fetchone()
            return dict(row) if row else None

    def get_pet_catalog(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM pet_catalog ORDER BY tier DESC, name ASC;")
            return [dict(r) for r in cur.fetchall()]

    # --- Hatch Events persistence with 15s cross-source deduplication ---

    def record_hatch_event(
        self,
        event: Dict[str, Any],
        dedup_window_sec: float = 15.0,
    ) -> Optional[Dict[str, Any]]:
        user_id = event.get("user_id")
        actor_name = (event.get("actor_name") or "").strip() or (f"Player_{user_id}" if user_id is not None else "Unknown")
        pet_name = (event.get("pet_name") or "Unknown Pet").strip() or "Unknown Pet"
        rarity = (event.get("rarity") or "Secret").strip() or "Secret"
        variant = normalize_variant(event.get("variant"))
        tier = event.get("tier")
        egg_name = event.get("egg_name")
        odds = event.get("odds")
        image_url = sanitize_image_url(event.get("image_url"))
        source = (event.get("source") or "telemetry").strip() or "telemetry"
        ts = float(event.get("timestamp") if event.get("timestamp") is not None else time.time())

        pet_slug = slugify_pet_name(pet_name)
        explicit_key = event.get("event_key")
        if not explicit_key:
            raw_sig = f"{user_id}|{actor_name.lower()}|{pet_slug}|{variant.lower()}|{int(ts)}|{source}"
            event_key = hashlib.sha256(raw_sig.encode("utf-8")).hexdigest()[:32]
        else:
            event_key = str(explicit_key)

        with self._get_connection() as conn:
            # 1. Exact event_key deduplication
            if conn.execute("SELECT 1 FROM hatch_events WHERE event_key = ?;", (event_key,)).fetchone():
                return None

            # 2. Cross-source temporal deduplication within dedup_window_sec
            if dedup_window_sec > 0:
                if user_id is not None:
                    recent_rows = conn.execute(
                        """
                        SELECT pet_name, variant FROM hatch_events
                        WHERE user_id = ? AND ABS(timestamp - ?) <= ?;
                        """,
                        (user_id, ts, dedup_window_sec),
                    ).fetchall()
                else:
                    recent_rows = conn.execute(
                        """
                        SELECT pet_name, variant FROM hatch_events
                        WHERE user_id IS NULL AND LOWER(COALESCE(actor_name, '')) = LOWER(?)
                          AND ABS(timestamp - ?) <= ?;
                        """,
                        (actor_name, ts, dedup_window_sec),
                    ).fetchall()
                for rr in recent_rows:
                    if slugify_pet_name(rr["pet_name"]) == pet_slug and normalize_variant(rr["variant"]) == variant:
                        return None

            cur = conn.execute(
                """
                INSERT INTO hatch_events (
                    event_key, user_id, actor_name, pet_name, rarity, variant,
                    tier, egg_name, odds, image_url, source, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (event_key, user_id, actor_name, pet_name, rarity, variant, tier, egg_name, odds, image_url, source, ts),
            )
            inserted = conn.execute("SELECT * FROM hatch_events WHERE id = ?;", (cur.lastrowid,)).fetchone()
            return dict(inserted) if inserted else None

    def get_hatch_events(
        self,
        limit: int = 50,
        rarity: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        clauses = []
        params: List[Any] = []
        if rarity:
            clauses.append("LOWER(h.rarity) = LOWER(?)")
            params.append(rarity)
        if user_id is not None:
            clauses.append("h.user_id = ?")
            params.append(user_id)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(500, int(limit))))
        with self._get_connection() as conn:
            cur = conn.execute(
                f"""
                SELECT h.*, a.username, a.display_name, a.avatar_url
                FROM hatch_events h
                LEFT JOIN accounts a ON a.user_id = h.user_id
                {where_sql}
                ORDER BY h.timestamp DESC, h.id DESC
                LIMIT ?;
                """,
                tuple(params),
            )
            return [dict(r) for r in cur.fetchall()]

    # --- Settings KV & Inspector reports ---

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._get_connection() as conn:
            row = conn.execute("SELECT value_json FROM settings_kv WHERE key = ?;", (key,)).fetchone()
            if not row:
                return default
            try:
                return json.loads(row["value_json"])
            except Exception:
                return default

    def set_setting(self, key: str, value: Any) -> None:
        ts = time.time()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO settings_kv (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at;
                """,
                (key, json.dumps(value), ts),
            )

    def save_inspector_report(
        self,
        user_id: int,
        username: Optional[str],
        place_id: Optional[int],
        structure: Dict[str, Any],
        created_at: Optional[float] = None,
    ) -> Dict[str, Any]:
        ts = created_at if created_at is not None else time.time()
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO inspector_reports (user_id, username, place_id, structure_json, created_at)
                VALUES (?, ?, ?, ?, ?);
                """,
                (user_id, username or f"Player_{user_id}", place_id, json.dumps(structure), ts),
            )
            report_id = cur.lastrowid
            # Prune older than newest 10
            conn.execute(
                """
                DELETE FROM inspector_reports
                WHERE id NOT IN (
                    SELECT id FROM inspector_reports ORDER BY created_at DESC, id DESC LIMIT 10
                );
                """
            )
            row = conn.execute("SELECT * FROM inspector_reports WHERE id = ?;", (report_id,)).fetchone()
            rec = dict(row)
            rec["structure"] = json.loads(rec.pop("structure_json", "{}"))
            return rec

    def get_inspector_reports(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM inspector_reports ORDER BY created_at DESC, id DESC LIMIT ?;",
                (max(1, min(50, int(limit))),),
            )
            results = []
            for r in cur.fetchall():
                d = dict(r)
                try:
                    d["structure"] = json.loads(d.pop("structure_json", "{}"))
                except Exception:
                    d["structure"] = {}
                results.append(d)
            return results

    # --- Sessions & Snapshots (v1 preserved + v2 columns) ---

    def start_session(self, user_id: int, start_time: float, initial_taps: int, initial_rebirths: int) -> str:
        session_id = str(uuid.uuid4())
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, user_id, start_time, initial_taps, initial_rebirths)
                VALUES (?, ?, ?, ?, ?);
                """,
                (session_id, user_id, start_time, initial_taps, initial_rebirths),
            )
        return session_id

    def end_session(
        self,
        session_id: str,
        end_time: float,
        final_taps: int,
        final_rebirths: int,
        max_tps: float,
        avg_tps: float,
    ) -> None:
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT initial_taps, initial_rebirths FROM sessions WHERE session_id = ?;",
                (session_id,),
            )
            row = cur.fetchone()
            if row:
                taps_gained = max(0, final_taps - row["initial_taps"])
                rebirths_gained = max(0, final_rebirths - row["initial_rebirths"])
                conn.execute(
                    """
                    UPDATE sessions SET
                        end_time = ?,
                        final_taps = ?,
                        taps_gained = ?,
                        final_rebirths = ?,
                        rebirths_gained = ?,
                        max_tps = ?,
                        avg_tps = ?
                    WHERE session_id = ?;
                    """,
                    (end_time, final_taps, taps_gained, final_rebirths, rebirths_gained, max_tps, avg_tps, session_id),
                )

    def get_active_session(self, user_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                SELECT * FROM sessions WHERE user_id = ? AND end_time IS NULL ORDER BY start_time DESC LIMIT 1;
                """,
                (user_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def close_dangling_sessions(self) -> int:
        """Closes any sessions left open from prior unexpected shutdowns by recovering from snapshots."""
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT session_id, user_id, start_time, initial_taps, initial_rebirths FROM sessions WHERE end_time IS NULL;"
            )
            open_sessions = cur.fetchall()
            if not open_sessions:
                return 0

            for s in open_sessions:
                s_id = s["session_id"]
                snap_cur = conn.execute(
                    """
                    SELECT timestamp, total_taps, current_rebirths
                    FROM snapshots WHERE session_id = ? ORDER BY timestamp DESC LIMIT 1;
                    """,
                    (s_id,),
                )
                last_snap = snap_cur.fetchone()

                stats_cur = conn.execute(
                    """
                    SELECT MAX(tps) as max_tps, AVG(tps) as avg_tps
                    FROM snapshots WHERE session_id = ?;
                    """,
                    (s_id,),
                )
                stats = stats_cur.fetchone()

                if last_snap:
                    end_time = last_snap["timestamp"]
                    final_taps = last_snap["total_taps"]
                    final_rebirths = last_snap["current_rebirths"]
                    taps_gained = max(0, final_taps - s["initial_taps"])
                    rebirths_gained = max(0, final_rebirths - s["initial_rebirths"])
                    max_tps = stats["max_tps"] or 0.0
                    avg_tps = round(stats["avg_tps"] or 0.0, 2)
                else:
                    end_time = s["start_time"]
                    final_taps = s["initial_taps"]
                    final_rebirths = s["initial_rebirths"]
                    taps_gained = 0
                    rebirths_gained = 0
                    max_tps = 0.0
                    avg_tps = 0.0

                conn.execute(
                    """
                    UPDATE sessions SET
                        end_time = ?,
                        final_taps = ?,
                        taps_gained = ?,
                        final_rebirths = ?,
                        rebirths_gained = ?,
                        max_tps = ?,
                        avg_tps = ?
                    WHERE session_id = ?;
                    """,
                    (end_time, final_taps, taps_gained, final_rebirths, rebirths_gained, max_tps, avg_tps, s_id),
                )

            return len(open_sessions)

    def insert_snapshot(
        self,
        session_id: str,
        payload: TelemetryPayload,
        tps: float,
        secret_count: Optional[int] = None,
    ) -> None:
        pets_json = json.dumps([p.model_dump() for p in payload.equippedPets])
        sec_cnt = secret_count if secret_count is not None else (payload.secretCount or 0)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO snapshots (
                    session_id, user_id, timestamp, current_taps, total_taps, tps,
                    current_rebirths, current_wins, current_currency, total_pet_power,
                    equipped_pets_json, eggs_hatched, secret_count, world
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    session_id,
                    payload.userId,
                    payload.timestamp,
                    payload.currentTaps,
                    payload.totalTaps,
                    tps,
                    payload.currentRebirths,
                    payload.currentWins,
                    payload.currentCurrency,
                    payload.totalPetPower,
                    pets_json,
                    payload.eggsHatched,
                    int(sec_cnt),
                    payload.world,
                ),
            )

    def get_recent_snapshots(self, user_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                SELECT * FROM snapshots WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?;
                """,
                (user_id, limit),
            )
            rows = cur.fetchall()
            return [dict(r) for r in reversed(rows)]

    def get_sessions(self, user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                SELECT * FROM sessions WHERE user_id = ? ORDER BY start_time DESC LIMIT ?;
                """,
                (user_id, limit),
            )
            return [dict(r) for r in cur.fetchall()]

    def export_data(self, format: str = "json") -> str:
        with self._get_connection() as conn:
            accounts = [dict(r) for r in conn.execute("SELECT * FROM accounts;").fetchall()]
            sessions = [dict(r) for r in conn.execute("SELECT * FROM sessions;").fetchall()]
            snapshots = [dict(r) for r in conn.execute("SELECT * FROM snapshots ORDER BY id ASC;").fetchall()]
            account_secrets = [dict(r) for r in conn.execute("SELECT * FROM account_secrets;").fetchall()]
            pet_catalog = [dict(r) for r in conn.execute("SELECT * FROM pet_catalog;").fetchall()]
            hatch_events = [dict(r) for r in conn.execute("SELECT * FROM hatch_events ORDER BY id ASC;").fetchall()]

        if format.lower() == "json":
            return json.dumps(
                {
                    "accounts": accounts,
                    "sessions": sessions,
                    "snapshots": snapshots,
                    "account_secrets": account_secrets,
                    "pet_catalog": pet_catalog,
                    "hatch_events": hatch_events,
                },
                indent=2,
            )
        elif format.lower() == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            for label, rows in [
                ("ACCOUNTS", accounts),
                ("ACCOUNT_SECRETS", account_secrets),
                ("HATCH_EVENTS", hatch_events),
                ("SESSIONS", sessions),
                ("SNAPSHOTS", snapshots),
            ]:
                writer.writerow([f"--- {label} ---"])
                if rows:
                    writer.writerow(list(rows[0].keys()))
                    for row in rows:
                        writer.writerow(list(row.values()))
                writer.writerow([])
            return output.getvalue()
        else:
            raise ValueError(f"Unsupported format: {format}")

    def restore_data(self, json_str: str) -> bool:
        try:
            data = json.loads(json_str)
            with self._get_connection() as conn:
                for a in data.get("accounts", []):
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO accounts (
                            user_id, username, display_name, avatar_url, is_tracking,
                            created_at, last_seen, world, eggs_hatched, secret_count, last_client_source
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            a["user_id"],
                            a["username"],
                            a.get("display_name"),
                            a.get("avatar_url"),
                            a.get("is_tracking", 1),
                            a.get("created_at"),
                            a.get("last_seen"),
                            a.get("world"),
                            a.get("eggs_hatched") or 0,
                            a.get("secret_count") or 0,
                            a.get("last_client_source") or "telemetry",
                        ),
                    )

                for s in data.get("sessions", []):
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO sessions (
                            session_id, user_id, start_time, end_time, initial_taps, final_taps,
                            taps_gained, initial_rebirths, final_rebirths, rebirths_gained, max_tps, avg_tps
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            s["session_id"],
                            s["user_id"],
                            s["start_time"],
                            s.get("end_time"),
                            s.get("initial_taps", 0),
                            s.get("final_taps", 0),
                            s.get("taps_gained", 0),
                            s.get("initial_rebirths", 0),
                            s.get("final_rebirths", 0),
                            s.get("rebirths_gained", 0),
                            s.get("max_tps", 0.0),
                            s.get("avg_tps", 0.0),
                        ),
                    )

                for sn in data.get("snapshots", []):
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO snapshots (
                            id, session_id, user_id, timestamp, current_taps, total_taps, tps,
                            current_rebirths, current_wins, current_currency, total_pet_power,
                            equipped_pets_json, eggs_hatched, secret_count, world
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            sn.get("id"),
                            sn["session_id"],
                            sn["user_id"],
                            sn["timestamp"],
                            sn["current_taps"],
                            sn.get("total_taps", 0),
                            sn["tps"],
                            sn.get("current_rebirths", 0),
                            sn.get("current_wins", 0),
                            sn.get("current_currency", 0),
                            sn.get("total_pet_power", 0.0),
                            sn.get("equipped_pets_json"),
                            sn.get("eggs_hatched", 0),
                            sn.get("secret_count", 0),
                            sn.get("world"),
                        ),
                    )

                for sec in data.get("account_secrets", []):
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO account_secrets (
                            user_id, pet_key, name, variant, tier, count, multiplier, power,
                            is_equipped, egg_source, image_asset_id, image_url, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            sec["user_id"],
                            sec["pet_key"],
                            sec["name"],
                            sec.get("variant", "Normal"),
                            sec.get("tier"),
                            sec.get("count", 1),
                            sec.get("multiplier", 1.0),
                            sec.get("power", 0.0),
                            sec.get("is_equipped", 0),
                            sec.get("egg_source"),
                            sec.get("image_asset_id"),
                            sec.get("image_url"),
                            sec.get("updated_at", time.time()),
                        ),
                    )

                for cat in data.get("pet_catalog", []):
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO pet_catalog (
                            slug, name, rarity, tier, default_egg, odds,
                            image_asset_id, resolved_image_url, custom_image_url, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            cat["slug"],
                            cat["name"],
                            cat.get("rarity", "Secret"),
                            cat.get("tier"),
                            cat.get("default_egg"),
                            cat.get("odds"),
                            cat.get("image_asset_id"),
                            cat.get("resolved_image_url"),
                            cat.get("custom_image_url"),
                            cat.get("updated_at", time.time()),
                        ),
                    )

                for he in data.get("hatch_events", []):
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO hatch_events (
                            id, event_key, user_id, actor_name, pet_name, rarity, variant,
                            tier, egg_name, odds, image_url, source, timestamp
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            he.get("id"),
                            he.get("event_key"),
                            he.get("user_id"),
                            he.get("actor_name"),
                            he["pet_name"],
                            he.get("rarity", "Secret"),
                            he.get("variant", "Normal"),
                            he.get("tier"),
                            he.get("egg_name"),
                            he.get("odds"),
                            he.get("image_url"),
                            he.get("source", "telemetry"),
                            he["timestamp"],
                        ),
                    )
            return True
        except Exception:
            return False
