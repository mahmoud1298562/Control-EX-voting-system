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


# ── Email validation ───────────────────────────────────────────────────────
def _valid_email(email: str) -> bool:
    parts = email.split("@")
    return (
        len(parts) == 2
        and len(parts[0]) > 0
        and "." in parts[1]
        and len(parts[1]) > 2
    )


# ── Routes ────────────────────────────────────────────────────────────────
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

    # ── Rate limit ─────────────────────────────────────────────────────────
    if not register_limiter.is_allowed(client_ip):
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Too many registration attempts. Please wait a minute and try again.",
        })

    # ── Clean input ────────────────────────────────────────────────────────
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

    # ── Check duplicate ────────────────────────────────────────────────────
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "This email is already registered. Check your inbox for your QR code.",
        })

    # ── Check email config ─────────────────────────────────────────────────
    if not email_configured():
        log.error("EMAIL_USER / EMAIL_PASS not configured.")
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Email service is not configured. Contact the organiser.",
        })

    # ── Create user ────────────────────────────────────────────────────────
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

    # ── Send email (background) ────────────────────────────────────────────
    future = send_qr_email_async(
        to_name=name,
        to_email=email,
        user_uuid=user_id,
        jwt_token=token,
    )

    # ── Handle errors in background (logging only) ─────────────────────────
    def _email_callback(f):
        try:
            f.result()
        except Exception as e:
            log.error("Email failed for %s: %s", email, e)
            log.error(traceback.format_exc())

    future.add_done_callback(_email_callback)

    # ── Success ────────────────────────────────────────────────────────────
    log.info("Registered: %s <%s> uuid=%s", name, email, user_id)

    return templates.TemplateResponse("success.html", {
        "request": request,
        "name": name,
        "email": email,
    })
