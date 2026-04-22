# ⚡ EventPass v2 — Production Event Management System

A hardened, production-ready event management system for ~4000 attendees.
Built on FastAPI + SQLite with email-based QR delivery and atomic check-in.

---

## ✨ What's new in v2

| Area | Change |
|---|---|
| **QR delivery** | Sent by email only — never displayed on screen |
| **Database** | WAL mode + busy_timeout + atomic UPDATE for scan & vote |
| **Security** | No fallback secrets — app refuses to start if env vars missing |
| **Admin password** | Constant-time comparison (timing-attack safe) |
| **Race conditions** | `UPDATE WHERE attended=0` and `UPDATE WHERE voted=0` eliminate TOCTOU |
| **Email** | Background thread pool, inline + attached PNG, HTML + plain text |
| **Logging** | Structured logs for every login, check-in, vote, and error |

---

## 🚀 Local Setup

### 1. Clone and install

```bash
git clone <your-repo>
cd event_system
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in **every** required variable:

```env
SECRET_KEY=<64-hex-chars from: python -c "import secrets; print(secrets.token_hex(32))">
ADMIN_PASSWORD=<strong-password>
DATABASE_URL=sqlite:///./event_system.db
EMAIL_USER=your_event@gmail.com
EMAIL_PASS=<16-char Gmail App Password>
```

### 3. Gmail App Password setup

1. Go to your Google Account → Security → 2-Step Verification (enable it)
2. Go to https://myaccount.google.com/apppasswords
3. Create an app password for "Mail"
4. Paste the 16-character code into `EMAIL_PASS`

### 4. Run locally

```bash
uvicorn main:app --reload --port 8000
```

The app will **refuse to start** if `SECRET_KEY`, `ADMIN_PASSWORD`, or `DATABASE_URL`
are missing from the environment.

---

## 🌐 Deploy on Railway

### Step 1 — Push to GitHub

```bash
git add .
git commit -m "EventPass v2"
git push origin main
```

### Step 2 — Create Railway project

1. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub**
2. Select your repository

### Step 3 — Add a Volume (REQUIRED for data persistence)

1. In your Railway service → **Add Volume**
2. Mount path: `/data`
3. This ensures the SQLite database survives restarts and redeploys

### Step 4 — Set environment variables

In Railway → your service → **Variables**, add:

```
SECRET_KEY        = <64-hex-char random string>
ADMIN_PASSWORD    = <strong password>
DATABASE_URL      = sqlite:////data/event_system.db
EMAIL_USER        = your_event@gmail.com
EMAIL_PASS        = <Gmail App Password>
EVENT_NAME        = Your Event Name   (optional)
```

### Step 5 — Deploy

Railway detects `railway.json` and runs:
```
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Your app is live at `https://<your-app>.up.railway.app`

---

## 🗂 Project Structure

```
event_system/
├── main.py                        ← Entry point, startup validation, lifespan
├── requirements.txt
├── railway.json                   ← Railway deploy config
├── Procfile                       ← Fallback process config
├── .env.example                   ← Environment template
└── app/
    ├── models/models.py           ← User, Vote, Project (SQLAlchemy)
    ├── routes/
    │   ├── registration.py        ← GET / + POST /register (email QR delivery)
    │   ├── scanner.py             ← GET /scanner + POST /scan (admin-only)
    │   ├── admin.py               ← Dashboard, CSV export, login/logout
    │   └── voting.py              ← /projects (gated) + /vote (atomic)
    ├── services/
    │   ├── email_service.py       ← SMTP email + QR PNG generation (background)
    │   └── qr_service.py          ← QR PNG helpers (used by email service)
    ├── utils/
    │   ├── database.py            ← Engine, WAL pragmas, atomic_checkin, atomic_vote
    │   ├── security.py            ← JWT, admin password verification
    │   └── rate_limiter.py        ← Per-IP in-memory rate limiting
    └── templates/                 ← 10 Jinja2 HTML templates
```

---

## 🔐 Security Model

| Concern | Implementation |
|---|---|
| Admin auth | JWT in HttpOnly cookie, 8-hour expiry, signed with SECRET_KEY |
| Admin password | Plain string env var, constant-time `hmac.compare_digest` comparison |
| QR tokens | HS256 JWT, no expiry (rotate SECRET_KEY between events) |
| TOCTOU (scan) | `UPDATE users SET attended=1 WHERE id=? AND attended=0` — atomic |
| TOCTOU (vote) | `UPDATE users SET voted=1 WHERE id=? AND voted=0 AND attended=1` |
| Fallback secrets | **None** — app crashes at startup if secrets are missing |
| QR on screen | **Never** — QR is only ever emailed, never rendered in browser |
| Rate limiting | Per-IP: 5 reg/min, 120 scan/min, 5 vote/min |

---

## 📧 Email Architecture

```
POST /register
  └─ validate input
  └─ check duplicate email
  └─ create User in DB
  └─ submit send_qr_email_async() → ThreadPoolExecutor (max 4 workers)
       └─ generate QR PNG in memory (never written to disk)
       └─ build MIME email (HTML + plain text + inline CID + PNG attachment)
       └─ SMTP STARTTLS → Gmail
  └─ future.result(timeout=10)
       success → return "check your email" page
       failure → DELETE user from DB, return error to form
```

Email failure rolls back the registration — the user can retry with the same
email address.

---

## 📦 Database (SQLite)

Pragmas set on every connection:

```sql
PRAGMA journal_mode = WAL;        -- concurrent readers + writers
PRAGMA synchronous  = NORMAL;     -- safe, ~2× faster than FULL
PRAGMA busy_timeout = 5000;       -- wait up to 5 s for a write lock
PRAGMA foreign_keys = ON;
PRAGMA temp_store   = MEMORY;
PRAGMA mmap_size    = 268435456;  -- 256 MB memory-mapped I/O
```

**Atomic operations** prevent duplicate check-ins and votes:

```sql
-- Check-in (returns rowcount=1 only for first scan)
UPDATE users SET attended=1, attended_at=? WHERE id=? AND attended=0;

-- Vote (returns rowcount=1 only for first valid vote)
UPDATE users SET voted=1 WHERE id=? AND voted=0 AND attended=1;
```

---

## ⚡ Performance at Scale (4000 attendees)

**Registration phase** (spread over days/hours):
- 5 registrations/min/IP rate limit
- Email sending in background thread — registration HTTP response is instant
- SQLite handles thousands of INSERTs easily

**Door scanning (peak burst)**:
- 10–20 scans/second across 2–4 scanner devices
- Each `/scan` = JWT decode + one `UPDATE` = ~5–15 ms server time
- WAL mode ensures readers (dashboard) never block scanner writers
- Rate limit: 120 scans/min per device IP (2/sec sustained, burst higher)

**Voting phase**:
- Spread over the event duration
- Atomic UPDATE prevents any double-vote regardless of timing

**Estimated capacity on Railway free tier (single instance)**:
- Sustained: ~50 scans/second
- Peak burst: ~100 scans/second (SQLite write lock serialises, busy_timeout queues)
- 4000 attendees in 30 minutes = 2.2/second average — well within capacity

---

## 🚨 Production Checklist

Before your event:

- [ ] Railway Volume attached at `/data`
- [ ] `DATABASE_URL=sqlite:////data/event_system.db` set
- [ ] `SECRET_KEY` is 64+ hex chars, randomly generated
- [ ] `ADMIN_PASSWORD` is strong (20+ chars)
- [ ] Gmail App Password configured and tested
- [ ] Test registration end-to-end (email received, QR scans correctly)
- [ ] Test scanner with admin login on the actual device you'll use at the door
- [ ] Export CSV backup before event starts
- [ ] Keep a paper backup list of registered names for internet-down fallback

---

## 📡 API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/` | Public | Registration form |
| POST | `/register` | Public | Submit registration → QR by email |
| GET | `/scanner` | Admin cookie | QR scanner UI |
| POST | `/scan` | Admin cookie | Check-in via QR JWT |
| GET | `/projects` | UUID + email | Projects page (attended only) |
| POST | `/vote` | UUID + email | Cast vote (atomic) |
| GET | `/admin/login` | Public | Admin login form |
| POST | `/admin/login` | Public | Submit password |
| GET | `/admin/dashboard` | Admin cookie | Attendee overview |
| GET | `/admin/export` | Admin cookie | Download CSV |
| GET | `/admin/votes` | Admin cookie | Vote results |
| GET | `/admin/logout` | Admin cookie | Clear session |
| GET | `/health` | Public | Health check |
