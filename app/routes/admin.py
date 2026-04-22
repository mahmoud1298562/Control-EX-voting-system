import csv
import io
import logging
from fastapi import APIRouter, Depends, Request, Form, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.utils.database import get_db
from app.utils.security import (
    create_admin_session_token,
    verify_admin_session_token,
    verify_admin_password,
)
from app.models import User

log = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _is_admin(request: Request) -> bool:
    token = request.cookies.get("admin_token")
    return bool(token and verify_admin_session_token(token))


def _require_admin(request: Request):
    if not _is_admin(request):
        return RedirectResponse("/admin/login", status_code=302)
    return None


@router.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    if _is_admin(request):
        return RedirectResponse("/admin/dashboard", status_code=302)
    return templates.TemplateResponse("admin_login.html", {"request": request})


@router.post("/admin/login")
async def admin_login(request: Request, password: str = Form(...)):
    if verify_admin_password(password):
        token = create_admin_session_token()
        next_url = request.query_params.get("next", "/admin/dashboard")
        if not next_url.startswith("/"):
            next_url = "/admin/dashboard"
        response = RedirectResponse(next_url, status_code=302)
        response.set_cookie(
            "admin_token", token,
            httponly=True,
            samesite="lax",
            max_age=28800,
        )
        log.info("Admin login from %s", request.client.host)
        return response

    log.warning("Failed admin login attempt from %s", request.client.host)
    return templates.TemplateResponse("admin_login.html", {
        "request": request,
        "error": "Invalid password.",
    })


@router.get("/admin/logout")
async def admin_logout():
    response = RedirectResponse("/admin/login", status_code=302)
    response.delete_cookie("admin_token")
    return response


@router.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    db: Session = Depends(get_db),
):
    if redir := _require_admin(request):
        return redir

    users    = db.query(User).order_by(User.created_at.desc()).all()
    total    = len(users)
    attended = sum(1 for u in users if u.attended)
    voted    = sum(1 for u in users if u.voted)

    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "users":    users,
        "total":    total,
        "attended": attended,
        "voted":    voted,
    })


@router.get("/admin/export")
async def export_csv(
    request: Request,
    db: Session = Depends(get_db),
):
    if redir := _require_admin(request):
        return redir

    users  = db.query(User).order_by(User.created_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name", "Email", "UUID", "Attended", "Attended At", "Voted", "Registered At"])
    for u in users:
        writer.writerow([
            u.name,
            u.email,
            u.id,
            "Yes" if u.attended else "No",
            u.attended_at.strftime("%Y-%m-%d %H:%M:%S") if u.attended_at else "",
            "Yes" if u.voted else "No",
            u.created_at.strftime("%Y-%m-%d %H:%M:%S") if u.created_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=attendees.csv"},
    )
