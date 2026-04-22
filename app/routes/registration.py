import logging
import uuid as _uuid
import traceback

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.utils.database import get_db
from app.utils.security import create_user_jwt
from app.utils.rate_limiter import register_limiter
from app.models import User
from app.services.email_service import send_qr_email_async, email_configured

log = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ── Basic email validation ─────────────────────────────────────────────
def _valid_email(email: str) -> bool:
    parts = email.split("@")
    return (
        len(parts) == 2
        and len(parts[0]) > 0
        and "." in parts[1]
        and len(parts[1]) > 2
    )


# ── Register page ──────────────────────────────────────────────────────
@router.get("/", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


# ── Register user ──────────────────────────────────────────────────────
@router.post("/register", response_class=HTMLResponse)
async def register_user(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    client_ip = request.client.host

    # ── Rate limit ──────────────────────────────────────────────────────
    if not register_limiter.is_allowed(client_ip):
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Too many registration attempts. Please wait and try again.",
        })

    # ── Clean input ─────────────────────────────────────────────────────
    name = name.strip()
    email = email.strip().lower()

    if len(name) < 2:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Please enter a valid name.",
        })

    if not _valid_email(email):
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Invalid email address.",
        })

    # ── Duplicate check ─────────────────────────────────────────────────
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Email already registered.",
        })

    # ── Email config check ──────────────────────────────────────────────
    if not email_configured():
        log.error("Email not configured properly (EMAIL_USER/EMAIL_PASS missing).")
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Email system is not configured.",
        })

    # ── Create user ─────────────────────────────────────────────────────
    user_id = str(_uuid.uuid4())
    token = create_user_jwt(user_id)

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

    # ── Send email (FIXED VERSION) ──────────────────────────────────────
    try:
        send_qr_email_async(
            to_name=name,
            to_email=email,
            user_uuid=user_id,
            jwt_token=token,
        )
    except Exception as exc:
        log.error("Failed to send QR email to %s: %s", email, exc)
        log.error(traceback.format_exc())

        db.delete(user)
        db.commit()

        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": (
                "Email delivery failed. Please try again later "
                "or contact the organizer."
            ),
        })

    # ── Success ─────────────────────────────────────────────────────────
    log.info("Registered user: %s <%s>", name, email)

    return templates.TemplateResponse("success.html", {
        "request": request,
        "name": name,
        "email": email,
    })
