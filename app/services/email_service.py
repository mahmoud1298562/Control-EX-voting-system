"""
email_service.py — sends QR code via email using smtplib over TLS.

Design decisions:
- Runs in a background thread so registration HTTP response is not blocked
  by SMTP latency (typically 500 ms – 3 s).
- QR PNG is generated in-memory and attached as inline CID image + fallback
  attachment — works in Gmail, Outlook, Apple Mail, and mobile clients.
- Returns immediately; caller learns of failure via the returned Future.
- No third-party email library needed — stdlib only (smtplib + email).
"""

import io
import logging
import os
import smtplib
import concurrent.futures
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

import qrcode
import qrcode.constants

log = logging.getLogger(__name__)

# Thread pool — max 4 concurrent SMTP connections.
# Gmail free limit: 500 emails/day, ~20 concurrent connections.
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="email")

EMAIL_USER = os.getenv("EMAIL_USER", "").strip()
EMAIL_PASS = os.getenv("EMAIL_PASS", "").strip()
SMTP_HOST  = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT  = int(os.getenv("SMTP_PORT", "587"))
EVENT_NAME = os.getenv("EVENT_NAME", "EventPass")


def _generate_qr_png(data: str) -> bytes:
    """Generate QR code PNG bytes in memory — never touches disk."""
    qr = qrcode.QRCode(
        version=2,
        error_correction=qrcode.constants.ERROR_CORRECT_H,  # H = 30% recovery
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0a0a0f", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _send_blocking(
    to_name: str,
    to_email: str,
    user_uuid: str,
    jwt_token: str,
) -> None:
    """
    Blocking send — called in a worker thread.
    Raises on failure so the Future captures the exception.
    """
    if not EMAIL_USER or not EMAIL_PASS:
        raise RuntimeError(
            "EMAIL_USER and EMAIL_PASS must be set in environment to send emails."
        )

    qr_png = _generate_qr_png(jwt_token)

    # ── Build MIME message ─────────────────────────────────────────────────
    msg = MIMEMultipart("related")
    msg["Subject"] = f"Your Entry Pass — {EVENT_NAME}"
    msg["From"]    = f"{EVENT_NAME} <{EMAIL_USER}>"
    msg["To"]      = f"{to_name} <{to_email}>"

    html_body = f"""\
<html>
<body style="margin:0;padding:0;background:#f4f4f8;font-family:'Helvetica Neue',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f8;padding:32px 0">
  <tr><td align="center">
    <table width="560" cellpadding="0" cellspacing="0"
           style="background:#ffffff;border-radius:12px;overflow:hidden;
                  box-shadow:0 4px 24px rgba(0,0,0,0.08)">
      <!-- Header -->
      <tr>
        <td style="background:#0a0a0f;padding:28px 40px">
          <p style="margin:0;font-size:22px;font-weight:800;color:#7c6fff;
                    letter-spacing:-0.03em">⚡ {EVENT_NAME}</p>
          <p style="margin:4px 0 0;font-size:13px;color:#6b6b80">Entry Pass</p>
        </td>
      </tr>
      <!-- Body -->
      <tr>
        <td style="padding:36px 40px">
          <p style="margin:0 0 8px;font-size:20px;font-weight:700;color:#13131a">
            Hello, {to_name}!
          </p>
          <p style="margin:0 0 28px;font-size:15px;color:#555;line-height:1.6">
            Your registration is confirmed. Present the QR code below at the entrance —
            the organiser will scan it to check you in.
          </p>
          <!-- QR code (inline CID) -->
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td align="center" style="padding:24px;background:#f8f8fc;border-radius:10px">
              <img src="cid:qrcode" width="220" height="220"
                   alt="Your QR entry code"
                   style="display:block;border:0" />
            </td></tr>
          </table>
          <!-- UUID -->
          <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:24px">
            <tr>
              <td style="background:#f0f0f8;border-radius:8px;padding:14px 18px">
                <p style="margin:0 0 4px;font-size:11px;font-weight:700;
                           color:#999;letter-spacing:0.06em;text-transform:uppercase">
                  Your unique ID
                </p>
                <p style="margin:0;font-family:monospace;font-size:13px;
                           color:#7c6fff;word-break:break-all">{user_uuid}</p>
              </td>
            </tr>
          </table>
          <!-- Instructions -->
          <p style="margin:28px 0 0;font-size:14px;color:#555;line-height:1.7">
            <strong>Instructions:</strong><br>
            1. Save this email or take a screenshot of the QR code.<br>
            2. Show the QR at the door — one scan per person.<br>
            3. After check-in, use your ID above to access the Projects page and vote.
          </p>
        </td>
      </tr>
      <!-- Footer -->
      <tr>
        <td style="background:#f8f8fc;padding:20px 40px;border-top:1px solid #eee">
          <p style="margin:0;font-size:12px;color:#999">
            This pass is personal and non-transferable.
            Do not share your QR code or unique ID publicly.
          </p>
        </td>
      </tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""

    plain_body = (
        f"Hello {to_name},\n\n"
        f"Your registration for {EVENT_NAME} is confirmed.\n\n"
        f"Your unique ID: {user_uuid}\n\n"
        "Your QR entry code is attached as a PNG image to this email.\n"
        "Show it at the door to check in.\n\n"
        "Instructions:\n"
        "1. Save this email or screenshot the QR code.\n"
        "2. Show the QR at the door — one scan per person.\n"
        "3. After check-in, use your ID above on the Projects page to vote.\n\n"
        "This pass is personal and non-transferable."
    )

    # Attach text/plain alternative
    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(plain_body, "plain", "utf-8"))
    alternative.attach(MIMEText(html_body,  "html",  "utf-8"))
    msg.attach(alternative)

    # Attach QR as inline image (CID)
    qr_img = MIMEImage(qr_png, "png")
    qr_img.add_header("Content-ID", "<qrcode>")
    qr_img.add_header("Content-Disposition", "inline", filename="entry_pass.png")
    msg.attach(qr_img)

    # Also add as regular attachment for clients that block inline images
    qr_attach = MIMEImage(qr_png, "png")
    qr_attach.add_header("Content-Disposition", "attachment", filename="entry_pass.png")
    msg.attach(qr_attach)

    # ── SMTP send ──────────────────────────────────────────────────────────
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, [to_email], msg.as_bytes())

    log.info("Email sent to %s <%s>", to_name, to_email)


def send_qr_email_async(
    to_name: str,
    to_email: str,
    user_uuid: str,
    jwt_token: str,
) -> concurrent.futures.Future:
    """
    Submit email send to background thread pool.
    Returns a Future — caller may call .result() to block or just let it run.
    """
    return _executor.submit(_send_blocking, to_name, to_email, user_uuid, jwt_token)


def email_configured() -> bool:
    """True if email credentials are present in environment."""
    return bool(EMAIL_USER and EMAIL_PASS)
