import pytest
from fastapi.testclient import TestClient
from src.config import settings
from src.main import app, db, session_manager


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_healthz_always_public(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "secret-admin", raising=False)
    monkeypatch.setattr(settings, "public_read", False, raising=False)
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_ingest_key_blocks_unauthenticated_telemetry_and_allows_valid_key(client, monkeypatch):
    monkeypatch.setattr(settings, "ingest_key", "ts_live_key_123", raising=False)
    uid = 81001
    db.delete_account(uid)
    session_manager.remove_account(uid)
    payload = {"userId": uid, "currentTaps": 500, "totalTaps": 500}

    res_no_key = client.post("/api/v1/telemetry", json=payload)
    assert res_no_key.status_code == 401

    res_bad_key = client.post("/api/v1/telemetry", json=payload, headers={"X-TrackStats-Key": "wrong"})
    assert res_bad_key.status_code == 401

    res_ok = client.post("/api/v1/telemetry", json=payload, headers={"X-TrackStats-Key": "ts_live_key_123"})
    assert res_ok.status_code == 200
    assert res_ok.json()["user_id"] == uid

    # Inspector & Discord inbound webhook also require ingest key (header or ?key= query param)
    insp_payload = {"userId": uid, "username": "Tester", "placeId": 72858262610964, "structure": {}}
    assert client.post("/api/v1/connector/inspect", json=insp_payload).status_code == 401
    assert (
        client.post(
            "/api/v1/connector/inspect",
            json=insp_payload,
            headers={"X-TrackStats-Key": "ts_live_key_123"},
        ).status_code
        == 200
    )

    wh_payload = {"content": "Tester hatched a Secret Dark Cat!"}
    assert client.post("/api/v1/webhook/discord", json=wh_payload).status_code == 401
    assert client.post("/api/v1/webhook/discord?key=ts_live_key_123", json=wh_payload).status_code == 200


def test_admin_login_cookie_unlocks_mutations_and_connector_key(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "my_admin_pw", raising=False)
    monkeypatch.setattr(settings, "ingest_key", "ts_secret_999", raising=False)
    monkeypatch.setattr(settings, "public_read", True, raising=False)

    # Guest can read overview, but connector config masks ingest_key
    assert client.get("/api/v1/overview").status_code == 200
    status_guest = client.get("/api/v1/auth/status").json()
    assert status_guest["auth_enabled"] is True
    assert status_guest["public_read"] is True
    assert status_guest["is_admin"] is False
    assert status_guest["ingest_key_required"] is True

    cfg_guest = client.get("/api/v1/connector/config").json()
    assert cfg_guest["is_admin"] is False
    assert cfg_guest["ingest_key"] is None

    # Guest cannot mutate alerts, restore, export, or modify catalog images
    assert client.post("/api/v1/settings/alerts", json={"enabled": True}).status_code == 401
    assert client.get("/api/v1/export/json").status_code == 401
    assert client.post("/api/v1/pets/catalog/dark-cat/image", json={"imageUrl": ""}).status_code == 401

    # Wrong password rejected
    assert client.post("/api/v1/auth/login", json={"password": "wrong"}).status_code == 401

    # Valid login sets cookie and reveals ingest_key
    login_res = client.post("/api/v1/auth/login", json={"password": "my_admin_pw"})
    assert login_res.status_code == 200
    assert login_res.json()["is_admin"] is True

    cfg_admin = client.get("/api/v1/connector/config").json()
    assert cfg_admin["is_admin"] is True
    assert cfg_admin["ingest_key"] == "ts_secret_999"
    assert client.post("/api/v1/settings/alerts", json={"enabled": True}).status_code == 200
    assert client.get("/api/v1/export/json").status_code == 200

    # Logout clears admin session
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/connector/config").json()["ingest_key"] is None
    assert client.post("/api/v1/settings/alerts", json={"enabled": False}).status_code == 401


def test_private_read_mode_blocks_guest_reads(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "lock_all_pw", raising=False)
    monkeypatch.setattr(settings, "public_read", False, raising=False)

    assert client.get("/api/v1/overview").status_code == 401
    assert client.get("/api/v1/secrets").status_code == 401
    assert client.get("/api/v1/accounts").status_code == 401

    client.post("/api/v1/auth/login", json={"password": "lock_all_pw"})
    assert client.get("/api/v1/overview").status_code == 200
    assert client.get("/api/v1/secrets").status_code == 200
