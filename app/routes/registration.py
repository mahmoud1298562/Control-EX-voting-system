import logging
import uuid as _uuid
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import traceback

from app.utils.database import get_db
from app.utils.security import create_user_jwt
from app.utils.rate_limiter import register_limiter
from app.models import User
from app.services.email_service import send_qr_email_async, email_configured

log = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# Basic email format check (avoids importing heavy validators)
def _valid_email(email: str) -> bool:
    parts = email.split("@")
    return (
        len(parts) == 2
        and len(parts[0]) > 0
        and "." in parts[1]
        and len(parts[1]) > 2
    )


@router.get("/", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@router.post("/register", response_class=HTMLResponse)
async def register_user(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    client_ip = request.client.host

    # ── Rate limit ────────────────────────────────────────────────────────────
    if not register_limiter.is_allowed(client_ip):
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Too many registration attempts. Please wait a minute and try again.",
        })

    # ── Input validation ──────────────────────────────────────────────────────
    name  = name.strip()
    email = email.strip().lower()

    if len(name) < 2:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Please enter your full name (at least 2 characters).",
        })
    if not _valid_email(email):
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Please enter a valid email address.",
        })

    # ── Duplicate email check ─────────────────────────────────────────────────
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "This email is already registered. Check your inbox for your QR code.",
        })

    # ── Email delivery pre-check ──────────────────────────────────────────────
    if not email_configured():
        log.error("Registration attempted but EMAIL_USER/EMAIL_PASS are not configured.")
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": (
                "Email delivery is not configured on this server. "
                "Contact the event organiser."
            ),
        })

    # ── Create user ───────────────────────────────────────────────────────────
    user_id = str(_uuid.uuid4())
    token   = create_user_jwt(user_id)

    user = User(
        id=user_id,
        name=name,
        email=email,
        jwt_token=token,
        attended=False,
        voted=False,
    )
    db.add(user)
    db.commit()

    # ── Send QR by email (background thread, non-blocking) ───────────────────
    future = send_qr_email_async(
        to_name=name,
        to_email=email,
        user_uuid=user_id,
        jwt_token=token,
    )

    # Wait up to 10 s for the email to go out.
    # If it fails, roll back the registration so the user can retry.
    try:
        future.result(timeout=10)
    except Exception as exc:
        log.error("Failed to send QR email to %s: %s", email, exc)
        log.error(traceback.format_exc())
        # Roll back — user record is removed so they can re-register
        db.delete(user)
        db.commit()
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": (
                "Email delivery failed. "
                "Please check your email address and try again. "
                "If the problem persists, contact the event organiser."
            ),
        })

    # ── Success — NO QR on screen ─────────────────────────────────────────────
    log.info("Registered and emailed: %s <%s> uuid=%s", name, email, user_id)
    return templates.TemplateResponse("success.html", {
        "request": request,
        "name": name,
        "email": email,
    })

