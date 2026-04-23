"""
email_service.py — Resend API-based email delivery.
No SMTP, no blocked ports, works on Railway, Render, Fly.io, etc.
"""
import base64
import io
import logging
import os
import concurrent.futures

import resend
import qrcode
import qrcode.constants

log = logging.getLogger(__name__)

resend.api_key = os.environ.get("RESEND_API_KEY", "")

EVENT_NAME   = os.getenv("EVENT_NAME", "EventPass")
FROM_ADDRESS = os.getenv("EMAIL_FROM", f"{EVENT_NAME} <onboarding@resend.dev>")

_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="email"
)


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


def _send_blocking(
    to_name: str,
    to_email: str,
    user_uuid: str,
    jwt_token: str,
) -> None:
    if not resend.api_key:
        raise RuntimeError("RESEND_API_KEY environment variable is not set.")

    qr_png   = _generate_qr_png(jwt_token)
    qr_b64   = base64.b64encode(qr_png).decode()

    html_body = f"""
<html>
<body style="margin:0;padding:0;background:#f4f4f8;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="padding:32px 0">
  <tr><td align="center">
    <table width="560" cellpadding="0" cellspacing="0"
           style="background:#fff;border-radius:12px;overflow:hidden;
                  box-shadow:0 4px 24px rgba(0,0,0,0.08)">
      <tr>
        <td style="background:#0a0a0f;padding:28px 40px">
          <p style="margin:0;font-size:22px;font-weight:800;color:#7c6fff">
            ⚡ {EVENT_NAME}
          </p>
          <p style="margin:4px 0 0;font-size:13px;color:#6b6b80">Entry Pass</p>
        </td>
      </tr>
      <tr>
        <td style="padding:36px 40px">
          <p style="margin:0 0 8px;font-size:20px;font-weight:700;color:#13131a">
            Hello, {to_name}!
          </p>
          <p style="margin:0 0 28px;font-size:15px;color:#555;line-height:1.6">
            Your registration is confirmed. Present the QR code below
            at the entrance to check in.
          </p>
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td align="center"
                    style="padding:24px;background:#f8f8fc;border-radius:10px">
              <img src="cid:qrcode" width="220" height="220"
                   alt="Your QR entry code"
                   style="display:block;border:0" />
            </td></tr>
          </table>
          <table width="100%" cellpadding="0" cellspacing="0"
                 style="margin-top:24px">
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
          <p style="margin:28px 0 0;font-size:14px;color:#555;line-height:1.7">
            <strong>Instructions:</strong><br>
            1. Save this email or screenshot the QR code.<br>
            2. Show the QR at the door — one scan per person.<br>
            3. After check-in, use your ID above to access Projects and vote.
          </p>
        </td>
      </tr>
      <tr>
        <td style="background:#f8f8fc;padding:20px 40px;border-top:1px solid #eee">
          <p style="margin:0;font-size:12px;color:#999">
            This pass is personal and non-transferable.
          </p>
        </td>
      </tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""

    params = resend.Emails.SendParams(
        from_=FROM_ADDRESS,
        to=[f"{to_name} <{to_email}>"],
        subject=f"Your Entry Pass — {EVENT_NAME}",
        html=html_body,
        attachments=[
            resend.Attachment(
                filename="entry_pass.png",
                content=list(qr_png),   # Resend expects list of ints
            )
        ],
    )
    response = resend.Emails.send(params)
    log.info("Resend delivered to %s — id=%s", to_email, response["id"])


def send_qr_email_async(
    to_name: str,
    to_email: str,
    user_uuid: str,
    jwt_token: str,
) -> concurrent.futures.Future:
    return _executor.submit(_send_blocking, to_name, to_email, user_uuid, jwt_token)


def email_configured() -> bool:
    return bool(os.getenv("RESEND_API_KEY", "").strip())
