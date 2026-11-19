import hashlib
import hmac
import re
from typing import Optional
from fastapi import HTTPException, Request

from src.config import settings

ADMIN_COOKIE_NAME = "ts_admin_session"
_SAFE_HOST_RE = re.compile(r"^[a-zA-Z0-9.\-:]+$")


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest((a or "").encode("utf-8"), (b or "").encode("utf-8"))


def resolve_public_base_url(request: Request) -> str:
    """Resolve external public base URL respecting PUBLIC_BASE_URL and reverse proxy headers."""
    configured = (settings.public_base_url or "").strip().rstrip("/")
    if configured and configured.lower().startswith(("http://", "https://")):
        if not any(ch in configured for ch in ("\r", "\n", '"', "'", "\\", " ")):
            return configured

    proto_hdr = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    scheme = proto_hdr if proto_hdr in ("http", "https") else request.url.scheme

    host_hdr = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or request.url.netloc
        or "127.0.0.1:3883"
    )
    host = host_hdr.split(",")[0].strip()
    if not _SAFE_HOST_RE.match(host):
        fallback_host = (request.url.netloc or "").strip()
        host = fallback_host if _SAFE_HOST_RE.match(fallback_host) else "127.0.0.1:3883"

    return f"{scheme}://{host}".rstrip("/")


def create_admin_session_token(password: str) -> str:
    key = (password or "").encode("utf-8")
    return hmac.new(key, b"trackstats-v2-admin-session", hashlib.sha256).hexdigest()


def verify_admin_session_token(token: Optional[str], password: str) -> bool:
    if not password:
        return True
    if not token:
        return False
    expected = create_admin_session_token(password)
    return constant_time_equals(token.strip(), expected)


def is_admin_request(request: Request) -> bool:
    admin_pw = (settings.admin_password or "").strip()
    if not admin_pw:
        return True

    cookie_token = request.cookies.get(ADMIN_COOKIE_NAME)
    if verify_admin_session_token(cookie_token, admin_pw):
        return True

    header_pw = (request.headers.get("x-admin-password") or "").strip()
    if header_pw and constant_time_equals(header_pw, admin_pw):
        return True

    return False


def require_admin(request: Request) -> None:
    if not is_admin_request(request):
        raise HTTPException(status_code=401, detail="Admin authentication required")


def require_read_access(request: Request) -> None:
    admin_pw = (settings.admin_password or "").strip()
    if not admin_pw or settings.public_read:
        return
    if not is_admin_request(request):
        raise HTTPException(status_code=401, detail="Authentication required to view dashboard")


def require_ingest_key(request: Request) -> None:
    expected = (settings.ingest_key or "").strip()
    if not expected:
        return

    # Also allow an authenticated admin session when admin_password is configured
    if (settings.admin_password or "").strip() and is_admin_request(request):
        return

    provided = (request.headers.get("x-trackstats-key") or "").strip()
    if not provided:
        auth_hdr = (request.headers.get("authorization") or "").strip()
        if auth_hdr.lower().startswith("bearer "):
            provided = auth_hdr[7:].strip()
    if not provided:
        provided = (request.query_params.get("key") or "").strip()

    if not provided or not constant_time_equals(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing X-TrackStats-Key")
