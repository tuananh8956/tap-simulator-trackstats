import time
import threading
from typing import Dict, Any, Optional, List, Tuple
from src.database import Database
from src.rate_engine import RateEngine
from src.pet_catalog import PetCatalogService
from src.models import (
    TelemetryPayload,
    AutoTradeSettingsUpdate,
    is_bogus_secret_name,
    slugify_pet_name,
    normalize_variant,
)


class SessionManager:
    def __init__(
        self,
        db: Database,
        rate_engine: RateEngine,
        poller: Optional[Any] = None,
        pet_catalog: Optional[PetCatalogService] = None,
        stale_timeout_sec: float = 15.0,
        disconnect_timeout_sec: float = 60.0,
    ):
        self.db = db
        self.rate_engine = rate_engine
        self.poller = poller
        self.pet_catalog = pet_catalog or PetCatalogService(db)
        self.stale_timeout_sec = stale_timeout_sec
        self.disconnect_timeout_sec = disconnect_timeout_sec

        self._lock = threading.Lock()
        self._last_payload: Dict[int, TelemetryPayload] = {}
        self._last_seen: Dict[int, float] = {}
        self._active_sessions: Dict[int, Optional[str]] = {}
        self._session_start_times: Dict[int, float] = {}
        self._connection_state: Dict[int, str] = {}
        self._last_authoritative_secret_sync: Dict[int, float] = {}
        self._had_secret_sync_in_session: Dict[int, bool] = {}
        self._active_boosts: Dict[int, List[Dict[str, Any]]] = {}
        self._boosts_timestamp: Dict[int, float] = {}
        self._world: Dict[int, Optional[str]] = {}
        self._eggs_hatched: Dict[int, int] = {}
        self._client_source: Dict[int, str] = {}

        # v2.4 Auto-Trade Coordinator state
        self._place_id: Dict[int, Optional[int]] = {}
        self._job_id: Dict[int, Optional[str]] = {}
        self._trade_state: Dict[int, str] = {}
        self._trade_message: Dict[int, Optional[str]] = {}
        self._secret_instance_ids: Dict[int, List[str]] = {}
        self._priority_trade_queue: List[int] = []
        self._active_trade_clone: Optional[int] = None
        self._active_trade_leased_at: float = 0.0
        self._trade_cooldown_until: Dict[int, float] = {}
        self._recent_trade_completions: List[Dict[str, Any]] = []

        # Clean any dangling sessions from a prior crash/restart
        self.db.close_dangling_sessions()

    def _resolve_main_account_locked(self) -> Dict[str, Any]:
        cfg = self.db.get_auto_trade_settings()
        accounts = self.db.get_accounts()
        acc_by_id = {int(a["user_id"]): a for a in accounts}
        acc_by_name = {(a.get("username") or "").strip().lower(): a for a in accounts if a.get("username")}

        main_uid = cfg.get("mainUserId")
        main_uname = (cfg.get("mainUsername") or "").strip()
        dirty = False

        if main_uname:
            matched = acc_by_name.get(main_uname.lower())
            if matched and (main_uid is None or int(matched["user_id"]) != int(main_uid)):
                main_uid = int(matched["user_id"])
                main_uname = matched.get("username") or main_uname
                dirty = True

        if main_uid is not None and int(main_uid) in acc_by_id and not main_uname:
            main_uname = acc_by_id[int(main_uid)].get("username") or ""
            if main_uname:
                dirty = True

        if dirty:
            cfg = self.db.save_auto_trade_settings(
                {
                    **cfg,
                    "mainUserId": main_uid,
                    "mainUsername": main_uname,
                }
            )
        return cfg

    def _reconcile_trade_queue_locked(self, now: Optional[float] = None) -> Dict[str, Any]:
        current_time = now if now is not None else time.time()
        cfg = self._resolve_main_account_locked()
        main_uid = cfg.get("mainUserId")
        main_uname = (cfg.get("mainUsername") or "").strip()

        accounts = self.db.get_accounts()
        acc_by_id = {int(a["user_id"]): a for a in accounts}
        trusted_user_ids = sorted(acc_by_id.keys())

        secret_counts: Dict[int, int] = {}
        for uid, acc in acc_by_id.items():
            secret_counts[uid] = int(acc.get("secret_count") or 0)

        main_online = bool(main_uid is not None and self._connection_state.get(int(main_uid)) == "LIVE")
        main_job_id = (self._job_id.get(int(main_uid)) or "").strip() if main_uid is not None else ""
        main_place_id = (
            int(self._place_id.get(int(main_uid)) or 72858262610964)
            if main_uid is not None
            else 72858262610964
        )
        main_ready = bool(main_online and main_job_id)

        # Clean priority queue of invalid or completed accounts
        self._priority_trade_queue = [
            uid
            for uid in self._priority_trade_queue
            if uid in acc_by_id
            and (main_uid is None or uid != int(main_uid))
            and secret_counts.get(uid, 0) > 0
            and self._connection_state.get(uid) == "LIVE"
        ]

        # Check active clone lease
        active = self._active_trade_clone
        lease_timeout = float(cfg.get("leaseTimeoutSec") or 120)
        if active is not None:
            active_state = (self._trade_state.get(active) or "IDLE").upper()
            active_secrets = secret_counts.get(active, 0)
            active_conn = self._connection_state.get(active, "IDLE")

            if (main_uid is not None and active == int(main_uid)) or active_conn != "LIVE":
                self._active_trade_clone = None
            elif active_secrets <= 0 or (active_state == "COMPLETED" and active_secrets <= 0):
                self._recent_trade_completions.insert(
                    0,
                    {
                        "user_id": active,
                        "username": acc_by_id.get(active, {}).get("username") or f"Player_{active}",
                        "completed_at": current_time,
                    },
                )
                del self._recent_trade_completions[20:]
                if active in self._priority_trade_queue:
                    self._priority_trade_queue.remove(active)
                self._trade_cooldown_until[active] = current_time + 15.0
                self._active_trade_clone = None
            elif active_state == "ERROR":
                if active in self._priority_trade_queue:
                    self._priority_trade_queue.remove(active)
                self._trade_cooldown_until[active] = current_time + 15.0
                self._active_trade_clone = None
            elif (current_time - self._active_trade_leased_at) >= lease_timeout:
                if active in self._priority_trade_queue:
                    self._priority_trade_queue.remove(active)
                self._trade_cooldown_until[active] = current_time + 15.0
                self._active_trade_clone = None

        # Build ordered candidate queue (priority queue first, then automatic queue if enabled)
        ordered_queue: List[int] = []
        seen_q = set()

        for uid in self._priority_trade_queue:
            if (
                uid not in seen_q
                and (main_uid is None or uid != int(main_uid))
                and self._connection_state.get(uid) == "LIVE"
                and secret_counts.get(uid, 0) > 0
                and current_time >= self._trade_cooldown_until.get(uid, 0.0)
            ):
                ordered_queue.append(uid)
                seen_q.add(uid)

        if cfg.get("enabled"):
            auto_candidates = [
                uid
                for uid in acc_by_id
                if uid not in seen_q
                and (main_uid is None or uid != int(main_uid))
                and self._connection_state.get(uid) == "LIVE"
                and secret_counts.get(uid, 0) > 0
                and current_time >= self._trade_cooldown_until.get(uid, 0.0)
            ]
            auto_candidates.sort(key=lambda u: (-secret_counts.get(u, 0), u))
            for uid in auto_candidates:
                ordered_queue.append(uid)
                seen_q.add(uid)

            if not ordered_queue:
                cooldown_candidates = [
                    uid
                    for uid in acc_by_id
                    if (main_uid is None or uid != int(main_uid))
                    and self._connection_state.get(uid) == "LIVE"
                    and secret_counts.get(uid, 0) > 0
                ]
                cooldown_candidates.sort(
                    key=lambda u: (self._trade_cooldown_until.get(u, 0.0), -secret_counts.get(u, 0), u)
                )
                ordered_queue.extend(cooldown_candidates)

        if main_ready:
            if self._active_trade_clone is None and ordered_queue:
                self._active_trade_clone = ordered_queue[0]
                self._active_trade_leased_at = current_time
            elif self._active_trade_clone is not None and self._active_trade_clone not in ordered_queue:
                self._active_trade_clone = ordered_queue[0] if ordered_queue else None
                if self._active_trade_clone is not None:
                    self._active_trade_leased_at = current_time
        else:
            self._active_trade_clone = None

        active_uid = self._active_trade_clone
        active_acc = acc_by_id.get(active_uid) if active_uid is not None else None

        queue_items = []
        for idx, uid in enumerate(ordered_queue):
            a = acc_by_id.get(uid, {})
            queue_items.append(
                {
                    "position": idx + 1,
                    "user_id": uid,
                    "username": a.get("username") or f"Player_{uid}",
                    "secret_count": secret_counts.get(uid, 0),
                    "is_active": uid == active_uid,
                    "trade_state": self._trade_state.get(uid, "QUEUED" if uid != active_uid else "ACTIVE"),
                    "trade_message": self._trade_message.get(uid),
                    "job_id": self._job_id.get(uid),
                }
            )

        return {
            "settings": cfg,
            "main_user_id": main_uid,
            "main_username": main_uname,
            "main_online": main_online,
            "main_ready": main_ready,
            "main_place_id": main_place_id,
            "main_job_id": main_job_id or None,
            "active_clone_id": active_uid,
            "active_clone_username": (active_acc.get("username") if active_acc else None),
            "active_clone_secrets": (secret_counts.get(active_uid, 0) if active_uid is not None else 0),
            "active_clone_state": (self._trade_state.get(active_uid, "IDLE") if active_uid is not None else None),
            "active_lease_elapsed_sec": (
                round(max(0.0, current_time - self._active_trade_leased_at), 1) if active_uid is not None else 0.0
            ),
            "queue_count": len(queue_items),
            "total_pending_secrets": sum(item["secret_count"] for item in queue_items),
            "queue": queue_items,
            "trusted_user_ids": trusted_user_ids,
            "recent_completions": list(self._recent_trade_completions),
        }

    def _build_trade_directive_locked(self, user_id: int, status: Dict[str, Any]) -> Dict[str, Any]:
        cfg = status["settings"]
        main_uid = status["main_user_id"]
        active_uid = status["active_clone_id"]
        queue_ids = [item["user_id"] for item in status["queue"]]
        is_enabled_or_queued = bool(cfg.get("enabled") or user_id in queue_ids or user_id == active_uid)

        if main_uid is not None and int(user_id) == int(main_uid):
            return {
                "enabled": bool(cfg.get("enabled") or active_uid is not None or len(queue_ids) > 0),
                "role": "MAIN",
                "action": "AUTO_ACCEPT",
                "mainUserId": main_uid,
                "mainUsername": status["main_username"],
                "activeCloneUserId": active_uid,
                "activeCloneUsername": status["active_clone_username"],
                "trustedUserIds": status["trusted_user_ids"],
            }

        if active_uid is not None and int(user_id) == int(active_uid) and status["main_ready"]:
            return {
                "enabled": True,
                "role": "CLONE_ACTIVE",
                "action": "JOIN_AND_TRADE",
                "mainUserId": main_uid,
                "mainUsername": status["main_username"],
                "mainPlaceId": status["main_place_id"],
                "mainJobId": status["main_job_id"],
                "unequipSecrets": bool(cfg.get("unequipSecrets", True)),
                "unlockSecrets": bool(cfg.get("unlockSecrets", True)),
                "hopOutAfterTrade": bool(cfg.get("hopOutAfterTrade", True)),
            }

        if is_enabled_or_queued and user_id in queue_ids:
            pos = queue_ids.index(user_id) + 1
            return {
                "enabled": True,
                "role": "CLONE_QUEUED",
                "action": "WAIT",
                "queuePosition": pos,
                "mainUserId": main_uid,
                "mainUsername": status["main_username"],
                "mainReady": status["main_ready"],
            }

        return {
            "enabled": bool(cfg.get("enabled")),
            "role": "IDLE",
            "action": "NONE",
            "mainUserId": main_uid,
            "mainUsername": status["main_username"],
        }

    def get_trade_status(self, now: Optional[float] = None) -> Dict[str, Any]:
        with self._lock:
            return self._reconcile_trade_queue_locked(now=now)

    def update_trade_settings(self, req: AutoTradeSettingsUpdate, now: Optional[float] = None) -> Dict[str, Any]:
        with self._lock:
            current = self.db.get_auto_trade_settings()
            patch = req.model_dump(exclude_unset=True)
            if "mainUsername" in patch and patch["mainUsername"] is not None:
                patch["mainUsername"] = str(patch["mainUsername"]).strip()
                # If username changed and mainUserId wasn't explicitly set in the request, reset mainUserId so it resolves cleanly
                if "mainUserId" not in patch and patch["mainUsername"].lower() != (current.get("mainUsername") or "").lower():
                    patch["mainUserId"] = None
            self.db.save_auto_trade_settings({**current, **patch})
            return self._reconcile_trade_queue_locked(now=now)

    def enqueue_clone_for_trade(self, user_id: int, now: Optional[float] = None) -> Dict[str, Any]:
        current_time = now if now is not None else time.time()
        with self._lock:
            self._trade_cooldown_until.pop(user_id, None)
            if user_id in self._priority_trade_queue:
                self._priority_trade_queue.remove(user_id)
            self._priority_trade_queue.insert(0, user_id)
            self._trade_state[user_id] = "QUEUED"
            # Preempt non-priority active clone if this user was explicitly manually queued
            if self._active_trade_clone is not None and self._active_trade_clone != user_id:
                if self._active_trade_clone not in self._priority_trade_queue:
                    self._active_trade_clone = None
            return self._reconcile_trade_queue_locked(now=current_time)

    def enqueue_all_clones_for_trade(self, now: Optional[float] = None) -> Dict[str, Any]:
        current_time = now if now is not None else time.time()
        with self._lock:
            self._trade_cooldown_until.clear()
            cfg = self._resolve_main_account_locked()
            main_uid = cfg.get("mainUserId")
            accounts = self.db.get_accounts()
            eligible = [
                int(a["user_id"])
                for a in accounts
                if (main_uid is None or int(a["user_id"]) != int(main_uid))
                and int(a.get("secret_count") or 0) > 0
                and self._connection_state.get(int(a["user_id"])) == "LIVE"
            ]
            eligible.sort(
                key=lambda u: (
                    -int(next((a.get("secret_count") or 0 for a in accounts if int(a["user_id"]) == u), 0)),
                    u,
                )
            )
            self._priority_trade_queue = eligible
            return self._reconcile_trade_queue_locked(now=current_time)

    def skip_active_trade_clone(self, now: Optional[float] = None) -> Dict[str, Any]:
        current_time = now if now is not None else time.time()
        with self._lock:
            active = self._active_trade_clone
            if active is not None:
                if active in self._priority_trade_queue:
                    self._priority_trade_queue.remove(active)
                self._trade_cooldown_until[active] = current_time + 20.0
                self._active_trade_clone = None
            return self._reconcile_trade_queue_locked(now=current_time)

    def _collect_pending_asset(
        self,
        pet_name: str,
        asset_id: Optional[int],
        pending: List[Tuple[str, int]],
    ) -> None:
        if not asset_id:
            return
        slug = slugify_pet_name(pet_name)
        existing = self.db.get_pet_catalog_item(slug)
        if not existing or not existing.get("resolved_image_url"):
            pair = (slug, int(asset_id))
            if pair not in pending:
                pending.append(pair)

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
                return {
                    "status": "paused",
                    "user_id": user_id,
                    "new_hatches": [],
                    "pending_asset_ids": [],
                    "needs_profile_lookup": False,
                }

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
                    self._had_secret_sync_in_session[user_id] = False
                self._active_sessions[user_id] = session_id

            # Update rate engine
            rate_res = self.rate_engine.add_record(user_id, payload)
            tps = rate_res["tps"]

            pending_asset_ids: List[Tuple[str, int]] = []
            new_hatches: List[Dict[str, Any]] = []
            actor_name = acc.get("username") or f"Player_{user_id}"

            # Register any equipped/secret pets in catalog
            for ep in payload.equippedPets:
                if ep.imageAssetId:
                    self.pet_catalog.register_discovered_pet(
                        ep.name, rarity=ep.rarity, tier=ep.tier, egg_source=ep.eggSource, image_asset_id=ep.imageAssetId
                    )
                    self._collect_pending_asset(ep.name, ep.imageAssetId, pending_asset_ids)

            # 1) Process explicit recentHatches first (with 15s cross-source dedup)
            for h in payload.recentHatches:
                if is_bogus_secret_name(h.petName):
                    continue
                canonical_pet_name = self.pet_catalog.canonical_name(h.petName)
                self.pet_catalog.register_discovered_pet(
                    canonical_pet_name,
                    rarity=h.rarity,
                    tier=h.tier,
                    egg_source=h.eggName,
                    odds=h.odds,
                    image_asset_id=h.imageAssetId,
                )
                self._collect_pending_asset(canonical_pet_name, h.imageAssetId, pending_asset_ids)
                img_url = self.pet_catalog.resolve_image_url(canonical_pet_name, explicit_url=h.imageUrl, asset_id=h.imageAssetId)
                recorded = self.db.record_hatch_event(
                    {
                        "event_key": h.eventId,
                        "user_id": user_id,
                        "actor_name": actor_name,
                        "pet_name": canonical_pet_name,
                        "rarity": h.rarity,
                        "variant": h.variant,
                        "tier": h.tier,
                        "egg_name": h.eggName,
                        "odds": h.odds,
                        "image_url": img_url,
                        "source": payload.clientSource or "telemetry",
                        "timestamp": h.timestamp if h.timestamp is not None else now,
                    },
                    dedup_window_sec=15.0,
                )
                if recorded:
                    recorded["username"] = actor_name
                    recorded["image_url"] = img_url
                    new_hatches.append(recorded)
                    # AFK closed-inventory Secret increment when secretPets is omitted
                    if payload.secretPets is None and (h.rarity or "").lower() == "secret":
                        self.db.increment_account_secret(
                            user_id=user_id,
                            name=canonical_pet_name,
                            variant=h.variant,
                            tier=h.tier,
                            egg_source=h.eggName,
                            image_asset_id=h.imageAssetId,
                            image_url=h.imageUrl,
                            updated_at=now,
                        )

            # 2) Sync Secret Pets (authoritative replacement when secretPets is not None, preserve when None)
            prev_rows = self.db.get_account_secrets(user_id)
            prev_counts = {r["pet_key"]: int(r["count"]) for r in prev_rows}

            if payload.secretPets is not None:
                valid_secret_dumps: List[Dict[str, Any]] = []
                for sp in payload.secretPets:
                    if is_bogus_secret_name(sp.name):
                        continue
                    canon_name = self.pet_catalog.canonical_name(sp.name)
                    self.pet_catalog.register_discovered_pet(
                        canon_name,
                        rarity="Secret",
                        tier=sp.tier,
                        egg_source=sp.eggSource,
                        image_asset_id=sp.imageAssetId,
                    )
                    self._collect_pending_asset(canon_name, sp.imageAssetId, pending_asset_ids)
                    dumped = sp.model_dump()
                    dumped["name"] = canon_name
                    valid_secret_dumps.append(dumped)

                secret_count = self.db.replace_account_secrets(
                    user_id=user_id,
                    secrets=valid_secret_dumps,
                    updated_at=now,
                    explicit_total_count=payload.secretCount,
                )

                # Delta secret hatch detection after first authoritative sync in this session
                if self._had_secret_sync_in_session.get(user_id):
                    curr_rows = self.db.get_account_secrets(user_id)
                    for row in curr_rows:
                        delta = int(row["count"]) - prev_counts.get(row["pet_key"], 0)
                        if delta > 0:
                            img_url = self.pet_catalog.resolve_image_url(
                                row["name"], explicit_url=row.get("image_url"), asset_id=row.get("image_asset_id")
                            )
                            for i in range(min(delta, 5)):
                                rec = self.db.record_hatch_event(
                                    {
                                        "event_key": f"delta:{user_id}:{row['pet_key']}:{round(now, 3)}:{i}",
                                        "user_id": user_id,
                                        "actor_name": actor_name,
                                        "pet_name": row["name"],
                                        "rarity": "Secret",
                                        "variant": row["variant"],
                                        "tier": row.get("tier"),
                                        "egg_name": row.get("egg_source"),
                                        "image_url": img_url,
                                        "source": "delta_detected",
                                        "timestamp": now + (i * 0.001),
                                    },
                                    dedup_window_sec=15.0 if i == 0 else 0.0,
                                )
                                if rec:
                                    rec["username"] = actor_name
                                    rec["image_url"] = img_url
                                    new_hatches.append(rec)

                self._had_secret_sync_in_session[user_id] = True
                self._last_authoritative_secret_sync[user_id] = now
            else:
                # Preserve existing account_secrets
                curr_rows = self.db.get_account_secrets(user_id)
                if payload.secretCount is not None:
                    secret_count = max(0, int(payload.secretCount))
                elif curr_rows:
                    secret_count = sum(int(r["count"]) for r in curr_rows)
                else:
                    secret_count = sum(
                        max(1, int(p.count)) for p in payload.equippedPets if (p.rarity or "").lower() == "secret"
                    )

            # Persist account metadata & snapshot
            if payload.world is not None:
                self._world[user_id] = payload.world
            if payload.eggsHatched > 0 or user_id not in self._eggs_hatched:
                self._eggs_hatched[user_id] = max(payload.eggsHatched, self._eggs_hatched.get(user_id, 0))
            self._client_source[user_id] = payload.clientSource or "telemetry"

            if payload.activeBoosts:
                self._active_boosts[user_id] = [b.model_dump() for b in payload.activeBoosts]
                self._boosts_timestamp[user_id] = now
            elif user_id not in self._active_boosts:
                self._active_boosts[user_id] = []
                self._boosts_timestamp[user_id] = now

            self.db.update_account_stats(
                user_id=user_id,
                world=self._world.get(user_id),
                eggs_hatched=self._eggs_hatched.get(user_id, 0),
                secret_count=secret_count,
                client_source=self._client_source.get(user_id, "telemetry"),
            )
            self.db.insert_snapshot(session_id, payload, tps, secret_count=secret_count)

            # Update in-memory state
            self._last_seen[user_id] = now
            self._last_payload[user_id] = payload
            self._connection_state[user_id] = "LIVE"

            if payload.placeId is not None:
                self._place_id[user_id] = payload.placeId
            if payload.jobId is not None:
                self._job_id[user_id] = payload.jobId.strip()
            if payload.tradeState is not None:
                self._trade_state[user_id] = payload.tradeState.strip().upper()
            if payload.tradeMessage is not None:
                self._trade_message[user_id] = payload.tradeMessage.strip()
            if payload.secretInstanceIds is not None:
                self._secret_instance_ids[user_id] = list(payload.secretInstanceIds)

            trade_status = self._reconcile_trade_queue_locked(now=now)
            trade_directive = self._build_trade_directive_locked(user_id, trade_status)

            needs_profile = (acc.get("username") == f"Player_{user_id}") or (not acc.get("avatar_url"))

            return {
                "status": "processed",
                "user_id": user_id,
                "session_id": session_id,
                "tps": tps,
                "secret_count": secret_count,
                "new_hatches": new_hatches,
                "pending_asset_ids": pending_asset_ids,
                "needs_profile_lookup": needs_profile,
                "trade_directive": trade_directive,
            }

    def check_timeouts(self, now: Optional[float] = None) -> List[Dict[str, Any]]:
        current_time = now if now is not None else time.time()
        events: List[Dict[str, Any]] = []

        with self._lock:
            accounts = self.db.get_accounts()
            for acc in accounts:
                user_id = acc["user_id"]
                username = acc.get("username") or f"Player_{user_id}"
                prev_state = self._connection_state.get(user_id, "IDLE")

                if not acc["is_tracking"]:
                    self._connection_state[user_id] = "PAUSED"
                    continue

                session_id = self._active_sessions.get(user_id)
                last = self._last_seen.get(user_id)

                if session_id and last:
                    elapsed = current_time - last
                    if elapsed >= self.disconnect_timeout_sec:
                        rates = self.rate_engine.get_rates(user_id)
                        last_p = self._last_payload.get(user_id)
                        final_taps = last_p.totalTaps if last_p else 0
                        final_rebirths = last_p.currentRebirths if last_p else 0

                        self.db.end_session(
                            session_id,
                            current_time,
                            final_taps,
                            final_rebirths,
                            rates["max_tps"],
                            rates["avg_tps"],
                        )
                        self._active_sessions[user_id] = None
                        self._had_secret_sync_in_session.pop(user_id, None)
                        self._connection_state[user_id] = "DISCONNECTED"
                        self.rate_engine.reset_account(user_id)
                        if prev_state != "DISCONNECTED":
                            events.append(
                                {
                                    "user_id": user_id,
                                    "username": username,
                                    "event": "DISCONNECTED",
                                    "prev_state": prev_state,
                                    "session_id": session_id,
                                }
                            )
                    elif elapsed >= self.stale_timeout_sec:
                        self._connection_state[user_id] = "STALE"
                        if prev_state != "STALE":
                            events.append(
                                {
                                    "user_id": user_id,
                                    "username": username,
                                    "event": "STALE",
                                    "prev_state": prev_state,
                                    "session_id": session_id,
                                }
                            )
                    else:
                        self._connection_state[user_id] = "LIVE"
                elif not session_id:
                    if user_id not in self._connection_state:
                        self._connection_state[user_id] = "IDLE"

        return events

    def has_recent_authoritative_secret_sync(
        self, user_id: int, within_sec: float = 60.0, now: Optional[float] = None
    ) -> bool:
        current_time = now if now is not None else time.time()
        with self._lock:
            ts = self._last_authoritative_secret_sync.get(user_id)
            if ts is None:
                return False
            return abs(current_time - ts) <= within_sec

    def _get_adjusted_boosts(self, user_id: int, current_time: float) -> List[Dict[str, Any]]:
        boosts = self._active_boosts.get(user_id, [])
        ts = self._boosts_timestamp.get(user_id, current_time)
        elapsed = max(0.0, current_time - ts)
        adjusted = []
        for b in boosts:
            rem = max(0.0, round(float(b.get("remainingSec", 0.0)) - elapsed, 1))
            if rem > 0.0 or float(b.get("remainingSec", 0.0)) == 0.0:
                adjusted.append(
                    {
                        "name": b.get("name", "Boost"),
                        "multiplier": b.get("multiplier"),
                        "remainingSec": rem,
                    }
                )
        return adjusted

    def _enrich_secret_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        slug = slugify_pet_name(row["name"])
        cat_item = self.db.get_pet_catalog_item(slug)
        img_url = self.pet_catalog.resolve_image_url(
            row["name"], explicit_url=row.get("image_url"), asset_id=row.get("image_asset_id")
        )
        return {
            "user_id": row["user_id"],
            "username": row.get("username") or f"Player_{row['user_id']}",
            "pet_key": row["pet_key"],
            "slug": slug,
            "name": row["name"],
            "variant": normalize_variant(row.get("variant")),
            "tier": row.get("tier") or (cat_item.get("tier") if cat_item else "Secret"),
            "count": int(row.get("count", 1)),
            "multiplier": float(row.get("multiplier", 1.0)),
            "power": float(row.get("power", 0.0)),
            "is_equipped": bool(row.get("is_equipped", 0)),
            "egg_source": row.get("egg_source") or (cat_item.get("default_egg") if cat_item else None),
            "odds": cat_item.get("odds") if cat_item else None,
            "image_asset_id": row.get("image_asset_id") or (cat_item.get("image_asset_id") if cat_item else None),
            "image_url": img_url,
            "updated_at": row.get("updated_at"),
        }

    def get_live_state(self, user_id: int, now: Optional[float] = None) -> Dict[str, Any]:
        current_time = now if now is not None else time.time()
        with self._lock:
            acc = self.db.get_account(user_id) or {
                "user_id": user_id,
                "username": f"Player_{user_id}",
                "display_name": f"Player_{user_id}",
                "avatar_url": "",
                "is_tracking": 1,
                "world": None,
                "eggs_hatched": 0,
                "secret_count": 0,
                "last_client_source": "telemetry",
            }

            status = self._connection_state.get(user_id, "IDLE" if acc.get("is_tracking", 1) else "PAUSED")
            last_p = self._last_payload.get(user_id)
            rates = self.rate_engine.get_rates(user_id)
            session_id = self._active_sessions.get(user_id)
            start_t = self._session_start_times.get(user_id, current_time)
            duration = max(0.0, current_time - start_t) if session_id else 0.0

            equipped = []
            if last_p:
                for p in last_p.equippedPets:
                    pd = p.model_dump()
                    pd["image_url"] = self.pet_catalog.resolve_image_url(
                        p.name, explicit_url=p.imageUrl, asset_id=p.imageAssetId
                    )
                    equipped.append(pd)

            raw_secrets = self.db.get_account_secrets(user_id)
            secret_pets = [self._enrich_secret_row(r) for r in raw_secrets]
            secret_count = int(acc.get("secret_count") or sum(s["count"] for s in secret_pets))
            eggs_hatched = int(self._eggs_hatched.get(user_id, acc.get("eggs_hatched") or 0))
            world = self._world.get(user_id) or acc.get("world")
            client_source = self._client_source.get(user_id) or acc.get("last_client_source") or "telemetry"

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
                "last_seen": self._last_seen.get(user_id, 0.0),
                # v2 fields
                "secret_count": secret_count,
                "secret_pets": secret_pets,
                "eggs_hatched": eggs_hatched,
                "eggs_per_hour": rates.get("eggs_per_hour", 0.0),
                "world": world,
                "active_boosts": self._get_adjusted_boosts(user_id, current_time),
                "client_source": client_source,
                "place_id": self._place_id.get(user_id),
                "job_id": self._job_id.get(user_id),
                "trade_state": self._trade_state.get(user_id, "IDLE"),
                "trade_message": self._trade_message.get(user_id),
            }

    def get_overview(self, now: Optional[float] = None) -> Dict[str, Any]:
        current_time = now if now is not None else time.time()
        accounts = self.db.get_accounts()

        counts = {"LIVE": 0, "STALE": 0, "DISCONNECTED": 0, "PAUSED": 0, "IDLE": 0}
        total_tps = 0.0
        total_current_taps = 0
        total_taps = 0
        total_currency = 0
        total_rebirths = 0
        total_eggs = 0
        total_eggs_per_hour = 0.0
        total_secrets_accounts = 0

        for acc in accounts:
            live = self.get_live_state(acc["user_id"], now=current_time)
            st = live["connection_status"]
            counts[st] = counts.get(st, 0) + 1
            total_tps += float(live["tps"])
            total_current_taps += int(live["current_taps"])
            total_taps += int(live["total_taps"])
            total_currency += int(live["current_currency"])
            total_rebirths += int(live["current_rebirths"])
            total_eggs += int(live["eggs_hatched"])
            total_eggs_per_hour += float(live["eggs_per_hour"])
            total_secrets_accounts += int(live["secret_count"])

        secret_rows = self.db.get_account_secrets()
        unique_species = {slugify_pet_name(r["name"]) for r in secret_rows}
        by_variant: Dict[str, int] = {}
        vault_total = 0
        for r in secret_rows:
            v = normalize_variant(r.get("variant"))
            c = int(r.get("count", 1))
            by_variant[v] = by_variant.get(v, 0) + c
            vault_total += c

        return {
            "total_accounts": len(accounts),
            "live_accounts": counts["LIVE"],
            "stale_accounts": counts["STALE"],
            "disconnected_accounts": counts["DISCONNECTED"],
            "paused_accounts": counts["PAUSED"],
            "idle_accounts": counts["IDLE"],
            "total_secrets": max(vault_total, total_secrets_accounts),
            "unique_secret_species": len(unique_species),
            "by_variant": by_variant,
            "total_tps": round(total_tps, 2),
            "total_current_taps": total_current_taps,
            "total_taps": total_taps,
            "total_currency": total_currency,
            "total_rebirths": total_rebirths,
            "total_eggs_hatched": total_eggs,
            "eggs_per_hour": round(total_eggs_per_hour, 1),
        }

    def get_secrets_summary(
        self,
        user_id: Optional[int] = None,
        variant: Optional[str] = None,
        tier: Optional[str] = None,
        query: Optional[str] = None,
    ) -> Dict[str, Any]:
        raw_rows = self.db.get_account_secrets(user_id=user_id)
        enriched = [self._enrich_secret_row(r) for r in raw_rows]

        norm_variant_filter = normalize_variant(variant) if variant and variant.lower() != "all" else None
        tier_filter = tier.strip().lower() if tier and tier.strip().lower() != "all" else None
        q_filter = query.strip().lower() if query and query.strip() else None

        filtered: List[Dict[str, Any]] = []
        for item in enriched:
            if norm_variant_filter and item["variant"].lower() != norm_variant_filter.lower():
                continue
            if tier_filter and (item.get("tier") or "").lower() != tier_filter:
                continue
            if q_filter:
                hay = f"{item['name']} {item['variant']} {item.get('tier') or ''} {item.get('egg_source') or ''} {item['username']}".lower()
                if q_filter not in hay:
                    continue
            filtered.append(item)

        grouped_map: Dict[str, Dict[str, Any]] = {}
        by_variant: Dict[str, int] = {}
        by_tier: Dict[str, int] = {}
        total_secrets = 0

        for item in filtered:
            pk = item["pet_key"]
            cnt = int(item["count"])
            total_secrets += cnt
            v = item["variant"]
            t = item.get("tier") or "Secret"
            by_variant[v] = by_variant.get(v, 0) + cnt
            by_tier[t] = by_tier.get(t, 0) + cnt

            if pk not in grouped_map:
                grouped_map[pk] = {
                    "pet_key": pk,
                    "slug": item["slug"],
                    "name": item["name"],
                    "variant": v,
                    "tier": t,
                    "total_count": cnt,
                    "max_multiplier": item["multiplier"],
                    "max_power": item["power"],
                    "egg_source": item.get("egg_source"),
                    "odds": item.get("odds"),
                    "image_asset_id": item.get("image_asset_id"),
                    "image_url": item["image_url"],
                    "owners": [
                        {
                            "user_id": item["user_id"],
                            "username": item["username"],
                            "count": cnt,
                            "is_equipped": item["is_equipped"],
                        }
                    ],
                }
            else:
                g = grouped_map[pk]
                g["total_count"] += cnt
                g["max_multiplier"] = max(g["max_multiplier"], item["multiplier"])
                g["max_power"] = max(g["max_power"], item["power"])
                g["owners"].append(
                    {
                        "user_id": item["user_id"],
                        "username": item["username"],
                        "count": cnt,
                        "is_equipped": item["is_equipped"],
                    }
                )

        grouped_list = sorted(
            grouped_map.values(),
            key=lambda x: (-x["total_count"], -x["max_power"], x["name"]),
        )
        return {
            "total_secrets": total_secrets,
            "unique_types": len(grouped_list),
            "by_variant": by_variant,
            "by_tier": by_tier,
            "grouped": grouped_list,
            "items": filtered,
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
                        session_id,
                        now,
                        final_taps,
                        final_rebirths,
                        rates["max_tps"],
                        rates["avg_tps"],
                    )
                    self._active_sessions[user_id] = None
                    self._had_secret_sync_in_session.pop(user_id, None)
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
            self._last_authoritative_secret_sync.pop(user_id, None)
            self._had_secret_sync_in_session.pop(user_id, None)
            self._active_boosts.pop(user_id, None)
            self._boosts_timestamp.pop(user_id, None)
            self._world.pop(user_id, None)
            self._eggs_hatched.pop(user_id, None)
            self._client_source.pop(user_id, None)
            self._place_id.pop(user_id, None)
            self._job_id.pop(user_id, None)
            self._trade_state.pop(user_id, None)
            self._trade_message.pop(user_id, None)
            self._secret_instance_ids.pop(user_id, None)
            if user_id in self._priority_trade_queue:
                self._priority_trade_queue.remove(user_id)
            if self._active_trade_clone == user_id:
                self._active_trade_clone = None
            self.rate_engine.reset_account(user_id)

    def reset_after_restore(self) -> None:
        """Clears stale in-memory session state after a database restore to avoid orphaned FK references."""
        with self._lock:
            self._active_sessions.clear()
            self._last_seen.clear()
            self._last_payload.clear()
            self._session_start_times.clear()
            self._connection_state.clear()
            self._last_authoritative_secret_sync.clear()
            self._had_secret_sync_in_session.clear()
            self._active_boosts.clear()
            self._boosts_timestamp.clear()
            self._world.clear()
            self._eggs_hatched.clear()
            self._client_source.clear()
            self._place_id.clear()
            self._job_id.clear()
            self._trade_state.clear()
            self._trade_message.clear()
            self._secret_instance_ids.clear()
            self._priority_trade_queue.clear()
            self._active_trade_clone = None
            self._active_trade_leased_at = 0.0
            self._trade_cooldown_until.clear()
            self._recent_trade_completions.clear()
            self.rate_engine.reset_all()
            self.db.close_dangling_sessions()
