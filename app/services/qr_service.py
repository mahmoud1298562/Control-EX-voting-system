import qrcode
import io
import base64
import os

QR_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "qrcodes")

def generate_qr_base64(data: str) -> str:
    """Generate QR code and return as base64 string for inline display."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("utf-8")

def generate_qr_file(data: str, filename: str) -> str:
    """Generate QR code and save to file, returns relative path."""
    os.makedirs(QR_DIR, exist_ok=True)
    filepath = os.path.join(QR_DIR, filename)
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(filepath)
    return f"/static/qrcodes/{filename}"
