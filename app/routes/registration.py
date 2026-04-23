from fastapi import APIRouter, Depends, Request, Form, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import uuid
import secrets
from datetime import datetime, timedelta

from app.utils.database import get_db
from app.utils.security import create_user_jwt
from app.utils.rate_limiter import register_limiter
from app.models import User
from app.services.qr_service import generate_qr_base64

# استيرادات لإرسال البريد
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig
from app.core.config import settings  # يجب أن يكون لديك ملف settings يحتوي على إعدادات SMTP

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# تكوين إعدادات البريد (ضع القيم الصحيحة في ملف settings أو هنا مؤقتاً)
mail_conf = ConnectionConfig(
    MAIL_USERNAME=settings.MAIL_USERNAME,
    MAIL_PASSWORD=settings.MAIL_PASSWORD,
    MAIL_FROM=settings.MAIL_FROM,
    MAIL_PORT=settings.MAIL_PORT,
    MAIL_SERVER=settings.MAIL_SERVER,
    MAIL_STARTTLS=False,
    MAIL_SSL_TLS=True,
    USE_CREDENTIALS=True,
)

async def send_verification_email(email_to: str, token: str):
    """إرسال رابط تأكيد الإيميل إلى المستخدم"""
    verification_url = f"https://yourdomain.com/verify-email?token={token}"  # غيّر الرابط حسب نطاقك
    message = MessageSchema(
        subject="تأكيد بريدك الإلكتروني - مطلوب لاستكمال التسجيل",
        recipients=[email_to],
        body=f"""
        <html>
        <body>
        <h2>مرحباً!</h2>
        <p>شكراً لتسجيلك. يرجى النقر على الرابط أدناه لتأكيد بريدك الإلكتروني واستكمال تسجيلك:</p>
        <a href="{verification_url}">تأكيد البريد الإلكتروني</a>
        <p>هذا الرابط صالح لمدة 24 ساعة.</p>
        <p>إذا لم تقم بطلب هذا التسجيل، يرجى تجاهل هذا البريد.</p>
        </body>
        </html>
        """,
        subtype="html"
    )
    fm = FastMail(mail_conf)
    await fm.send_message(message)

# صفحة عرض نموذج التسجيل (بدون تغيير)
@router.get("/", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

# معالجة التسجيل (بعد تعديلها)
@router.post("/register", response_class=HTMLResponse)
async def register_user(
    request: Request,
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    # التحقق من معدل الطلبات
    client_ip = request.client.host
    if not register_limiter.is_allowed(client_ip):
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "لقد تجاوزت الحد المسموح من المحاولات. يرجى الانتظار قليلاً."
        })

    name = name.strip()
    email = email.strip().lower()

    # التحقق من صحة البيانات الأساسية
    if not name or not email or "@" not in email:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "الرجاء إدخال اسم وإيميل صحيح."
        })

    # التحقق من عدم وجود الإيميل مسجلاً مسبقاً
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "هذا الإيميل مسجل بالفعل."
        })

    # إنشاء رمز تحقق عشوائي
    verification_token = secrets.token_urlsafe(32)

    # إنشاء معرف مستخدم مؤقت (لا يتم إنشاء JWT ولا QR الآن)
    user_id = str(uuid.uuid4())

    # حفظ المستخدم مع حالة غير مؤكد (email_verified = False)
    user = User(
        id=user_id,
        name=name,
        email=email,
        jwt_token=None,          # لم يتم إنشاؤه بعد
        attended=False,
        voted=False,
        email_verified=False,    # حقل جديد يجب إضافته في موديل User
        verification_token=verification_token,  # حقل جديد
        verification_expires=datetime.utcnow() + timedelta(hours=24)  # حقل جديد (اختياري)
    )
    db.add(user)
    db.commit()

    # إرسال بريد التأكيد في الخلفية (حتى لا ينتظر المستخدم)
    background_tasks.add_task(send_verification_email, email, verification_token)

    # عرض صفحة تفيد بضرورة تفقد البريد
    return templates.TemplateResponse("check_email.html", {
        "request": request,
        "email": email,
    })

# نقطة نهاية تأكيد الإيميل (يتم النقر عليها من الرابط المرسل)
@router.get("/verify-email", response_class=HTMLResponse)
async def verify_email(
    request: Request,
    token: str,
    db: Session = Depends(get_db),
):
    # البحث عن المستخدم باستخدام رمز التحقق
    user = db.query(User).filter(User.verification_token == token).first()

    if not user:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "رابط التأكيد غير صالح أو غير موجود."
        })

    # التحقق من صلاحية الرابط (إذا كان لديك حقل صلاحية)
    if user.verification_expires and datetime.utcnow() > user.verification_expires:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "انتهت صلاحية رابط التأكيد. يرجى التسجيل مرة أخرى."
        })

    # إذا كان قد تم التأكيد مسبقاً
    if user.email_verified:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "هذا البريد الإلكتروني مؤكد بالفعل."
        })

    # إنشاء JWT و QR Code للمستخدم بعد التأكيد
    jwt_token = create_user_jwt(user.id)
    qr_b64 = generate_qr_base64(jwt_token)

    # تحديث بيانات المستخدم
    user.jwt_token = jwt_token
    user.email_verified = True
    user.verification_token = None   # إلغاء الرابط بعد الاستخدام
    user.verification_expires = None # إلغاء تاريخ الانتهاء

    db.commit()

    # عرض صفحة النجاح مع QR Code
    return templates.TemplateResponse("success.html", {
        "request": request,
        "user": user,
        "qr_b64": qr_b64,
    })
