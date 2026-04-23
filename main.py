import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv

load_dotenv()

from app.utils.database import init_db
from app.routes.registration import router as registration_router
from app.routes.scanner import router as scanner_router
from app.routes.admin import router as admin_router
from app.routes.voting import router as voting_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialise DB tables and seed demo projects
    init_db()
    _seed_projects()
    yield
    # Shutdown: nothing to clean up


def _seed_projects():
    """Add sample projects if the table is empty."""
    from app.utils.database import SessionLocal
    from app.models import Project
    import uuid

    db = SessionLocal()
    try:
        if db.query(Project).count() == 0:
            samples = [
                Project(id=str(uuid.uuid4()), name="Smart City Dashboard",
                        description="Real-time IoT data visualisation for urban infrastructure.",
                        team="Team Alpha"),
                Project(id=str(uuid.uuid4()), name="AI Study Companion",
                        description="Personalised learning assistant powered by LLMs.",
                        team="Team Beta"),
                Project(id=str(uuid.uuid4()), name="GreenTrack",
                        description="Carbon footprint tracker with gamified reduction goals.",
                        team="Team Gamma"),
            ]
            db.add_all(samples)
            db.commit()
    finally:
        db.close()


app = FastAPI(
    title="EventPass",
    description="Lightweight event management & QR check-in system",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
)

# ── Static files ──────────────────────────────────────────────────────────────
static_dir = os.path.join(os.path.dirname(__file__), "app", "static")
os.makedirs(static_dir, exist_ok=True)
os.makedirs(os.path.join(static_dir, "qrcodes"), exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(registration_router)
app.include_router(scanner_router)
app.include_router(admin_router)
app.include_router(voting_router)

# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "service": "EventPass"}


# ── 404 handler ───────────────────────────────────────────────────────────────
templates = Jinja2Templates(directory="app/templates")

@app.exception_handler(404)
async def not_found(request: Request, exc):
    return templates.TemplateResponse(
        "404.html", {"request": request}, status_code=404
    )
