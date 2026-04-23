from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import uuid

from app.utils.database import get_db
from app.utils.security import create_user_jwt
from app.utils.rate_limiter import register_limiter
from app.models import User
from app.services.qr_service import generate_qr_base64

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

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
    if not register_limiter.is_allowed(client_ip):
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Too many requests. Please wait a moment."
        })

    name = name.strip()
    email = email.strip().lower()

    if not name or not email or "@" not in email:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Please provide a valid name and email."
        })

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "This email is already registered."
        })

    user_id = str(uuid.uuid4())
    token = create_user_jwt(user_id)
    qr_b64 = generate_qr_base64(token)

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

    return templates.TemplateResponse("success.html", {
        "request": request,
        "user": user,
        "qr_b64": qr_b64,
    })
