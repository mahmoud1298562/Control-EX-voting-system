import logging
import uuid as _uuid
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.utils.database import get_db, atomic_vote
from app.utils.rate_limiter import vote_limiter
from app.utils.security import verify_admin_session_token
from app.models import User, Vote, Project

log = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _is_admin(request: Request) -> bool:
    token = request.cookies.get("admin_token")
    return bool(token and verify_admin_session_token(token))


# ── Projects page (attended-only gate) ───────────────────────────────────────
@router.get("/projects", response_class=HTMLResponse)
async def projects_page(
    request: Request,
    uuid: str = None,
    email: str = None,
    db: Session = Depends(get_db),
):
    if not uuid or not email:
        return templates.TemplateResponse("projects_gate.html", {
            "request": request, "error": None,
        })

    user = db.query(User).filter(
        User.id == uuid,
        User.email == email.strip().lower(),
    ).first()

    if not user:
        return templates.TemplateResponse("projects_gate.html", {
            "request": request,
            "error": "User not found. Check your UUID and email.",
        })
    if not user.attended:
        return templates.TemplateResponse("projects_gate.html", {
            "request": request,
            "error": "Access denied. You must be checked in to view projects.",
        })

    projects = db.query(Project).all()
    return templates.TemplateResponse("projects.html", {
        "request": request,
        "user": user,
        "projects": projects,
    })


@router.post("/projects/gate", response_class=HTMLResponse)
async def projects_gate(
    request: Request,
    user_uuid: str = Form(...),
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    return RedirectResponse(
        f"/projects?uuid={user_uuid}&email={email.strip().lower()}",
        status_code=302,
    )


# ── Vote endpoint (atomic, race-condition safe) ───────────────────────────────
@router.post("/vote")
async def cast_vote(
    request: Request,
    user_uuid: str = Form(...),
    email: str = Form(...),
    project_name: str = Form(...),
    db: Session = Depends(get_db),
):
    client_ip = request.client.host
    if not vote_limiter.is_allowed(client_ip):
        return JSONResponse(
            {"status": "error", "message": "Too many requests. Please wait."},
            status_code=429,
        )

    # Verify email + uuid match (prevents API bypass with only uuid)
    user = db.query(User).filter(
        User.id == user_uuid,
        User.email == email.strip().lower(),
    ).first()
    if not user:
        return JSONResponse({"status": "error", "message": "User not found."})

    if not project_name.strip():
        return JSONResponse({"status": "error", "message": "No project selected."})

    result = atomic_vote(db, user_uuid, project_name.strip())
    if result["status"] == "success":
        log.info("Vote cast by user %s for '%s'", user_uuid, project_name)
    return JSONResponse(result)


# ── Vote results (admin only) ─────────────────────────────────────────────────
@router.get("/admin/votes", response_class=HTMLResponse)
async def vote_results(
    request: Request,
    db: Session = Depends(get_db),
):
    if not _is_admin(request):
        return RedirectResponse("/admin/login", status_code=302)

    votes = db.query(Vote).all()
    tally: dict[str, int] = {}
    for v in votes:
        tally[v.project_name] = tally.get(v.project_name, 0) + 1

    sorted_tally = sorted(tally.items(), key=lambda x: x[1], reverse=True)

    return templates.TemplateResponse("vote_results.html", {
        "request": request,
        "tally": sorted_tally,
        "total_votes": len(votes),
    })

