"""
main.py — EventPass application entry point.

Startup order:
  1. load_dotenv() so env vars are available before any module import
  2. Import security/database (they validate SECRET_KEY, ADMIN_PASSWORD,
     DATABASE_URL at import time and raise RuntimeError if missing)
  3. Build FastAPI app, mount static files, register routers
  4. lifespan: init DB tables, WAL check, seed projects
"""
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()   # must be first — before any app imports

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse

# ── These imports validate required env vars and will raise RuntimeError
# ── if SECRET_KEY, ADMIN_PASSWORD, or DATABASE_URL are missing.
from app.utils.database import init_db, engine      # noqa: E402
from app.utils.security import SECRET_KEY           # noqa: E402  (validates on import)

from app.routes.registration import router as registration_router
from app.routes.scanner      import router as scanner_router
from app.routes.admin        import router as admin_router
from app.routes.voting       import router as voting_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("eventpass")


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting EventPass…")
    init_db()
    _seed_projects()
    log.info("EventPass ready.")
    yield
    log.info("EventPass shutting down.")


def _seed_projects():
    """Insert sample projects if the table is empty (first run only)."""
    import uuid
    from app.utils.database import get_db_ctx
    from app.models import Project

    with get_db_ctx() as db:
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
            log.info("Seeded %d sample projects.", len(samples))


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="EventPass",
    description="Production-grade event management & QR check-in system",
    version="2.0.0",
    lifespan=lifespan,
    docs_url=None,    # disable public Swagger UI in production
    redoc_url=None,
)

# ── Static files ──────────────────────────────────────────────────────────────
_static_dir = os.path.join(os.path.dirname(__file__), "app", "static")
os.makedirs(_static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(registration_router)
app.include_router(scanner_router)
app.include_router(admin_router)
app.include_router(voting_router)

# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}

# ── 404 ───────────────────────────────────────────────────────────────────────
_templates = Jinja2Templates(directory="app/templates")

@app.exception_handler(404)
async def not_found(request: Request, exc):
    return _templates.TemplateResponse("404.html", {"request": request}, status_code=404)

@app.exception_handler(500)
async def server_error(request: Request, exc):
    log.exception("Unhandled 500 on %s", request.url)
    return JSONResponse({"detail": "Internal server error."}, status_code=500)
