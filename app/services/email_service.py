"""
email_service.py — sends QR code via email using smtplib over TLS.
"""

import io
import logging
import os
import smtplib
import concurrent.futures
import time

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

import qrcode
import qrcode.constants

log = logging.getLogger(__name__)

# ── Thread pool ─────────────────────────────────────────────────────────────
_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="email"
)

# ── Env vars ────────────────────────────────────────────────────────────────
EMAIL_USER = os.getenv("EMAIL_USER", "").strip()
EMAIL_PASS = os.getenv("EMAIL_PASS", "").strip()
SMTP_HOST  = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT  = int(os.getenv("SMTP_PORT", "587"))
EVENT_NAME = os.getenv("EVENT_NAME", "EventPass")


# ── QR generator ────────────────────────────────────────────────────────────
def _generate_qr_png(data: str) -> bytes:
    qr = qrcode.QRCode(
        version=2,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0a0a0f", back_color="white")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ── Blocking send ───────────────────────────────────────────────────────────
def _send_blocking(
    to_name: str,
    to_email: str,
    user_uuid: str,
    jwt_token: str,
) -> None:
    # 👇 مهم جدًا علشان Gmail ما يعملش rate limit
    time.sleep(1)

    if not EMAIL_USER or not EMAIL_PASS:
        raise RuntimeError(
            "EMAIL_USER and EMAIL_PASS must be set in environment."
        )

    qr_png = _generate_qr_png(jwt_token)

    # ── Build message ──────────────────────────────────────────────────────
    msg = MIMEMultipart("related")
    msg["Subject"] = f"Your Entry Pass — {EVENT_NAME}"
    msg["From"]    = f"{EVENT_NAME} <{EMAIL_USER}>"
    msg["To"]      = f"{to_name} <{to_email}>"

    html_body = f"""
    <html>
    <body style="font-family:Arial;background:#f4f4f8;padding:20px">
        <h2>Hello {to_name} 👋</h2>
        <p>Your registration is confirmed.</p>
        <p>Show this QR at the event entrance:</p>
        <img src="cid:qrcode" width="220"/>
        <p><b>Your ID:</b> {user_uuid}</p>
    </body>
    </html>
    """

    plain_body = f"""
Hello {to_name},

Your registration is confirmed.

Your ID: {user_uuid}

QR code is attached.
"""

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(plain_body, "plain", "utf-8"))
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt)

    # ── Attach QR ─────────────────────────────────────────────────────────
    qr_img = MIMEImage(qr_png, "png")
    qr_img.add_header("Content-ID", "<qrcode>")
    msg.attach(qr_img)

    qr_attach = MIMEImage(qr_png, "png")
    qr_attach.add_header("Content-Disposition", "attachment", filename="qr.png")
    msg.attach(qr_attach)

    # ── SMTP ──────────────────────────────────────────────────────────────
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, [to_email], msg.as_bytes())

        log.info("✅ Email sent to %s <%s>", to_name, to_email)

    except Exception as e:
        log.error("❌ SMTP failed for %s: %s", to_email, e)
        raise


# ── Async wrapper ───────────────────────────────────────────────────────────
def send_qr_email_async(
    to_name: str,
    to_email: str,
    user_uuid: str,
    jwt_token: str,
) -> concurrent.futures.Future:
    return _executor.submit(
        _send_blocking,
        to_name,
        to_email,
        user_uuid,
        jwt_token
    )


# ── Config check ────────────────────────────────────────────────────────────
def email_configured() -> bool:
    return bool(EMAIL_USER and EMAIL_PASS)
