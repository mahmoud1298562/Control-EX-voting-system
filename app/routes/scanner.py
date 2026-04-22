import logging
from fastapi import APIRouter, Depends, Request, Cookie
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.utils.database import get_db, atomic_checkin
from app.utils.security import decode_user_jwt, verify_admin_session_token
from app.utils.rate_limiter import scan_limiter

log = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _is_admin(request: Request) -> bool:
    token = request.cookies.get("admin_token")
    return bool(token and verify_admin_session_token(token))


class ScanPayload(BaseModel):
    token: str


# ── Scanner UI (admin-only, full-screen) ──────────────────────────────────────
@router.get("/scanner", response_class=HTMLResponse)
async def scanner_page(request: Request):
    if not _is_admin(request):
        return RedirectResponse("/admin/login?next=/scanner", status_code=302)
    return templates.TemplateResponse("scanner.html", {"request": request})


# ── Scan endpoint (admin-only) ────────────────────────────────────────────────
@router.post("/scan")
async def scan_qr(
    payload: ScanPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    # ── Auth ─────────────────────────────────────────────────────────────────
    if not _is_admin(request):
        return JSONResponse(
            {"status": "unauthorized", "message": "Admin login required."},
            status_code=401,
        )

    # ── Rate limit (per scanner IP, generous for burst scanning) ────────────
    client_ip = request.client.host
    if not scan_limiter.is_allowed(client_ip):
        return JSONResponse(
            {"status": "rate_limited", "message": "Slow down — too many scans."},
            status_code=429,
        )

    # ── Decode JWT ────────────────────────────────────────────────────────────
    token = payload.token.strip()
    user_id = decode_user_jwt(token)

    if not user_id:
        log.warning("Invalid QR scan from %s — bad JWT", client_ip)
        return JSONResponse({"status": "invalid", "message": "Invalid QR code."})

    # ── Atomic check-in (race-condition safe) ─────────────────────────────────
    result = atomic_checkin(db, user_id)
    status = result["status"]

    if status == "not_found":
        return JSONResponse({"status": "invalid", "message": "User not found."})

    if status == "already_scanned":
        ts = result["attended_at"]
        time_str = ts.strftime("%H:%M:%S") if ts else "earlier"
        return JSONResponse({
            "status": "already_scanned",
            "name": result["name"],
            "message": f"Already checked in at {time_str}",
        })

    # success
    log.info("Check-in: %s (id=%s) from scanner %s", result["name"], user_id, client_ip)
    return JSONResponse({
        "status": "success",
        "name": result["name"],
        "message": f"Welcome, {result['name']}!",
    })

