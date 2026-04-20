from flask import Flask, request, jsonify, render_template, session, redirect, url_for, send_from_directory
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import case, or_
from datetime import datetime, timedelta, UTC
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
import os
import json
import gzip
import io
import uuid
import subprocess
import requests
from urllib.request import urlopen, Request
from urllib.parse import quote
from functools import wraps
from flask_mail import Mail, Message
import secrets
import hashlib

load_dotenv()

app = Flask(__name__)

MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN", "")
BASE_URL = os.getenv("BASE_URL", "https://www.cataloginpk.com.br")

VIP_PLAN_PRICES = {
    "VIP_BRONZE": 19.90,
    "VIP_PRATA": 39.90,
    "VIP_OURO": 59.90,
    "VIP_PREMIUM": 99.90
}

VIP_PLAN_DAYS = {
    "VIP_BRONZE": 30,
    "VIP_PRATA": 30,
    "VIP_OURO": 30,
    "VIP_PREMIUM": 30
}

app.secret_key = os.getenv("SECRET_KEY", "michaelis1")
CORS(app)

app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL",
    "postgresql+pg8000://postgres:postgres@localhost:5432/catalogo_db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT", 587))
app.config["MAIL_USE_TLS"] = os.getenv("MAIL_USE_TLS", "true").lower() == "true"
app.config["MAIL_USE_SSL"] = os.getenv("MAIL_USE_SSL", "false").lower() == "true"
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME", "")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD", "")
app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_DEFAULT_SENDER", app.config["MAIL_USERNAME"])

db = SQLAlchemy(app)
mail = Mail(app)

RENDER_DISK_PATH = os.getenv("RENDER_DISK_PATH", "")
UPLOAD_BASE = RENDER_DISK_PATH if RENDER_DISK_PATH else os.path.join("static", "uploads")

UPLOAD_IMAGE_FOLDER = os.path.join(UPLOAD_BASE, "images")
UPLOAD_VIDEO_FOLDER = os.path.join(UPLOAD_BASE, "videos")

os.makedirs(UPLOAD_IMAGE_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_VIDEO_FOLDER, exist_ok=True)

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
ALLOWED_VIDEO_EXTENSIONS = {"mp4"}

app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

# =========================
# MODELS
# =========================

class ManagedLocation(db.Model):
    __tablename__ = "managed_locations"

    id = db.Column(db.Integer, primary_key=True)
    state = db.Column(db.String(10), nullable=False, index=True)
    city = db.Column(db.String(150), nullable=False, index=True)
    neighborhood = db.Column(db.String(150), nullable=True, index=True)
    street = db.Column(db.String(150), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint(
            "state",
            "city",
            "neighborhood",
            "street",
            name="uq_managed_location_full"
        ),
    )


def serialize_managed_location(location):
    return {
        "id": location.id,
        "state": location.state,
        "city": location.city,
        "neighborhood": location.neighborhood,
        "street": location.street,
        "created_at": location.created_at.isoformat() if location.created_at else None
    }
    
class BlockedLocation(db.Model):
    __tablename__ = "blocked_locations"

    id = db.Column(db.Integer, primary_key=True)
    state = db.Column(db.String(10), nullable=True, index=True)
    city = db.Column(db.String(150), nullable=True, index=True)
    neighborhood = db.Column(db.String(150), nullable=True, index=True)
    street = db.Column(db.String(150), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)    

class AppSetting(db.Model):
    __tablename__ = "app_settings"

    id = db.Column(db.Integer, primary_key=True)

    free_ads_limit = db.Column(db.Integer, nullable=False, default=1)
    free_keywords_limit = db.Column(db.Integer, nullable=False, default=3)
    free_can_use_images = db.Column(db.Boolean, nullable=False, default=False)
    free_can_use_videos = db.Column(db.Boolean, nullable=False, default=False)
    free_can_appear_in_vip_list = db.Column(db.Boolean, nullable=False, default=False)
    free_can_show_full_details = db.Column(db.Boolean, nullable=False, default=False)
    free_can_use_vitrine = db.Column(db.Boolean, nullable=False, default=False)

    bronze_ads_limit = db.Column(db.Integer, nullable=False, default=5)
    bronze_keywords_limit = db.Column(db.Integer, nullable=False, default=10)
    bronze_can_use_images = db.Column(db.Boolean, nullable=False, default=True)
    bronze_can_use_videos = db.Column(db.Boolean, nullable=False, default=False)
    bronze_can_appear_in_vip_list = db.Column(db.Boolean, nullable=False, default=True)
    bronze_can_show_full_details = db.Column(db.Boolean, nullable=False, default=True)
    bronze_price = db.Column(db.Float, nullable=False, default=19.90)
    bronze_can_use_vitrine = db.Column(db.Boolean, nullable=False, default=True)

    prata_ads_limit = db.Column(db.Integer, nullable=False, default=10)
    prata_keywords_limit = db.Column(db.Integer, nullable=False, default=15)
    prata_can_use_images = db.Column(db.Boolean, nullable=False, default=True)
    prata_can_use_videos = db.Column(db.Boolean, nullable=False, default=True)
    prata_can_appear_in_vip_list = db.Column(db.Boolean, nullable=False, default=True)
    prata_can_show_full_details = db.Column(db.Boolean, nullable=False, default=True)
    prata_price = db.Column(db.Float, nullable=False, default=39.90)
    prata_can_use_vitrine = db.Column(db.Boolean, nullable=False, default=True)

    ouro_ads_limit = db.Column(db.Integer, nullable=False, default=20)
    ouro_keywords_limit = db.Column(db.Integer, nullable=False, default=20)
    ouro_can_use_images = db.Column(db.Boolean, nullable=False, default=True)
    ouro_can_use_videos = db.Column(db.Boolean, nullable=False, default=True)
    ouro_can_appear_in_vip_list = db.Column(db.Boolean, nullable=False, default=True)
    ouro_can_show_full_details = db.Column(db.Boolean, nullable=False, default=True)
    ouro_price = db.Column(db.Float, nullable=False, default=59.90)
    ouro_can_use_vitrine = db.Column(db.Boolean, nullable=False, default=True)

    premium_ads_limit = db.Column(db.Integer, nullable=False, default=50)
    premium_keywords_limit = db.Column(db.Integer, nullable=False, default=30)
    premium_can_use_images = db.Column(db.Boolean, nullable=False, default=True)
    premium_can_use_videos = db.Column(db.Boolean, nullable=False, default=True)
    premium_can_appear_in_vip_list = db.Column(db.Boolean, nullable=False, default=True)
    premium_can_show_full_details = db.Column(db.Boolean, nullable=False, default=True)
    premium_price = db.Column(db.Float, nullable=False, default=99.90)
    premium_can_use_vitrine = db.Column(db.Boolean, nullable=False, default=True)
    
    support_whatsapp = db.Column(db.String(30), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    cpf = db.Column(db.String(20), nullable=True)
    phone = db.Column(db.String(30), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    plan = db.Column(db.String(20), nullable=False, default="FREE")
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    blocked_until = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    vip_expires_at = db.Column(db.DateTime, nullable=True)
    privacy_policy_accepted_at = db.Column(db.DateTime, nullable=True)

    ads = db.relationship("Ad", backref="user", lazy=True)
    
class VipPurchase(db.Model):
    __tablename__ = "vip_purchases"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    plan = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Float, nullable=False)

    payment_id = db.Column(db.String(50), nullable=True, unique=True, index=True)
    payment_status = db.Column(db.String(30), nullable=False, default="pending")
    payment_method = db.Column(db.String(30), nullable=False, default="pix")

    external_reference = db.Column(db.String(120), nullable=True, index=True)
    mp_created_at = db.Column(db.DateTime, nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref="vip_purchases")    
    
class PasswordResetToken(db.Model):
    __tablename__ = "password_reset_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    token_hash = db.Column(db.String(255), nullable=False, unique=True, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref="password_reset_tokens")    


class Ad(db.Model):
    __tablename__ = "ads"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)

    phone = db.Column(db.String(30))

    country = db.Column(db.String(100))
    state = db.Column(db.String(100))
    city = db.Column(db.String(100))
    municipality = db.Column(db.String(100))
    neighborhood = db.Column(db.String(100))

    street = db.Column(db.String(150))
    number = db.Column(db.String(20))
    complement = db.Column(db.String(150))
    zipcode = db.Column(db.String(20))

    plan = db.Column(db.String(20), default="FREE")
    main_image = db.Column(db.String(500))
    main_video = db.Column(db.String(500))
    is_active = db.Column(db.Boolean, default=True)
    blocked_until = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    keywords = db.relationship("Keyword", backref="ad", cascade="all, delete-orphan")
    reports = db.relationship("Report", backref="ad", cascade="all, delete-orphan")


class Keyword(db.Model):
    __tablename__ = "keywords"

    id = db.Column(db.Integer, primary_key=True)
    ad_id = db.Column(db.Integer, db.ForeignKey("ads.id"), nullable=False)
    keyword = db.Column(db.String(100), nullable=False)
    
class Report(db.Model):
    __tablename__ = "reports"

    id = db.Column(db.Integer, primary_key=True)
    ad_id = db.Column(db.Integer, db.ForeignKey("ads.id"), nullable=False)
    reported_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reporter_message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="OPEN")
    action_taken = db.Column(db.String(50), nullable=True)
    action_days = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by_admin_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)    

# =========================
# HELPERS
# =========================

def generate_reset_token():
    return secrets.token_urlsafe(32)


def hash_reset_token(raw_token):
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    
def utc_now():
    return datetime.now(UTC).replace(tzinfo=None)    


def send_password_reset_email(user, raw_token):
    reset_link = f"{BASE_URL}/reset-password-page?token={quote(raw_token)}"

    msg = Message(
        subject="Recuperação de senha",
        recipients=[user.email],
        body=f"""Olá, {user.name}!

Recebemos uma solicitação para redefinir sua senha.

Clique no link abaixo para cadastrar uma nova senha:
{reset_link}

Se você não solicitou isso, ignore este e-mail.

Este link expira em 30 minutos.
"""
    )

    mail.send(msg)

@app.route("/vip/create-pix", methods=["POST"])
def create_vip_pix():
    try:
        print("=== INICIO create_vip_pix ===", flush=True)
        print("SESSION USER ID:", session.get("user_id"), flush=True)
        print("MP_ACCESS_TOKEN carregado?", bool(MP_ACCESS_TOKEN), flush=True)
        print("BASE_URL:", BASE_URL, flush=True)

        if not session.get("user_id"):
            print("ERRO: usuario nao logado", flush=True)
            return jsonify({"message": "Faça login para contratar um plano VIP."}), 401

        data = request.get_json() or {}
        print("BODY RECEBIDO:", data, flush=True)

        target_plan = (data.get("plan") or "").strip().upper()
        print("PLANO:", target_plan, flush=True)

        if target_plan not in VIP_PLAN_PRICES:
            print("ERRO: plano invalido", flush=True)
            return jsonify({"message": "Plano inválido."}), 400

        user = User.query.get(session["user_id"])
        print("USER ENCONTRADO:", user.id if user else None, flush=True)

        if not user:
            print("ERRO: usuario nao encontrado", flush=True)
            return jsonify({"message": "Usuário não encontrado."}), 404

        if not MP_ACCESS_TOKEN:
            print("ERRO: MP_ACCESS_TOKEN vazio", flush=True)
            return jsonify({"message": "Mercado Pago não configurado."}), 500

        settings = get_app_settings()

        price_map = {
            "VIP_BRONZE": settings.bronze_price,
            "VIP_PRATA": settings.prata_price,
            "VIP_OURO": settings.ouro_price,
            "VIP_PREMIUM": settings.premium_price
        }

        amount = price_map[target_plan]

        payment_payload = {
            "transaction_amount": amount,
            "description": f"Assinatura {target_plan} - usuário {user.id}",
            "payment_method_id": "pix",
            "payer": {
                "email": user.email,
                "first_name": user.name
            },
            "notification_url": f"{BASE_URL}/mercadopago/webhook",
            "external_reference": f"user:{user.id}|plan:{target_plan}"
        }

        headers = {
            "Authorization": f"Bearer {MP_ACCESS_TOKEN}",
            "Content-Type": "application/json",
            "X-Idempotency-Key": str(uuid.uuid4())
        }

        print("PAYLOAD ENVIADO AO MP:", payment_payload, flush=True)

        response = requests.post(
            "https://api.mercadopago.com/v1/payments",
            headers=headers,
            json=payment_payload,
            timeout=30
        )

        print("MP STATUS:", response.status_code, flush=True)
        print("MP TEXTO:", response.text, flush=True)

        try:
            mp_data = response.json()
        except Exception as e:
            print("ERRO AO LER JSON DO MP:", str(e), flush=True)
            return jsonify({
                "message": "Erro ao interpretar resposta do Mercado Pago",
                "raw_text": response.text
            }), 500

        if response.status_code not in (200, 201):
            return jsonify({
                "message": "Erro ao criar pagamento no Mercado Pago.",
                "status_code": response.status_code,
                "details": mp_data
            }), 500

        qr_data = mp_data.get("point_of_interaction", {}).get("transaction_data", {})

        purchase = VipPurchase(
            user_id=user.id,
            plan=target_plan,
            amount=amount,
            payment_id=str(mp_data.get("id")) if mp_data.get("id") else None,
            payment_status=(mp_data.get("status") or "pending"),
            payment_method="pix",
            external_reference=payment_payload["external_reference"],
            mp_created_at=utc_now()
        )

        db.session.add(purchase)
        db.session.commit()

        print("=== SUCESSO create_vip_pix ===", flush=True)

        return jsonify({
            "message": "Pagamento Pix gerado com sucesso.",
            "payment_id": mp_data.get("id"),
            "plan": target_plan,
            "amount": amount,
            "qr_code": qr_data.get("qr_code"),
            "qr_code_base64": qr_data.get("qr_code_base64"),
            "ticket_url": qr_data.get("ticket_url")
        }), 201

    except Exception as e:
        import traceback
        print("=== EXCEPTION create_vip_pix ===", flush=True)
        traceback.print_exc()
        return jsonify({
            "message": "Erro interno no create_vip_pix",
            "error": str(e)
        }), 500
    
@app.route("/vip-payment-page")
def vip_payment_page():
    if not session.get("user_id"):
        return redirect(url_for("auth_page"))
    return render_template("vip_payment.html")  

@app.route("/mercadopago/webhook", methods=["POST"])
def mercadopago_webhook():
    print("=== WEBHOOK RECEBIDO ===", flush=True)
    payload = request.get_json(silent=True) or {}
    print("PAYLOAD WEBHOOK:", payload, flush=True)

    data = payload.get("data", {})
    payment_id = data.get("id")

    # fallback: formato com "resource"
    if not payment_id:
        payment_id = payload.get("resource")

    # fallback: formato via query string
    if not payment_id:
        payment_id = request.args.get("id")

    print("PAYMENT_ID RESOLVIDO:", payment_id, flush=True)

    if not payment_id:
        print("WEBHOOK SEM payment_id", flush=True)
        return jsonify({"message": "ok"}), 200

    headers = {
        "Authorization": f"Bearer {MP_ACCESS_TOKEN}"
    }

    response = requests.get(
        f"https://api.mercadopago.com/v1/payments/{payment_id}",
        headers=headers,
        timeout=30
    )

    print("STATUS CONSULTA PAYMENT:", response.status_code, flush=True)
    print("BODY CONSULTA PAYMENT:", response.text, flush=True)

    if response.status_code != 200:
        return jsonify({"message": "payment not found"}), 200

    payment = response.json()
    print("STATUS PAYMENT:", payment.get("status"), flush=True)

    if payment.get("status") != "approved":
        print("PAGAMENTO AINDA NAO APROVADO", flush=True)
        return jsonify({"message": "ignored"}), 200

    external_reference = payment.get("external_reference", "")

    try:
        parts = dict(item.split(":", 1) for item in external_reference.split("|"))
        user_id = int(parts.get("user"))
        target_plan = parts.get("plan")
    except Exception:
        print("ERRO AO LER external_reference", flush=True)
        return jsonify({"message": "invalid reference"}), 200

    if target_plan not in VIP_PLAN_DAYS:
        print("PLANO INVALIDO NO WEBHOOK", flush=True)
        return jsonify({"message": "invalid plan"}), 200

    user = User.query.get(user_id)
    if not user:
        print("USUARIO NAO ENCONTRADO NO WEBHOOK", flush=True)
        return jsonify({"message": "user not found"}), 200

    now = utc_now()
    expires_at = now + timedelta(days=VIP_PLAN_DAYS[target_plan])

    user.plan = target_plan
    user.vip_expires_at = expires_at
    sync_user_ads_with_plan(user, target_plan)

    purchase = VipPurchase.query.filter_by(payment_id=str(payment_id)).first()

    if not purchase:
        purchase = VipPurchase(
            user_id=user.id,
            plan=target_plan,
            amount=float(payment.get("transaction_amount") or 0),
            payment_id=str(payment_id),
            payment_status="approved",
            payment_method=payment.get("payment_method_id") or "pix",
            external_reference=external_reference,
            mp_created_at=now,
            approved_at=now,
            expires_at=expires_at
        )
        db.session.add(purchase)
    else:
        purchase.plan = target_plan
        purchase.amount = float(payment.get("transaction_amount") or purchase.amount or 0)
        purchase.payment_status = payment.get("status") or "approved"
        purchase.payment_method = payment.get("payment_method_id") or purchase.payment_method or "pix"
        purchase.external_reference = external_reference
        purchase.approved_at = now
        purchase.expires_at = expires_at

    db.session.commit()

    print(f"USUARIO {user.id} ATUALIZADO PARA {target_plan}", flush=True)

    return jsonify({"message": "ok"}), 200
    
@app.route("/vip/check-payment/<int:payment_id>", methods=["GET"])
def check_payment(payment_id):
    headers = {
        "Authorization": f"Bearer {MP_ACCESS_TOKEN}"
    }

    try:
        response = requests.get(
            f"https://api.mercadopago.com/v1/payments/{payment_id}",
            headers=headers,
            timeout=30
        )

        if response.status_code != 200:
            return jsonify({"status": "error"}), 500

        payment = response.json()
        status = payment.get("status")
        external_reference = payment.get("external_reference")

        user_data = None

        if status == "approved" and external_reference:
            try:
                parts = dict(item.split(":", 1) for item in external_reference.split("|"))
                user_id = int(parts.get("user"))
                target_plan = parts.get("plan")
                user = User.query.get(user_id)

                if user and target_plan in VIP_PLAN_DAYS:
                    now = utc_now()
                    expires_at = now + timedelta(days=VIP_PLAN_DAYS[target_plan])

                    if user.plan != target_plan or not user.vip_expires_at or user.vip_expires_at < now:
                        user.plan = target_plan
                        user.vip_expires_at = expires_at

                    sync_user_ads_with_plan(user, target_plan)

                    purchase = VipPurchase.query.filter_by(payment_id=str(payment_id)).first()

                    if not purchase:
                        purchase = VipPurchase(
                            user_id=user.id,
                            plan=target_plan,
                            amount=float(payment.get("transaction_amount") or 0),
                            payment_id=str(payment_id),
                            payment_status="approved",
                            payment_method=payment.get("payment_method_id") or "pix",
                            external_reference=external_reference,
                            mp_created_at=now,
                            approved_at=now,
                            expires_at=expires_at
                        )
                        db.session.add(purchase)
                    else:
                        purchase.payment_status = status
                        purchase.approved_at = purchase.approved_at or now
                        purchase.expires_at = purchase.expires_at or expires_at

                    db.session.commit()
                    user_data = serialize_user(user)
            except Exception:
                pass

        return jsonify({
            "status": status,
            "external_reference": external_reference,
            "user": user_data
        })

    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

def login_required_page(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("auth_page"))
        return view_func(*args, **kwargs)
    return wrapper


def admin_required_page(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("auth_page"))

        if not session.get("is_admin"):
            return redirect(url_for("search_page"))

        return view_func(*args, **kwargs)
    return wrapper

def plan_priority_case():
    return case(
        (Ad.plan == "VIP_PREMIUM", 0),
        (Ad.plan == "VIP_OURO", 1),
        (Ad.plan == "VIP_PRATA", 2),
        (Ad.plan == "VIP_BRONZE", 3),
        else_=4
    )
    
def title_match_priority(term):
    return case(
        (Ad.title.ilike(f"%{term}%"), 0),
        else_=1
    )

def keyword_match_priority(term):
    return case(
        (Ad.keywords.any(Keyword.keyword.ilike(f"%{term}%")), 0),
        else_=1
    )

def description_match_priority(term):
    return case(
        (Ad.description.ilike(f"%{term}%"), 0),
        else_=1
    )

def image_priority_case():
    return case(
        (Ad.main_image.isnot(None), 0),
        else_=1
    )

def video_priority_case():
    return case(
        (Ad.main_video.isnot(None), 0),
        else_=1
    ) 
    
def get_app_settings():
    settings = AppSetting.query.first()

    if not settings:
        settings = AppSetting()
        db.session.add(settings)
        db.session.commit()

    return settings

def serialize_report(report):
    reported_user = User.query.get(report.reported_user_id)
    reviewed_by = User.query.get(report.reviewed_by_admin_id) if report.reviewed_by_admin_id else None

    total_reports = Report.query.filter_by(ad_id=report.ad_id).count()

    return {
        "id": report.id,
        "ad_id": report.ad_id,
        "ad_title": report.ad.title if report.ad else None,
        "reported_user_id": report.reported_user_id,
        "reported_user_name": reported_user.name if reported_user else None,
        "reported_user_email": reported_user.email if reported_user else None,
        "reporter_message": report.reporter_message,
        "status": report.status,
        "action_taken": report.action_taken,
        "action_days": report.action_days,
        "total_reports": total_reports,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "reviewed_at": report.reviewed_at.isoformat() if report.reviewed_at else None,
        "reviewed_by_admin_id": report.reviewed_by_admin_id,
        "reviewed_by_admin_name": reviewed_by.name if reviewed_by else None,
        "blocked_until": report.ad.blocked_until.isoformat() if report.ad and report.ad.blocked_until else None,
        "user_blocked_until": reported_user.blocked_until.isoformat() if reported_user and reported_user.blocked_until else None
    }

def ensure_admin_user():
    admin_email = "jean.facnet@gmail.com"
    admin_password = "michaelis1"

    existing_admin = User.query.filter_by(email=admin_email).first()

    if existing_admin:
        existing_admin.name = "Administrador"
        existing_admin.phone = "(00) 00000-0000"
        existing_admin.is_admin = True
        existing_admin.password_hash = generate_password_hash(admin_password)
        db.session.commit()
        return

    admin_user = User(
        name="Administrador",
        email=admin_email,
        phone="(00) 00000-0000",
        password_hash=generate_password_hash(admin_password),
        plan="VIP_PREMIUM",
        is_admin=True
    )

    db.session.add(admin_user)
    db.session.commit()
    
    
    
def allowed_file(filename, allowed_extensions):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_extensions

def resolve_media_file_path(media_url):
    if not media_url:
        return None

    media_url = str(media_url).strip()
    if not media_url:
        return None

    normalized = media_url.replace("\\", "/").strip()

    # Caso já venha como caminho absoluto no servidor
    if os.path.isabs(normalized):
        return normalized

    # Caso esteja salvo como /static/uploads/...
    if normalized.startswith("/static/uploads/"):
        relative_part = normalized[len("/static/uploads/"):]
        return os.path.join(UPLOAD_BASE, relative_part)

    # Caso esteja salvo como static/uploads/...
    if normalized.startswith("static/uploads/"):
        relative_part = normalized[len("static/uploads/"):]
        return os.path.join(UPLOAD_BASE, relative_part)

    # Caso esteja salvo apenas como uploads/...
    if normalized.startswith("uploads/"):
        relative_part = normalized[len("uploads/"):]
        return os.path.join(UPLOAD_BASE, relative_part)

    # Caso venha só o nome do arquivo, tenta em images e videos
    image_candidate = os.path.join(UPLOAD_IMAGE_FOLDER, os.path.basename(normalized))
    if os.path.exists(image_candidate):
        return image_candidate

    video_candidate = os.path.join(UPLOAD_VIDEO_FOLDER, os.path.basename(normalized))
    if os.path.exists(video_candidate):
        return video_candidate

    # fallback
    return os.path.join(UPLOAD_BASE, normalized.lstrip("/"))
    
def get_video_duration(file_path):
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                file_path
            ],
            capture_output=True,
            text=True
        )

        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except Exception as e:
        print("Erro ao obter duração do vídeo:", e)
        return None
        
        
def sync_user_ads_with_plan(user, target_plan=None):
    if not user:
        return

    effective_plan = (target_plan or user.plan or "FREE").strip().upper()

    if effective_plan not in ["FREE", "VIP_BRONZE", "VIP_PRATA", "VIP_OURO", "VIP_PREMIUM"]:
        effective_plan = "FREE"

    if is_vip_plan(effective_plan):
        if not user.vip_expires_at or user.vip_expires_at <= utc_now():
            effective_plan = "FREE"
            user.plan = "FREE"
            user.vip_expires_at = None
            
    user.plan = effective_plan
    
    plan_rules = get_plan_rules(effective_plan)
    ads_limit = int(plan_rules.get("ads_limit", 0))
    can_use_images = bool(plan_rules.get("can_use_images", False))
    can_use_videos = bool(plan_rules.get("can_use_videos", False))

    user_ads = Ad.query.filter_by(user_id=user.id).order_by(Ad.created_at.desc()).all()

    for index, ad in enumerate(user_ads):
        ad.plan = effective_plan
        ad.is_active = index < ads_limit

        if not can_use_images:
            ad.main_image = None

        if not can_use_videos:
            ad.main_video = None        

def enforce_user_plan(user):
    if not user:
        return

    if not is_vip_plan(user.plan):
        return

    if not user.vip_expires_at:
        return

    if user.vip_expires_at > utc_now():
        return

    user.plan = "FREE"
    user.vip_expires_at = None

    sync_user_ads_with_plan(user, "FREE")
    db.session.commit()

def serialize_ad(ad):
    plan_rules = get_plan_rules(ad.plan)

    safe_main_image = ad.main_image if plan_rules.get("can_use_images") else None
    safe_main_video = ad.main_video if plan_rules.get("can_use_videos") else None

    return {
        "id": ad.id,
        "title": ad.title,
        "description": ad.description,
        "phone": ad.phone,
        "country": ad.country,
        "state": ad.state,
        "city": ad.city,
        "municipality": ad.municipality,
        "neighborhood": ad.neighborhood,
        "street": ad.street,
        "number": ad.number,
        "complement": ad.complement,
        "zipcode": ad.zipcode,
        "plan": ad.plan,
        "main_image": safe_main_image,
        "main_video": safe_main_video,
        "is_active": ad.is_active,
        "plan_label": get_plan_label(ad.plan),
        "can_show_full_details": plan_rules["can_show_full_details"],
        "blocked_until": ad.blocked_until.isoformat() if ad.blocked_until else None,
        "owner_blocked_until": ad.user.blocked_until.isoformat() if ad.user and ad.user.blocked_until else None,
        "created_at": ad.created_at.isoformat() if ad.created_at else None,
        "keywords": [k.keyword for k in ad.keywords]
    }


def serialize_user(user):
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "phone": user.phone,
        "plan": user.plan,
        "is_admin": user.is_admin,
        "plan_label": get_plan_label(user.plan),
        "blocked_until": user.blocked_until.isoformat() if user.blocked_until else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "vip_expires_at": user.vip_expires_at.isoformat() if user.vip_expires_at else None
    }

def serialize_vip_purchase(purchase):
    return {
        "id": purchase.id,
        "plan": purchase.plan,
        "plan_label": get_plan_label(purchase.plan),
        "amount": purchase.amount,
        "payment_id": purchase.payment_id,
        "payment_status": purchase.payment_status,
        "payment_method": purchase.payment_method,
        "external_reference": purchase.external_reference,
        "mp_created_at": purchase.mp_created_at.isoformat() if purchase.mp_created_at else None,
        "approved_at": purchase.approved_at.isoformat() if purchase.approved_at else None,
        "expires_at": purchase.expires_at.isoformat() if purchase.expires_at else None,
        "created_at": purchase.created_at.isoformat() if purchase.created_at else None
    }
    
def fetch_ibge_json(url):
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Accept-Encoding": "gzip"
        }
    )

    with urlopen(req, timeout=20) as response:
        data = response.read()

        if response.headers.get("Content-Encoding") == "gzip":
            buf = io.BytesIO(data)
            f = gzip.GzipFile(fileobj=buf)
            data = f.read()

        return json.loads(data.decode("utf-8"))
        
def normalize_cpf(value):
    return "".join(ch for ch in (value or "") if ch.isdigit())

def is_valid_cpf(cpf):
    cpf = normalize_cpf(cpf)

    if len(cpf) != 11:
        return False

    if cpf == cpf[0] * 11:
        return False

    total = sum(int(cpf[i]) * (10 - i) for i in range(9))
    first_digit = 11 - (total % 11)
    if first_digit >= 10:
        first_digit = 0

    if first_digit != int(cpf[9]):
        return False

    total = sum(int(cpf[i]) * (11 - i) for i in range(10))
    second_digit = 11 - (total % 11)
    if second_digit >= 10:
        second_digit = 0

    return second_digit == int(cpf[10])        
        
def is_blocked_location(state=None, city=None, neighborhood=None, street=None):
    query = BlockedLocation.query

    if state:
        query = query.filter(BlockedLocation.state == state)

    # BLOQUEIO EXATO DE RUA
    if street:
        return query.filter(
            BlockedLocation.city == city,
            BlockedLocation.neighborhood == neighborhood,
            BlockedLocation.street == street
        ).first() is not None

    # BLOQUEIO EXATO DE BAIRRO
    if neighborhood:
        return query.filter(
            BlockedLocation.city == city,
            BlockedLocation.neighborhood == neighborhood,
            BlockedLocation.street.is_(None)
        ).first() is not None

    # BLOQUEIO EXATO DE CIDADE
    if city:
        return query.filter(
            BlockedLocation.city == city,
            BlockedLocation.neighborhood.is_(None),
            BlockedLocation.street.is_(None)
        ).first() is not None

    # BLOQUEIO EXATO APENAS DE ESTADO
    return query.filter(
        BlockedLocation.city.is_(None),
        BlockedLocation.neighborhood.is_(None),
        BlockedLocation.street.is_(None)
    ).first() is not None        
        
VIP_PLANS = ["VIP_BRONZE", "VIP_PRATA", "VIP_OURO", "VIP_PREMIUM"]

def is_vip_plan(plan):
    return plan in VIP_PLANS

def get_plan_label(plan):
    labels = {
        "FREE": "FREE",
        "VIP_BRONZE": "VIP Bronze",
        "VIP_PRATA": "VIP Prata",
        "VIP_OURO": "VIP Ouro",
        "VIP_PREMIUM": "VIP Premium"
    }
    return labels.get(plan, plan)   

PLAN_RULES = {
    "FREE": {
        "ads_limit": 1,
        "keywords_limit": 3,
        "can_use_images": False,
        "can_use_videos": False,
        "can_appear_in_vip_list": False,
        "can_show_full_details": False
    },
    "VIP_BRONZE": {
        "ads_limit": 5,
        "keywords_limit": 10,
        "can_use_images": True,
        "can_use_videos": False,
        "can_appear_in_vip_list": True,
        "can_show_full_details": True
    },
    "VIP_PRATA": {
        "ads_limit": 10,
        "keywords_limit": 15,
        "can_use_images": True,
        "can_use_videos": True,
        "can_appear_in_vip_list": True,
        "can_show_full_details": True
    },
    "VIP_OURO": {
        "ads_limit": 20,
        "keywords_limit": 20,
        "can_use_images": True,
        "can_use_videos": True,
        "can_appear_in_vip_list": True,
        "can_show_full_details": True
    },
    "VIP_PREMIUM": {
        "ads_limit": 50,
        "keywords_limit": 30,
        "can_use_images": True,
        "can_use_videos": True,
        "can_appear_in_vip_list": True,
        "can_show_full_details": True
    }
}

def get_plan_rules(plan):
    settings = get_app_settings()

    rules_map = {
        "FREE": {
            "ads_limit": settings.free_ads_limit,
            "keywords_limit": settings.free_keywords_limit,
            "can_use_images": settings.free_can_use_images,
            "can_use_videos": settings.free_can_use_videos,
            "can_appear_in_vip_list": settings.free_can_appear_in_vip_list,
            "can_show_full_details": settings.free_can_show_full_details,
            "can_use_vitrine": settings.free_can_use_vitrine
        },
        "VIP_BRONZE": {
            "ads_limit": settings.bronze_ads_limit,
            "keywords_limit": settings.bronze_keywords_limit,
            "can_use_images": settings.bronze_can_use_images,
            "can_use_videos": settings.bronze_can_use_videos,
            "can_appear_in_vip_list": settings.bronze_can_appear_in_vip_list,
            "can_show_full_details": settings.bronze_can_show_full_details,
            "can_use_vitrine": settings.bronze_can_use_vitrine
        },
        "VIP_PRATA": {
            "ads_limit": settings.prata_ads_limit,
            "keywords_limit": settings.prata_keywords_limit,
            "can_use_images": settings.prata_can_use_images,
            "can_use_videos": settings.prata_can_use_videos,
            "can_appear_in_vip_list": settings.prata_can_appear_in_vip_list,
            "can_show_full_details": settings.prata_can_show_full_details,
            "can_use_vitrine": settings.prata_can_use_vitrine
        },
        "VIP_OURO": {
            "ads_limit": settings.ouro_ads_limit,
            "keywords_limit": settings.ouro_keywords_limit,
            "can_use_images": settings.ouro_can_use_images,
            "can_use_videos": settings.ouro_can_use_videos,
            "can_appear_in_vip_list": settings.ouro_can_appear_in_vip_list,
            "can_show_full_details": settings.ouro_can_show_full_details,
            "can_use_vitrine": settings.ouro_can_use_vitrine
        },
        "VIP_PREMIUM": {
            "ads_limit": settings.premium_ads_limit,
            "keywords_limit": settings.premium_keywords_limit,
            "can_use_images": settings.premium_can_use_images,
            "can_use_videos": settings.premium_can_use_videos,
            "can_appear_in_vip_list": settings.premium_can_appear_in_vip_list,
            "can_show_full_details": settings.premium_can_show_full_details,
            "can_use_vitrine": settings.premium_can_use_vitrine
        }
    }

    return rules_map.get(plan, rules_map["FREE"])


def normalize_keywords(keywords):
    cleaned_keywords = []

    for keyword in keywords or []:
        raw_value = str(keyword).strip()
        if not raw_value:
            continue

        parts = [part.strip() for part in raw_value.split(",") if part.strip()]

        for part in parts:
            subparts = [item.strip() for item in part.split() if item.strip()]

            for word in subparts:
                if word.lower() not in [k.lower() for k in cleaned_keywords]:
                    cleaned_keywords.append(word)

    return cleaned_keywords


DF_ADMIN_REGIONS = [
    {"id": 1, "nome": "Plano Piloto", "sigla": "RA I"},
    {"id": 2, "nome": "Gama", "sigla": "RA II"},
    {"id": 3, "nome": "Taguatinga", "sigla": "RA III"},
    {"id": 4, "nome": "Brazlândia", "sigla": "RA IV"},
    {"id": 5, "nome": "Sobradinho", "sigla": "RA V"},
    {"id": 6, "nome": "Planaltina", "sigla": "RA VI"},
    {"id": 7, "nome": "Paranoá", "sigla": "RA VII"},
    {"id": 8, "nome": "Núcleo Bandeirante", "sigla": "RA VIII"},
    {"id": 9, "nome": "Ceilândia", "sigla": "RA IX"},
    {"id": 10, "nome": "Guará", "sigla": "RA X"},
    {"id": 11, "nome": "Cruzeiro", "sigla": "RA XI"},
    {"id": 12, "nome": "Samambaia", "sigla": "RA XII"},
    {"id": 13, "nome": "Santa Maria", "sigla": "RA XIII"},
    {"id": 14, "nome": "São Sebastião", "sigla": "RA XIV"},
    {"id": 15, "nome": "Recanto das Emas", "sigla": "RA XV"},
    {"id": 16, "nome": "Lago Sul", "sigla": "RA XVI"},
    {"id": 17, "nome": "Riacho Fundo", "sigla": "RA XVII"},
    {"id": 18, "nome": "Lago Norte", "sigla": "RA XVIII"},
    {"id": 19, "nome": "Candangolândia", "sigla": "RA XIX"},
    {"id": 20, "nome": "Águas Claras", "sigla": "RA XX"},
    {"id": 21, "nome": "Riacho Fundo II", "sigla": "RA XXI"},
    {"id": 22, "nome": "Sudoeste/Octogonal", "sigla": "RA XXII"},
    {"id": 23, "nome": "Varjão", "sigla": "RA XXIII"},
    {"id": 24, "nome": "Park Way", "sigla": "RA XXIV"},
    {"id": 25, "nome": "SCIA / Estrutural", "sigla": "RA XXV"},
    {"id": 26, "nome": "Sobradinho II", "sigla": "RA XXVI"},
    {"id": 27, "nome": "Jardim Botânico", "sigla": "RA XXVII"},
    {"id": 28, "nome": "Itapoã", "sigla": "RA XXVIII"},
    {"id": 29, "nome": "SIA", "sigla": "RA XXIX"},
    {"id": 30, "nome": "Vicente Pires", "sigla": "RA XXX"},
    {"id": 31, "nome": "Fercal", "sigla": "RA XXXI"},
    {"id": 32, "nome": "Sol Nascente / Pôr do Sol", "sigla": "RA XXXII"},
    {"id": 33, "nome": "Arniqueira", "sigla": "RA XXXIII"},
    {"id": 34, "nome": "Arapoanga", "sigla": "RA XXXIV"},
    {"id": 35, "nome": "Água Quente", "sigla": "RA XXXV"},
]

DF_NEIGHBORHOODS = {
    "Ceilândia": [
        "Ceilândia Norte",
        "Ceilândia Sul",
        "Ceilândia Oeste",
        "Guariroba",
        "Setor O",
        "Setor P Sul",
        "Setor P Norte",
        "Expansão e Setor de Oficinas",
        "ADE Centro Norte",
        "Setores Industrial e DMC",
        "Setor QNQ",
        "Setor QNR",
        "Condomínio Privê",
        "Centro Metropolitano"
    ]
}

# =========================
# ROTA DE TESTE
# =========================

@app.route("/sitemap.xml")
def sitemap():
    return """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url>
        <loc>https://www.cataloginpk.com.br/</loc>
      </url>
      <url>
        <loc>https://www.cataloginpk.com.br/search-page</loc>
      </url>
      <url>
        <loc>https://www.cataloginpk.com.br/auth-page</loc>
      </url>
      <url>
        <loc>https://www.cataloginpk.com.br/register-page</loc>
      </url>
      <url>
        <loc>https://cataloguinho.onrender.com/create-ad-page</loc>
      </url>
    </urlset>
    """, 200, {"Content-Type": "application/xml"}

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/auth-page")
def auth_page():
    if session.get("user_id"):
        if session.get("is_admin"):
            return redirect(url_for("admin_dashboard_page"))
        return redirect(url_for("search_page"))
    return render_template("auth.html")
    
@app.route("/privacy-policy")
def privacy_policy_page():
    return render_template("privacy_policy.html")    


@app.route("/register-page")
def register_page():
    if session.get("user_id"):
        if session.get("is_admin"):
            return redirect(url_for("admin_dashboard_page"))
        return redirect(url_for("search_page"))
    return render_template("register.html")
    
@app.route("/forgot-password-page")
def forgot_password_page():
    if session.get("user_id"):
        if session.get("is_admin"):
            return redirect(url_for("admin_dashboard_page"))
        return redirect(url_for("search_page"))
    return render_template("forgot_password.html")


@app.route("/reset-password-page")
def reset_password_page():
    if session.get("user_id"):
        if session.get("is_admin"):
            return redirect(url_for("admin_dashboard_page"))
        return redirect(url_for("search_page"))
    return render_template("reset_password.html")    


@app.route("/register", methods=["POST"])
def register():
    data = request.get_json() or {}

    name = data.get("name", "").strip()
    cpf = normalize_cpf(data.get("cpf", ""))
    email = data.get("email", "").strip().lower()
    phone = data.get("phone", "").strip()
    password = data.get("password", "").strip()
    accepted_privacy_policy = bool(data.get("accepted_privacy_policy"))

    if not name or not cpf or not email or not phone or not password:
        return jsonify({"message": "Preencha todos os campos obrigatórios"}), 400

    if not accepted_privacy_policy:
        return jsonify({
            "message": "Você precisa aceitar a Política de Privacidade para se cadastrar."
        }), 400

    if not is_valid_cpf(cpf):
        return jsonify({"message": "CPF inválido"}), 400

    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        return jsonify({"message": "E-mail já cadastrado"}), 400

    existing_cpf = User.query.filter_by(cpf=cpf).first()
    if existing_cpf:
        return jsonify({"message": "CPF já cadastrado"}), 400

    password_hash = generate_password_hash(password)

    user = User(
        name=name,
        cpf=cpf,
        email=email,
        phone=phone,
        password_hash=password_hash,
        plan="FREE",
        privacy_policy_accepted_at=datetime.utcnow()
    )

    db.session.add(user)
    db.session.commit()

    return jsonify({
        "message": "Usuário cadastrado com sucesso",
        "user": serialize_user(user)
    }), 201


@app.route("/login", methods=["POST"])
def login():
    data = request.get_json() or {}

    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()

    if not email or not password:
        return jsonify({"message": "Informe e-mail e senha"}), 400

    user = User.query.filter_by(email=email).first()
    
    if user:
        enforce_user_plan(user)
        sync_user_ads_with_plan(user)
        db.session.commit()
    
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"message": "E-mail ou senha inválidos"}), 401

    if user.blocked_until and user.blocked_until > utc_now():
        return jsonify({
            "message": f"Conta bloqueada até {user.blocked_until.strftime('%d/%m/%Y %H:%M')}"
        }), 403

    session["user_id"] = user.id
    session["is_admin"] = bool(user.is_admin)
    session["user_name"] = user.name

    return jsonify({
        "message": "Login realizado com sucesso",
        "user": serialize_user(user)
    })
    
@app.route("/forgot-password", methods=["POST"])
def forgot_password():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()

    if not email:
        return jsonify({"message": "Informe o e-mail"}), 400

    user = User.query.filter_by(email=email).first()

    generic_response = {
        "message": "Se o e-mail estiver cadastrado, você receberá as instruções de recuperação."
    }

    if not user:
        return jsonify(generic_response), 200

    existing_tokens = PasswordResetToken.query.filter_by(
        user_id=user.id,
        used_at=None
    ).all()

    for item in existing_tokens:
        item.used_at = utc_now()

    raw_token = generate_reset_token()
    token_hash = hash_reset_token(raw_token)

    reset_item = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=utc_now() + timedelta(minutes=30)
    )

    try:
        db.session.add(reset_item)
        db.session.commit()
    except Exception as e:
        import traceback
        db.session.rollback()
        print("=== ERRO AO SALVAR TOKEN DE RECUPERACAO ===", flush=True)
        traceback.print_exc()
        return jsonify({
            "message": "Erro ao salvar token de recuperação.",
            "error": str(e)
        }), 500

    try:
        send_password_reset_email(user, raw_token)
    except Exception as e:
        import traceback
        print("=== ERRO AO ENVIAR E-MAIL DE RECUPERACAO ===", flush=True)
        traceback.print_exc()
        return jsonify({
            "message": "Erro ao enviar e-mail de recuperação.",
            "error": str(e)
        }), 500

    return jsonify(generic_response), 200    
    
@app.route("/reset-password", methods=["POST"])
def reset_password():
    data = request.get_json() or {}

    raw_token = (data.get("token") or "").strip()
    password = (data.get("password") or "").strip()
    confirm_password = (data.get("confirm_password") or "").strip()

    if not raw_token or not password or not confirm_password:
        return jsonify({"message": "Preencha todos os campos"}), 400

    if password != confirm_password:
        return jsonify({"message": "As senhas não coincidem"}), 400

    if len(password) < 6:
        return jsonify({"message": "A senha deve ter pelo menos 6 caracteres"}), 400

    token_hash = hash_reset_token(raw_token)

    reset_item = PasswordResetToken.query.filter_by(
        token_hash=token_hash,
        used_at=None
    ).first()

    if not reset_item:
        return jsonify({"message": "Token inválido ou já utilizado"}), 400

    if reset_item.expires_at < utc_now():
        return jsonify({"message": "Token expirado"}), 400

    user = User.query.get(reset_item.user_id)

    if not user:
        return jsonify({"message": "Usuário não encontrado"}), 404

    user.password_hash = generate_password_hash(password)
    reset_item.used_at = utc_now()

    db.session.commit()

    return jsonify({"message": "Senha redefinida com sucesso"}), 200    
    
@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Logout realizado com sucesso"})    
    
@app.route("/auth/session", methods=["GET"])
def get_current_session():
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({
            "authenticated": False,
            "user": None
        }), 200

    user = User.query.get(user_id)

    if not user:
        session.clear()
        return jsonify({
            "authenticated": False,
            "user": None
        }), 200

    enforce_user_plan(user)
    sync_user_ads_with_plan(user)
    db.session.commit()

    if user.blocked_until and user.blocked_until > utc_now():
        return jsonify({
            "authenticated": True,
            "user": serialize_user(user),
            "blocked": True
        }), 200

    return jsonify({
        "authenticated": True,
        "user": serialize_user(user),
        "blocked": False
    }), 200    

# =========================
# SEARCH
# =========================

@app.route("/search-page")
def search_page():
    return render_template("search.html")


@app.route("/search", methods=["GET"])
def search_ads():
    term = request.args.get("term", "").strip()
    country = request.args.get("country", "").strip()
    state = request.args.get("state", "").strip()
    city = request.args.get("city", "").strip()
    municipality = request.args.get("municipality", "").strip()
    neighborhood = request.args.get("neighborhood", "").strip()
    street = request.args.get("street", "").strip()
    complement = request.args.get("complement", "").strip()
    
    allowed_vip_plans = [
        plan for plan in VIP_PLANS
        if get_plan_rules(plan)["can_appear_in_vip_list"]
    ]

    query = Ad.query.join(User, Ad.user_id == User.id).filter(
        Ad.is_active == True,
        or_(Ad.blocked_until.is_(None), Ad.blocked_until <= utc_now()),
        or_(User.blocked_until.is_(None), User.blocked_until <= utc_now())
    )
    
    has_search = bool(term or country or state or city or municipality or neighborhood or street or complement)

    if not has_search:
        query = query.filter(Ad.plan.in_(allowed_vip_plans))

    if term:
        query = query.filter(
            or_(
                Ad.title.ilike(f"%{term}%"),
                Ad.description.ilike(f"%{term}%"),
                Ad.keywords.any(Keyword.keyword.ilike(f"%{term}%"))
            )
        )

    if country:
        query = query.filter(Ad.country == country)

    if state:
        query = query.filter(Ad.state == state)

    if city:
        query = query.filter(Ad.city == city)

    if municipality:
        query = query.filter(Ad.municipality == municipality)

    if neighborhood:
        query = query.filter(Ad.neighborhood == neighborhood)

    if street:
        query = query.filter(Ad.street.ilike(f"%{street}%"))

    if complement:
        query = query.filter(
            or_(
                Ad.country.ilike(f"%{complement}%"),
                Ad.state.ilike(f"%{complement}%"),
                Ad.city.ilike(f"%{complement}%"),
                Ad.municipality.ilike(f"%{complement}%"),
                Ad.neighborhood.ilike(f"%{complement}%"),
                Ad.street.ilike(f"%{complement}%"),
                Ad.number.ilike(f"%{complement}%"),
                Ad.complement.ilike(f"%{complement}%"),
                Ad.zipcode.ilike(f"%{complement}%")
            )
        )

    if term:
        ads = query.order_by(
            title_match_priority(term),
            keyword_match_priority(term),
            description_match_priority(term),
            plan_priority_case(),
            image_priority_case(),
            video_priority_case(),
            Ad.created_at.desc()
        ).all()
    else:
        ads = query.order_by(
            plan_priority_case(),
            image_priority_case(),
            video_priority_case(),
            Ad.created_at.desc()
        ).all()

    return jsonify([serialize_ad(ad) for ad in ads])

# =========================
# LOCATIONS
# =========================

@app.route("/locations/states", methods=["GET"])
def get_states():
    try:
        url = "https://servicodados.ibge.gov.br/api/v1/localidades/estados?orderBy=nome"
        data = fetch_ibge_json(url)

        states = [
            {
                "id": item["id"],
                "sigla": item["sigla"],
                "nome": item["nome"]
            }
            for item in data
        ]

        return jsonify(states)
    except Exception as e:
        return jsonify({
            "message": "Erro ao carregar estados do IBGE",
            "error": str(e)
        }), 500


@app.route("/locations/cities", methods=["GET"])
def get_cities():
    uf = request.args.get("uf", "").strip().upper()

    if not uf:
        return jsonify({"message": "Informe a UF"}), 400

    if uf == "DF":
        cities = [
            {
                "id": item["id"],
                "nome": item["nome"]
            }
            for item in DF_ADMIN_REGIONS
            if not is_blocked_location(state=uf, city=item["nome"])
        ]
        return jsonify(cities)

    try:
        url = f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{quote(uf)}/municipios?orderBy=nome"
        data = fetch_ibge_json(url)

        cities = []
        seen = set()

        for item in data:
            city_name = (item.get("nome") or "").strip()

            if not city_name:
                continue

            normalized = city_name.casefold()
            if normalized in seen:
                continue

            if is_blocked_location(state=uf, city=city_name):
                continue

            seen.add(normalized)
            cities.append({
                "id": item["id"],
                "nome": city_name
            })

        return jsonify(cities)
    except Exception as e:
        return jsonify({
            "message": "Erro ao carregar municípios do IBGE",
            "error": str(e)
        }), 500


@app.route("/locations/districts", methods=["GET"])
def get_districts():
    return jsonify([])


@app.route("/locations/subdistricts", methods=["GET"])
def get_subdistricts():
    municipio_id = request.args.get("municipio_id", "").strip()

    if not municipio_id:
        return jsonify({"message": "Informe o ID do município"}), 400

    try:
        url = f"https://servicodados.ibge.gov.br/api/v1/localidades/municipios/{quote(municipio_id)}/subdistritos?orderBy=nome"
        data = fetch_ibge_json(url)

        subdistricts = [
            {
                "id": item["id"],
                "nome": item["nome"]
            }
            for item in data
        ]

        return jsonify(subdistricts)
    except Exception as e:
        return jsonify({
            "message": "Erro ao carregar subdistritos do IBGE",
            "error": str(e)
        }), 500


@app.route("/locations/neighborhoods", methods=["GET"])
def get_neighborhoods():
    city = request.args.get("city", "").strip()
    state = request.args.get("state", "").strip().upper()

    if not city:
        return jsonify({"message": "Informe a cidade"}), 400

    if state == "DF":
        items = DF_NEIGHBORHOODS.get(city, [])
        filtered = [
            {"nome": item}
            for item in items
            if not is_blocked_location(state=state, city=city, neighborhood=item)
        ]
        return jsonify(filtered)

    try:
        query_parts = [city, "Brasil"]
        if state:
            query_parts.insert(0, state)

        q = ", ".join(query_parts)

        url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": q,
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": 100
        }

        headers = {
            "User-Agent": "catalogo-app/1.0"
        }

        response = requests.get(url, params=params, headers=headers, timeout=20)
        response.raise_for_status()

        data = response.json()

        neighborhoods = []
        seen = set()

        for item in data:
            address = item.get("address", {})
            suburb = (address.get("suburb") or address.get("neighbourhood") or address.get("quarter") or "").strip()

            if not suburb:
                continue

            normalized = suburb.casefold()
            if normalized in seen:
                continue

            if is_blocked_location(state=state, city=city, neighborhood=suburb):
                continue

            seen.add(normalized)
            neighborhoods.append({
                "nome": suburb
            })

        return jsonify(neighborhoods)
    except Exception as e:
        return jsonify({
            "message": "Erro ao carregar bairros",
            "error": str(e)
        }), 500


@app.route("/locations/streets", methods=["GET"])
def get_streets():
    city = request.args.get("city", "").strip()
    state = request.args.get("state", "").strip().upper()
    neighborhood = request.args.get("neighborhood", "").strip()

    if not city:
        return jsonify({"message": "Informe a cidade"}), 400

    try:
        # 1) PRIORIDADE: localidades gerenciadas manualmente
        managed_query = db.session.query(ManagedLocation.street).filter(
            ManagedLocation.city == city,
            ManagedLocation.street.isnot(None)
        )

        if state:
            managed_query = managed_query.filter(ManagedLocation.state == state)

        if neighborhood:
            managed_query = managed_query.filter(ManagedLocation.neighborhood == neighborhood)

        managed_rows = managed_query.distinct().order_by(ManagedLocation.street.asc()).all()

        managed_streets = []
        seen = set()

        for row in managed_rows:
            street_name = (row[0] or "").strip()
            if not street_name:
                continue

            normalized = street_name.casefold()
            if normalized in seen:
                continue

            if is_blocked_location(
                state=state,
                city=city,
                neighborhood=neighborhood or None,
                street=street_name
            ):
                continue

            seen.add(normalized)
            managed_streets.append({"nome": street_name})

        
        # 2) SEGUNDA PRIORIDADE: ruas já existentes em anúncios
        ad_query = db.session.query(Ad.street).filter(
            Ad.city == city,
            Ad.street.isnot(None),
            Ad.street != "",
            Ad.is_active == True
        )

        if state:
            ad_query = ad_query.filter(Ad.state == state)

        if neighborhood:
            ad_query = ad_query.filter(Ad.neighborhood == neighborhood)

        ad_rows = ad_query.distinct().order_by(Ad.street.asc()).all()

        ad_streets = []
        seen = set()

        for row in ad_rows:
            street_name = (row[0] or "").strip()
            if not street_name:
                continue

            normalized = street_name.casefold()
            if normalized in seen:
                continue

            if is_blocked_location(
                state=state,
                city=city,
                neighborhood=neighborhood or None,
                street=street_name
            ):
                continue

            seen.add(normalized)
            ad_streets.append({"nome": street_name})

        
        # 3) FALLBACK: OpenStreetMap / Overpass
        nominatim_url = "https://nominatim.openstreetmap.org/search"
        headers = {
            "User-Agent": "catalogo-app/1.0"
        }

        if state == "DF":
            search_text = f"{city}, Distrito Federal, Brasil"
        else:
            search_text = f"{city}, {state}, Brasil" if state else f"{city}, Brasil"

        area_resp = requests.get(
            nominatim_url,
            params={
                "q": search_text,
                "format": "jsonv2",
                "limit": 1,
                "addressdetails": 1
            },
            headers=headers,
            timeout=12
        )
        area_resp.raise_for_status()
        area_data = area_resp.json()

        if not area_data:
            return jsonify([])

        osm_type = area_data[0].get("osm_type")
        osm_id = area_data[0].get("osm_id")

        if not osm_type or not osm_id:
            return jsonify([])

        if osm_type == "relation":
            area_id = 3600000000 + int(osm_id)
        elif osm_type == "way":
            area_id = 2400000000 + int(osm_id)
        elif osm_type == "node":
            area_id = 1600000000 + int(osm_id)
        else:
            return jsonify([])

        overpass_query = f"""
        [out:json][timeout:20];
        area({area_id})->.searchArea;
        (
          way["highway"]["name"](area.searchArea);
        );
        out tags;
        """

        overpass_resp = requests.post(
            "https://overpass-api.de/api/interpreter",
            data=overpass_query,
            headers=headers,
            timeout=25
        )
        overpass_resp.raise_for_status()
        overpass_data = overpass_resp.json()

        ignored_types = {
            "footway", "cycleway", "path", "steps", "track",
            "corridor", "bridleway", "pedestrian",
            "proposed", "construction", "service"
        }

        names = set()

        for element in overpass_data.get("elements", []):
            tags = element.get("tags", {})
            name = (tags.get("name") or "").strip()
            highway_type = (tags.get("highway") or "").strip()

            if not name:
                continue

            if highway_type in ignored_types:
                continue

            if is_blocked_location(
                state=state,
                city=city,
                neighborhood=neighborhood or None,
                street=name
            ):
                continue

            names.add(name)

        # 🔥 AGORA JUNTA TUDO
        all_names = set()

        # Managed
        for item in managed_streets:
            all_names.add(item["nome"])

        # Ads
        for item in ad_streets:
            all_names.add(item["nome"])

        # OpenStreetMap
        for name in names:
            all_names.add(name)

        streets = [{"nome": name} for name in sorted(all_names)]

        return jsonify(streets)

    except Exception as e:
        print("Erro ao carregar ruas:", e, flush=True)
        return jsonify([])
        
@app.route("/admin/blocked-locations", methods=["POST"])
def admin_block_location():
    data = request.get_json() or {}

    admin_user_id = data.get("admin_user_id")
    if not admin_user_id:
        return jsonify({"message": "Administrador não informado"}), 400

    admin_user = User.query.get(admin_user_id)
    if not admin_user or not admin_user.is_admin:
        return jsonify({"message": "Acesso negado"}), 403

    state = (data.get("state") or "").strip().upper() or None
    city = (data.get("city") or "").strip() or None
    neighborhood = (data.get("neighborhood") or "").strip() or None
    street = (data.get("street") or "").strip() or None
    streets = data.get("streets") or []

    if not state:
        return jsonify({"message": "Estado não informado"}), 400

    if isinstance(streets, list) and streets:
        created = []

        for item in streets:
            current_street = (item or "").strip() or None

            existing = BlockedLocation.query.filter_by(
                state=state,
                city=city,
                neighborhood=neighborhood,
                street=current_street
            ).first()

            if existing:
                continue

            blocked = BlockedLocation(
                state=state,
                city=city,
                neighborhood=neighborhood,
                street=current_street
            )

            db.session.add(blocked)
            created.append(current_street)

        db.session.commit()

        return jsonify({
            "message": "Localidades bloqueadas com sucesso",
            "total": len(created),
            "streets": created
        }), 201

    existing = BlockedLocation.query.filter_by(
        state=state,
        city=city,
        neighborhood=neighborhood,
        street=street
    ).first()

    if existing:
        return jsonify({"message": "Essa localidade já está bloqueada"}), 409

    blocked = BlockedLocation(
        state=state,
        city=city,
        neighborhood=neighborhood,
        street=street
    )

    db.session.add(blocked)
    db.session.commit()

    return jsonify({"message": "Localidade bloqueada com sucesso"}), 201   
    
@app.route("/admin/blocked-locations", methods=["GET"])
def admin_list_blocked_locations():
    admin_user_id = request.args.get("user_id", type=int)

    if not admin_user_id:
        return jsonify({"message": "Administrador não informado"}), 400

    admin_user = User.query.get(admin_user_id)
    if not admin_user or not admin_user.is_admin:
        return jsonify({"message": "Acesso negado"}), 403

    items = BlockedLocation.query.order_by(
        BlockedLocation.state.asc(),
        BlockedLocation.city.asc(),
        BlockedLocation.neighborhood.asc(),
        BlockedLocation.street.asc()
    ).all()

    return jsonify([
        {
            "id": item.id,
            "state": item.state,
            "city": item.city,
            "neighborhood": item.neighborhood,
            "street": item.street,
            "created_at": item.created_at.isoformat() if item.created_at else None
        }
        for item in items
    ])
    
@app.route("/admin/blocked-locations/<int:block_id>", methods=["DELETE"])
def admin_delete_blocked_location(block_id):
    data = request.get_json() or {}

    admin_user_id = data.get("admin_user_id")
    if not admin_user_id:
        return jsonify({"message": "Administrador não informado"}), 400

    admin_user = User.query.get(admin_user_id)
    if not admin_user or not admin_user.is_admin:
        return jsonify({"message": "Acesso negado"}), 403

    blocked = BlockedLocation.query.get(block_id)
    if not blocked:
        return jsonify({"message": "Bloqueio não encontrado"}), 404

    db.session.delete(blocked)
    db.session.commit()

    return jsonify({"message": "Bloqueio removido com sucesso"})    


@app.route("/ibge-test", methods=["GET"])
def ibge_test():
    try:
        data = fetch_ibge_json("https://servicodados.ibge.gov.br/api/v1/localidades/estados?orderBy=nome")
        return jsonify({
            "ok": True,
            "total": len(data),
            "primeiro": data[0] if data else None
        })
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500
        
@app.route("/admin/locations-page")
@admin_required_page
def admin_locations_page():
    return render_template("locations.html", active_page="locations") 

@app.route("/admin/locations", methods=["GET"])
def admin_list_locations():
    admin_user_id = request.args.get("user_id", type=int)

    if not admin_user_id:
        return jsonify({"message": "Administrador não informado"}), 400

    admin_user = User.query.get(admin_user_id)
    if not admin_user or not admin_user.is_admin:
        return jsonify({"message": "Acesso negado"}), 403

    query = ManagedLocation.query

    state = (request.args.get("state") or "").strip().upper()
    city = (request.args.get("city") or "").strip()
    neighborhood = (request.args.get("neighborhood") or "").strip()
    street = (request.args.get("street") or "").strip()

    if state:
        query = query.filter(ManagedLocation.state == state)

    if city:
        query = query.filter(ManagedLocation.city.ilike(f"%{city}%"))

    if neighborhood:
        query = query.filter(ManagedLocation.neighborhood.ilike(f"%{neighborhood}%"))

    if street:
        query = query.filter(ManagedLocation.street.ilike(f"%{street}%"))

    items = query.order_by(
        ManagedLocation.state.asc(),
        ManagedLocation.city.asc(),
        ManagedLocation.neighborhood.asc(),
        ManagedLocation.street.asc()
    ).all()

    return jsonify([serialize_managed_location(item) for item in items])


@app.route("/admin/locations", methods=["POST"])
def admin_create_location():
    data = request.get_json() or {}

    admin_user_id = data.get("admin_user_id")

    if not admin_user_id:
        return jsonify({"message": "Administrador não informado"}), 400

    admin_user = User.query.get(admin_user_id)
    if not admin_user or not admin_user.is_admin:
        return jsonify({"message": "Acesso negado"}), 403

    state = (data.get("state") or "").strip().upper()
    city = (data.get("city") or "").strip()
    neighborhood = (data.get("neighborhood") or "").strip() or None
    street = (data.get("street") or "").strip() or None

    if not state:
        return jsonify({"message": "Informe o estado"}), 400

    if not city:
        return jsonify({"message": "Informe a cidade"}), 400

    existing = ManagedLocation.query.filter_by(
        state=state,
        city=city,
        neighborhood=neighborhood,
        street=street
    ).first()

    if existing:
        return jsonify({
            "message": "Essa localidade já está cadastrada",
            "location": serialize_managed_location(existing)
        }), 409

    location = ManagedLocation(
        state=state,
        city=city,
        neighborhood=neighborhood,
        street=street
    )

    db.session.add(location)
    db.session.commit()

    return jsonify({
        "message": "Localidade cadastrada com sucesso",
        "location": serialize_managed_location(location)
    }), 201


@app.route("/admin/locations/<int:location_id>", methods=["DELETE"])
def admin_delete_location(location_id):
    data = request.get_json() or {}

    admin_user_id = data.get("admin_user_id")

    if not admin_user_id:
        return jsonify({"message": "Administrador não informado"}), 400

    admin_user = User.query.get(admin_user_id)
    if not admin_user or not admin_user.is_admin:
        return jsonify({"message": "Acesso negado"}), 403

    location = ManagedLocation.query.get(location_id)

    if not location:
        return jsonify({"message": "Localidade não encontrada"}), 404

    db.session.delete(location)
    db.session.commit()

    return jsonify({"message": "Localidade excluída com sucesso"})    

# =========================
# SEED INICIAL OPCIONAL
# =========================

@app.route("/seed", methods=["POST"])
def seed_data():
    if Ad.query.first() or User.query.first():
        return jsonify({"message": "Banco já possui dados"}), 400

    user_vip = User(
        name="Usuário VIP",
        email="vip@teste.com",
        phone="(61) 99999-1111",
        password_hash=generate_password_hash("123456"),
        plan="VIP_BRONZE"
    )

    user_free = User(
        name="Usuário Free",
        email="free@teste.com",
        phone="(61) 98888-2222",
        password_hash=generate_password_hash("123456"),
        plan="FREE"
    )

    db.session.add(user_vip)
    db.session.add(user_free)
    db.session.flush()

    ad1 = Ad(
        user_id=user_vip.id,
        title="Clínica Sorriso Total",
        description="Atendimento odontológico especializado",
        phone="(61) 99999-1111",
        country="Brasil",
        state="DF",
        city="Ceilândia",
        municipality="Ceilândia",
        neighborhood="Centro",
        street="QNN 01",
        number="10",
        zipcode="72225-010",
        plan="VIP_BRONZE",
        main_image=None
    )
    ad1.keywords = [
        Keyword(keyword="dentista"),
        Keyword(keyword="odontologia"),
        Keyword(keyword="clinica")
    ]

    ad2 = Ad(
        user_id=user_free.id,
        title="Mecânico do João",
        description="Serviços automotivos em geral",
        phone="(61) 98888-2222",
        country="Brasil",
        state="DF",
        city="Taguatinga",
        municipality="Taguatinga",
        neighborhood="Sul",
        street="QSB 02",
        number="25",
        zipcode="72015-020",
        plan="FREE"
    )
    ad2.keywords = [
        Keyword(keyword="mecanico"),
        Keyword(keyword="carro"),
        Keyword(keyword="oficina")
    ]

    db.session.add(ad1)
    db.session.add(ad2)
    db.session.commit()

    return jsonify({"message": "Dados iniciais criados com sucesso"})


@app.route("/ads/<int:ad_id>", methods=["GET"])
def get_ad(ad_id):
    ad = Ad.query.get(ad_id)

    if not ad or not ad.is_active:
        return jsonify({"message": "Anúncio não encontrado"}), 404

    current_user = None
    if session.get("user_id"):
        current_user = User.query.get(session["user_id"])

    if not get_plan_rules(ad.plan)["can_show_full_details"]:
        if not current_user or not current_user.is_admin:
            return jsonify({"message": "Detalhes disponíveis apenas para anúncios com plano compatível"}), 403

    return jsonify(serialize_ad(ad))


@app.route("/ads/<int:ad_id>/page")
def ad_details_page(ad_id):
    ad = Ad.query.get(ad_id)

    if not ad or not ad.is_active:
        return "Anúncio não encontrado", 404

    current_user = None
    if session.get("user_id"):
        current_user = User.query.get(session["user_id"])

    if not get_plan_rules(ad.plan)["can_show_full_details"]:
        if not current_user or not current_user.is_admin:
            return "Detalhes disponíveis apenas para anúncios com plano compatível", 403

    origin = request.args.get("from", "search")

    return render_template("ad_details.html", ad_id=ad_id, origin=origin)


@app.route("/create-ad-page")
@login_required_page
def create_ad_page():
    return render_template("create_ad.html")
    
@app.route("/profile-page")
@login_required_page
def profile_page():
    return render_template("profile.html")  


@app.route("/ads", methods=["POST"])
def create_ad():
    if not session.get("user_id"):
        return jsonify({"message": "Faça login para cadastrar um anúncio."}), 401
        
    user_id = request.form.get("user_id")
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    phone = request.form.get("phone", "").strip()
    country = request.form.get("country", "Brasil").strip()
    state = request.form.get("state", "").strip()
    city = request.form.get("city", "").strip()
    municipality = request.form.get("municipality", "").strip()
    neighborhood = request.form.get("neighborhood", "").strip()
    street = request.form.get("street", "").strip()
    number = request.form.get("number", "").strip()
    complement = request.form.get("complement", "").strip()
    zipcode = request.form.get("zipcode", "").strip()

    keywords = request.form.getlist("keywords")

    main_image_file = request.files.get("main_image")
    main_video_file = request.files.get("main_video")

    if state.upper() == "DF" and city and not municipality:
        municipality = city

    
    if not user_id:
        return jsonify({"message": "Usuário não informado"}), 400
        
    if int(user_id) != int(session["user_id"]):
        return jsonify({"message": "Acesso negado"}), 403    

    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "Usuário não encontrado"}), 404
    
    enforce_user_plan(user)
    
    plan_rules = get_plan_rules(user.plan)

    if (main_image_file and not plan_rules["can_use_images"]) or (main_video_file and not plan_rules["can_use_videos"]):
        return jsonify({
            "message": "Seu plano atual não permite usar imagem e/ou vídeo neste anúncio.",
            "upgrade": True
        }), 403

    plan_rules = get_plan_rules(user.plan)
    max_ads = plan_rules["ads_limit"]
    current_ads_count = Ad.query.filter_by(user_id=user.id).count()

    if current_ads_count >= max_ads:
        if user.plan == "FREE":
            return jsonify({
                "message": "Torne-se VIP para anunciar mais produtos ou serviços",
                "upgrade": True
            }), 400

        return jsonify({
            "message": "Você atingiu o limite de 5 anúncios VIP"
        }), 400

    if not title or not state or not city:
        return jsonify({"message": "Preencha os campos obrigatórios"}), 400

    max_keywords = plan_rules["keywords_limit"]
    cleaned_keywords = normalize_keywords(keywords)

    if len(cleaned_keywords) > max_keywords:
        return jsonify({
            "message": f"Usuário {user.plan} pode cadastrar até {max_keywords} palavras-chave"
        }), 400
        
    image_path = None
    video_path = None

    if main_image_file and main_image_file.filename:
        if not allowed_file(main_image_file.filename, ALLOWED_IMAGE_EXTENSIONS):
            return jsonify({"message": "Formato de imagem inválido."}), 400

        image_ext = main_image_file.filename.rsplit(".", 1)[1].lower()
        image_filename = f"{uuid.uuid4().hex}.{image_ext}"
        image_full_path = os.path.join(UPLOAD_IMAGE_FOLDER, image_filename)
        main_image_file.save(image_full_path)
        image_path = f"/static/uploads/images/{image_filename}"

    if main_video_file and main_video_file.filename:
        if not allowed_file(main_video_file.filename, ALLOWED_VIDEO_EXTENSIONS):
            return jsonify({"message": "Formato de vídeo inválido."}), 400

        video_ext = main_video_file.filename.rsplit(".", 1)[1].lower()
        video_filename = f"{uuid.uuid4().hex}.{video_ext}"
        video_full_path = os.path.join(UPLOAD_VIDEO_FOLDER, video_filename)
        main_video_file.save(video_full_path)

        duration_seconds = get_video_duration(video_full_path)

        if duration_seconds is None:
            os.remove(video_full_path)
            return jsonify({"message": "Não foi possível validar a duração do vídeo."}), 400

        if duration_seconds > 60:
            os.remove(video_full_path)
            return jsonify({
                "message": "O vídeo deve ter no máximo 1 minuto."
            }), 400

        video_path = f"/static/uploads/videos/{video_filename}"    

    ad = Ad(
        user_id=user.id,
        title=title,
        description=description,
        phone=phone,
        country=country,
        state=state,
        city=city,
        municipality=municipality,
        neighborhood=neighborhood,
        street=street,
        number=number,
        complement=complement,
        zipcode=zipcode,
        plan=user.plan,
        main_image=image_path if plan_rules["can_use_images"] else None,
        main_video=video_path if plan_rules["can_use_videos"] else None,
        is_active=True
    )

    db.session.add(ad)
    db.session.flush()

    for keyword in cleaned_keywords:
        db.session.add(Keyword(ad_id=ad.id, keyword=keyword))

    db.session.commit()

    return jsonify({
        "message": "Anúncio cadastrado com sucesso",
        "ad": serialize_ad(ad)
    }), 201

@app.route("/vitrine-page")
def vitrine_page():
    return render_template("vitrine.html")
    
@app.route("/vitrine-ads", methods=["GET"])
def vitrine_ads():
    allowed_plans = [
        plan for plan in ["FREE", "VIP_BRONZE", "VIP_PRATA", "VIP_OURO", "VIP_PREMIUM"]
        if get_plan_rules(plan)["can_use_vitrine"]
    ]

    ads = Ad.query.join(User, Ad.user_id == User.id).filter(
        Ad.is_active == True,
        Ad.main_image.isnot(None),
        Ad.plan.in_(allowed_plans),
        or_(Ad.blocked_until.is_(None), Ad.blocked_until <= utc_now()),
        or_(User.blocked_until.is_(None), User.blocked_until <= utc_now())
    ).order_by(
        plan_priority_case(),
        Ad.created_at.desc()
    ).limit(100).all()

    return jsonify([serialize_ad(ad) for ad in ads])

@app.route("/my-ads/<int:user_id>", methods=["GET"])
def get_my_ads(user_id):
    user = User.query.get(user_id)
    
    if not session.get("user_id"):
        return jsonify({"message": "Faça login para ver seus anúncios."}), 401

    if int(user_id) != int(session["user_id"]):
        return jsonify({"message": "Acesso negado"}), 403

    if not user:
        return jsonify({"message": "Usuário não encontrado"}), 404
        
    enforce_user_plan(user)
    sync_user_ads_with_plan(user)
    db.session.commit()

    ads = Ad.query.filter_by(user_id=user_id).order_by(Ad.created_at.desc()).all()

    return jsonify([serialize_ad(ad) for ad in ads])


@app.route("/vip-page")
def vip_page():
    return render_template("vip.html")
    
@app.route("/plans-config", methods=["GET"])
def get_plans_config():
    return jsonify({
        "free": get_plan_rules("FREE"),
        "bronze": get_plan_rules("VIP_BRONZE"),
        "prata": get_plan_rules("VIP_PRATA"),
        "ouro": get_plan_rules("VIP_OURO"),
        "premium": get_plan_rules("VIP_PREMIUM")
    })    

@app.route("/public/support-whatsapp", methods=["GET"])
def public_support_whatsapp():
    settings = get_app_settings()

    return jsonify({
        "support_whatsapp": settings.support_whatsapp or ""
    }), 200
    
@app.route("/manifest.webmanifest")
def manifest():
    return send_from_directory("static", "manifest.webmanifest", mimetype="application/manifest+json")

@app.route("/service-worker.js")
def service_worker():
    return send_from_directory("static", "service-worker.js", mimetype="application/javascript")    
    
@app.route("/upgrade-vip/<int:user_id>", methods=["PATCH"])
def upgrade_vip(user_id):
    user = User.query.get(user_id)
    
    if not session.get("user_id"):
        return jsonify({"message": "Faça login para alterar seu plano VIP."}), 401

    if int(user_id) != int(session["user_id"]):
        return jsonify({"message": "Acesso negado"}), 403

    if not user:
        return jsonify({"message": "Usuário não encontrado"}), 404

    data = request.get_json() or {}
    target_plan = (data.get("plan") or "").strip().upper()

    if target_plan not in VIP_PLANS:
        return jsonify({"message": "Plano VIP inválido"}), 400

    now = utc_now()

    if user.plan == target_plan and user.vip_expires_at and user.vip_expires_at > now:
        return jsonify({
            "message": f"Usuário já possui o plano {get_plan_label(target_plan)} ativo",
            "user": serialize_user(user)
        })

    user.plan = target_plan
    user.vip_expires_at = now + timedelta(days=30)

    sync_user_ads_with_plan(user, target_plan)

    db.session.commit()

    return jsonify({
        "message": f"Upgrade para {get_plan_label(target_plan)} realizado com sucesso",
        "user": serialize_user(user)
    })
    
@app.route("/admin/settings", methods=["GET"])
def get_admin_settings():
    admin_user_id = request.args.get("user_id", type=int)

    if not admin_user_id:
        return jsonify({"message": "Administrador não informado"}), 400

    admin_user = User.query.get(admin_user_id)
    if not admin_user or not admin_user.is_admin:
        return jsonify({"message": "Acesso negado"}), 403

    settings = get_app_settings()

    return jsonify({
        "support_whatsapp": settings.support_whatsapp or "",
        "free": {
            "ads_limit": settings.free_ads_limit,
            "keywords_limit": settings.free_keywords_limit,
            "can_use_images": settings.free_can_use_images,
            "can_use_videos": settings.free_can_use_videos,
            "can_appear_in_vip_list": settings.free_can_appear_in_vip_list,
            "can_show_full_details": settings.free_can_show_full_details,
            "can_use_vitrine": settings.free_can_use_vitrine
        },
        "bronze": {
            "ads_limit": settings.bronze_ads_limit,
            "keywords_limit": settings.bronze_keywords_limit,
            "price": settings.bronze_price,
            "can_use_images": settings.bronze_can_use_images,
            "can_use_videos": settings.bronze_can_use_videos,
            "can_appear_in_vip_list": settings.bronze_can_appear_in_vip_list,
            "can_show_full_details": settings.bronze_can_show_full_details,
            "can_use_vitrine": settings.bronze_can_use_vitrine
        },
        "prata": {
            "ads_limit": settings.prata_ads_limit,
            "keywords_limit": settings.prata_keywords_limit,
            "price": settings.prata_price,
            "can_use_images": settings.prata_can_use_images,
            "can_use_videos": settings.prata_can_use_videos,
            "can_appear_in_vip_list": settings.prata_can_appear_in_vip_list,
            "can_show_full_details": settings.prata_can_show_full_details,
            "can_use_vitrine": settings.prata_can_use_vitrine
        },
        "ouro": {
            "ads_limit": settings.ouro_ads_limit,
            "keywords_limit": settings.ouro_keywords_limit,
            "price": settings.ouro_price,
            "can_use_images": settings.ouro_can_use_images,
            "can_use_videos": settings.ouro_can_use_videos,
            "can_appear_in_vip_list": settings.ouro_can_appear_in_vip_list,
            "can_show_full_details": settings.ouro_can_show_full_details,
            "can_use_vitrine": settings.ouro_can_use_vitrine
        },
        "premium": {
            "ads_limit": settings.premium_ads_limit,
            "keywords_limit": settings.premium_keywords_limit,
            "price": settings.premium_price,
            "can_use_images": settings.premium_can_use_images,
            "can_use_videos": settings.premium_can_use_videos,
            "can_appear_in_vip_list": settings.premium_can_appear_in_vip_list,
            "can_show_full_details": settings.premium_can_show_full_details,
            "can_use_vitrine": settings.premium_can_use_vitrine
        }
    })
    
@app.route("/admin/settings", methods=["PATCH"])
def update_admin_settings():
    data = request.get_json() or {}

    admin_user_id = data.get("admin_user_id")

    if not admin_user_id:
        return jsonify({"message": "Administrador não informado"}), 400

    admin_user = User.query.get(admin_user_id)
    if not admin_user or not admin_user.is_admin:
        return jsonify({"message": "Acesso negado"}), 403

    settings = get_app_settings()

    try:
        settings.support_whatsapp = (data.get("support_whatsapp") or "").strip()
        
        settings.free_ads_limit = int(data["free"]["ads_limit"])
        settings.free_keywords_limit = int(data["free"]["keywords_limit"])
        settings.free_can_use_images = bool(data["free"]["can_use_images"])
        settings.free_can_use_videos = bool(data["free"]["can_use_videos"])
        settings.free_can_appear_in_vip_list = bool(data["free"]["can_appear_in_vip_list"])
        settings.free_can_show_full_details = bool(data["free"]["can_show_full_details"])
        settings.free_can_use_vitrine = bool(data["free"]["can_use_vitrine"])

        settings.bronze_ads_limit = int(data["bronze"]["ads_limit"])
        settings.bronze_keywords_limit = int(data["bronze"]["keywords_limit"])
        settings.bronze_can_use_images = bool(data["bronze"]["can_use_images"])
        settings.bronze_can_use_videos = bool(data["bronze"]["can_use_videos"])
        settings.bronze_can_appear_in_vip_list = bool(data["bronze"]["can_appear_in_vip_list"])
        settings.bronze_can_show_full_details = bool(data["bronze"]["can_show_full_details"])
        settings.bronze_price = float(data["bronze"]["price"])
        settings.bronze_can_use_vitrine = bool(data["bronze"]["can_use_vitrine"])

        settings.prata_ads_limit = int(data["prata"]["ads_limit"])
        settings.prata_keywords_limit = int(data["prata"]["keywords_limit"])
        settings.prata_can_use_images = bool(data["prata"]["can_use_images"])
        settings.prata_can_use_videos = bool(data["prata"]["can_use_videos"])
        settings.prata_can_appear_in_vip_list = bool(data["prata"]["can_appear_in_vip_list"])
        settings.prata_can_show_full_details = bool(data["prata"]["can_show_full_details"])
        settings.prata_price = float(data["prata"]["price"])
        settings.prata_can_use_vitrine = bool(data["prata"]["can_use_vitrine"])

        settings.ouro_ads_limit = int(data["ouro"]["ads_limit"])
        settings.ouro_keywords_limit = int(data["ouro"]["keywords_limit"])
        settings.ouro_can_use_images = bool(data["ouro"]["can_use_images"])
        settings.ouro_can_use_videos = bool(data["ouro"]["can_use_videos"])
        settings.ouro_can_appear_in_vip_list = bool(data["ouro"]["can_appear_in_vip_list"])
        settings.ouro_can_show_full_details = bool(data["ouro"]["can_show_full_details"])
        settings.ouro_price = float(data["ouro"]["price"])
        settings.ouro_can_use_vitrine = bool(data["ouro"]["can_use_vitrine"])

        settings.premium_ads_limit = int(data["premium"]["ads_limit"])
        settings.premium_keywords_limit = int(data["premium"]["keywords_limit"])
        settings.premium_can_use_images = bool(data["premium"]["can_use_images"])
        settings.premium_can_use_videos = bool(data["premium"]["can_use_videos"])
        settings.premium_can_appear_in_vip_list = bool(data["premium"]["can_appear_in_vip_list"])
        settings.premium_can_show_full_details = bool(data["premium"]["can_show_full_details"])
        settings.premium_price = float(data["premium"]["price"])
        settings.premium_can_use_vitrine = bool(data["premium"]["can_use_vitrine"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"message": "Valores inválidos"}), 400

    db.session.commit()

    all_users = User.query.all()

    for user in all_users:
        if is_vip_plan(user.plan):
            if not user.vip_expires_at or user.vip_expires_at <= utc_now():
                user.plan = "FREE"
                user.vip_expires_at = None

        sync_user_ads_with_plan(user)

    db.session.commit()

    return jsonify({"message": "Ajustes atualizados com sucesso"})
    
@app.route("/admin/dashboard-page")
@admin_required_page
def admin_dashboard_page():
    return render_template("dashboard.html", active_page="dashboard")   
    
@app.route("/admin/settings-page")
@admin_required_page
def admin_settings_page():
    return render_template("settings.html", active_page="settings")  


@app.route("/ads-page")
@login_required_page
def ads_page():
    return render_template("ads.html")
    
@app.route("/feed-page")
def feed_page():
    return render_template("feed.html")


@app.route("/feed", methods=["GET"])
def get_feed():
    ads = Ad.query.join(User, Ad.user_id == User.id).filter(
        Ad.is_active == True,
        or_(Ad.main_image.isnot(None), Ad.main_video.isnot(None)),
        or_(Ad.blocked_until.is_(None), Ad.blocked_until <= utc_now()),
        or_(User.blocked_until.is_(None), User.blocked_until <= utc_now())
    ).order_by(
        plan_priority_case(),
        Ad.created_at.desc()
    ).all()

    feed_items = []

    for ad in ads:
        plan_rules = get_plan_rules(ad.plan)

        if not plan_rules.get("can_use_vitrine", False):
            continue

        if plan_rules.get("can_use_images", False) and ad.main_image:
            feed_items.append({
                "ad_id": ad.id,
                "title": ad.title,
                "type": "image",
                "url": ad.main_image,
                "plan": ad.plan,
                "created_at": ad.created_at.isoformat() if ad.created_at else None
            })

        if plan_rules.get("can_use_videos", False) and ad.main_video:
            feed_items.append({
                "ad_id": ad.id,
                "title": ad.title,
                "type": "video",
                "url": ad.main_video,
                "plan": ad.plan,
                "created_at": ad.created_at.isoformat() if ad.created_at else None
            })

    return jsonify(feed_items) 


@app.route("/ads", methods=["GET"])
def list_vip_ads():
    country = request.args.get("country")
    state = request.args.get("state")
    city = request.args.get("city")
    municipality = request.args.get("municipality")
    neighborhood = request.args.get("neighborhood")

    # ✔️ define fora do filter
    allowed_plans = [
        plan for plan in ["FREE", "VIP_BRONZE", "VIP_PRATA", "VIP_OURO", "VIP_PREMIUM"]
        if get_plan_rules(plan)["can_appear_in_vip_list"]
    ]

    query = Ad.query.join(User, Ad.user_id == User.id).filter(
        Ad.plan.in_(allowed_plans),
        Ad.is_active == True,
        or_(Ad.blocked_until.is_(None), Ad.blocked_until <= utc_now()),
        or_(User.blocked_until.is_(None), User.blocked_until <= utc_now())
    )

    if country:
        query = query.filter(Ad.country == country)

    if state:
        query = query.filter(Ad.state == state)

    if city:
        query = query.filter(Ad.city == city)

    if municipality:
        query = query.filter(Ad.municipality == municipality)

    if neighborhood:
        query = query.filter(Ad.neighborhood == neighborhood)

    ads = query.order_by(Ad.created_at.desc()).all()

    return jsonify([serialize_ad(ad) for ad in ads])


@app.route("/ads/<int:ad_id>", methods=["DELETE"])
def delete_ad(ad_id):
    data = request.get_json() or {}
    user_id = data.get("user_id")

    if not user_id:
        return jsonify({"message": "Usuário não informado"}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "Usuário não encontrado"}), 404

    ad = Ad.query.get(ad_id)
    if not ad:
        return jsonify({"message": "Anúncio não encontrado"}), 404

    if ad.user_id != user.id:
        return jsonify({"message": "Você não tem permissão para excluir este anúncio"}), 403
        
    if ad.main_image:
        old_image_path = resolve_media_file_path(ad.main_image)
        if old_image_path and os.path.exists(old_image_path):
            try:
                os.remove(old_image_path)
            except Exception as e:
                print(f"Erro ao remover imagem antiga do anúncio {ad.id}: {e}", flush=True)

    if ad.main_video:
        old_video_path = resolve_media_file_path(ad.main_video)
        if old_video_path and os.path.exists(old_video_path):
            try:
                os.remove(old_video_path)
            except Exception as e:
                print(f"Erro ao remover vídeo antigo do anúncio {ad.id}: {e}", flush=True)
            
    db.session.delete(ad)
    db.session.commit()

    return jsonify({"message": "Anúncio excluído com sucesso"})


@app.route("/ads/<int:ad_id>", methods=["PUT"])
def update_ad(ad_id):
    user_id = request.form.get("user_id")

    if not user_id:
        return jsonify({"message": "Usuário não informado"}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "Usuário não encontrado"}), 404

    ad = Ad.query.get(ad_id)
    if not ad:
        return jsonify({"message": "Anúncio não encontrado"}), 404

    if ad.user_id != user.id:
        return jsonify({"message": "Você não tem permissão para editar este anúncio"}), 403

    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    phone = request.form.get("phone", "").strip()
    country = request.form.get("country", "Brasil").strip()
    state = request.form.get("state", "").strip()
    city = request.form.get("city", "").strip()
    neighborhood = request.form.get("neighborhood", "").strip()
    street = request.form.get("street", "").strip()
    number = request.form.get("number", "").strip()
    complement = request.form.get("complement", "").strip()
    zipcode = request.form.get("zipcode", "").strip()
    keywords = request.form.getlist("keywords")

    main_image_file = request.files.get("main_image")
    main_video_file = request.files.get("main_video")

    enforce_user_plan(user)
    plan_rules = get_plan_rules(user.plan)

    if (main_image_file and not plan_rules["can_use_images"]) or (main_video_file and not plan_rules["can_use_videos"]):
        return jsonify({
            "message": "Seu plano atual não permite usar imagem e/ou vídeo neste anúncio.",
            "upgrade": True
        }), 403

    if not title or not state or not city:
        return jsonify({"message": "Preencha os campos obrigatórios"}), 400

    max_keywords = plan_rules["keywords_limit"]
    cleaned_keywords = normalize_keywords(keywords)

    if len(cleaned_keywords) > max_keywords:
        return jsonify({
            "message": f"Usuário {user.plan} pode cadastrar até {max_keywords} palavras-chave"
        }), 400

    if main_image_file and main_image_file.filename:
        if not allowed_file(main_image_file.filename, ALLOWED_IMAGE_EXTENSIONS):
            return jsonify({"message": "Formato de imagem inválido."}), 400

        if ad.main_image:
            old_image_path = resolve_media_file_path(ad.main_image)
            if old_image_path and os.path.exists(old_image_path):
                try:
                    os.remove(old_image_path)
                except Exception as e:
                    print(f"Erro ao remover imagem antiga do anúncio {ad.id}: {e}", flush=True)

        image_ext = main_image_file.filename.rsplit(".", 1)[1].lower()
        image_filename = f"{uuid.uuid4().hex}.{image_ext}"
        image_full_path = os.path.join(UPLOAD_IMAGE_FOLDER, image_filename)
        main_image_file.save(image_full_path)

        ad.main_image = f"/static/uploads/images/{image_filename}"

    elif not plan_rules["can_use_images"]:
        ad.main_image = None

    if main_video_file and main_video_file.filename:
        if not allowed_file(main_video_file.filename, ALLOWED_VIDEO_EXTENSIONS):
            return jsonify({"message": "Formato de vídeo inválido."}), 400

        if ad.main_video:
            old_video_path = ad.main_video.lstrip("/")
            if os.path.exists(old_video_path):
                os.remove(old_video_path)

        video_ext = main_video_file.filename.rsplit(".", 1)[1].lower()
        video_filename = f"{uuid.uuid4().hex}.{video_ext}"
        video_full_path = os.path.join(UPLOAD_VIDEO_FOLDER, video_filename)
        main_video_file.save(video_full_path)

        duration_seconds = get_video_duration(video_full_path)

        if duration_seconds is None:
            os.remove(video_full_path)
            return jsonify({"message": "Não foi possível validar a duração do vídeo."}), 400

        if duration_seconds > 60:
            os.remove(video_full_path)
            return jsonify({"message": "O vídeo deve ter no máximo 1 minuto."}), 400

        ad.main_video = f"/static/uploads/videos/{video_filename}"

    elif not plan_rules["can_use_videos"]:
        ad.main_video = None

    ad.title = title
    ad.description = description
    ad.phone = phone
    ad.country = country
    ad.state = state
    ad.city = city
    ad.municipality = city if state.upper() == "DF" else request.form.get("municipality", "").strip()
    ad.neighborhood = neighborhood
    ad.street = street
    ad.number = number
    ad.complement = complement
    ad.zipcode = zipcode
    ad.plan = user.plan

    Keyword.query.filter_by(ad_id=ad.id).delete()

    for keyword in cleaned_keywords:
        db.session.add(Keyword(ad_id=ad.id, keyword=keyword))

    db.session.commit()

    return jsonify({
        "message": "Anúncio atualizado com sucesso",
        "ad": serialize_ad(ad)
    })
    
@app.errorhandler(413)
def file_too_large(error):
    return jsonify({
        "message": "O vídeo deve ter no máximo 1 minuto e tamanho compatível."
    }), 413 

@app.route("/reports", methods=["POST"])
def create_report():
    data = request.get_json() or {}

    ad_id = data.get("ad_id")
    reporter_message = (data.get("reason") or "").strip()
    
    if not session.get("user_id"):
        return jsonify({"message": "Faça login para denunciar um anúncio."}), 401

    if not ad_id:
        return jsonify({"message": "Anúncio não informado"}), 400

    if not reporter_message:
        return jsonify({"message": "Informe o motivo da denúncia"}), 400

    ad = Ad.query.get(ad_id)
    if not ad:
        return jsonify({"message": "Anúncio não encontrado"}), 404

    report = Report(
        ad_id=ad.id,
        reported_user_id=ad.user_id,
        reporter_message=reporter_message,
        status="OPEN"
    )

    db.session.add(report)
    db.session.flush()

    total_reports = Report.query.filter_by(ad_id=ad.id).count()

    if total_reports >= 50 and (not ad.blocked_until or ad.blocked_until <= utc_now()):
        ad.blocked_until = utc_now() + timedelta(days=30)

    db.session.commit()

    return jsonify({
        "message": "Denúncia enviada com sucesso",
        "report": serialize_report(report)
    }), 201
    
@app.route("/admin/reports-page")
@admin_required_page
def admin_reports_page():
    return render_template("admin_reports.html", active_page="reports")   
    
@app.route("/admin/reports", methods=["GET"])
def list_admin_reports():
    admin_user_id = request.args.get("user_id", type=int)
    status = (request.args.get("status") or "OPEN").strip().upper()

    if not admin_user_id:
        return jsonify({"message": "Usuário administrador não informado"}), 400

    admin_user = User.query.get(admin_user_id)
    if not admin_user or not admin_user.is_admin:
        return jsonify({"message": "Acesso negado"}), 403

    query = Report.query

    if status in ["OPEN", "RESOLVED"]:
        query = query.filter_by(status=status)

    reports = query.order_by(Report.created_at.desc()).all()

    return jsonify([serialize_report(report) for report in reports])  
    
@app.route("/admin/reports/<int:report_id>/resolve", methods=["PATCH"])
def resolve_report(report_id):
    data = request.get_json() or {}

    admin_user_id = data.get("admin_user_id")

    if not admin_user_id:
        return jsonify({"message": "Administrador não informado"}), 400

    admin_user = User.query.get(admin_user_id)
    if not admin_user or not admin_user.is_admin:
        return jsonify({"message": "Acesso negado"}), 403

    report = Report.query.get(report_id)
    if not report:
        return jsonify({"message": "Denúncia não encontrada"}), 404

    report.status = "RESOLVED"
    report.action_taken = "ONLY_RESOLVED"
    report.action_days = None
    report.reviewed_at = utc_now()
    report.reviewed_by_admin_id = admin_user.id

    db.session.commit()

    return jsonify({
        "message": "Denúncia concluída com sucesso",
        "report": serialize_report(report)
    })    
    
@app.route("/admin/reports-history-page")
@admin_required_page
def admin_reports_history_page():
    return render_template("admin_reports_history.html", active_page="reports_history")   
    
@app.route("/admin/users/<int:target_user_id>/block", methods=["PATCH"])
def block_user(target_user_id):
    data = request.get_json() or {}

    admin_user_id = data.get("admin_user_id")
    days = data.get("days")
    report_id = data.get("report_id")

    if not admin_user_id:
        return jsonify({"message": "Administrador não informado"}), 400

    admin_user = User.query.get(admin_user_id)
    if not admin_user or not admin_user.is_admin:
        return jsonify({"message": "Acesso negado"}), 403

    try:
        days = int(days)
    except (TypeError, ValueError):
        return jsonify({"message": "Quantidade de dias inválida"}), 400

    if days <= 0:
        return jsonify({"message": "Informe uma quantidade de dias maior que zero"}), 400

    target_user = User.query.get(target_user_id)
    if not target_user:
        return jsonify({"message": "Usuário não encontrado"}), 404
    
    if target_user.is_admin:
        return jsonify({"message": "Não é permitido bloquear administrador"}), 400

    target_user.blocked_until = utc_now() + timedelta(days=days)

    if report_id:
        report = Report.query.get(report_id)
        if report:
            report.status = "RESOLVED"
            report.action_taken = "USER_BLOCKED"
            report.action_days = days
            report.reviewed_at = utc_now()
            report.reviewed_by_admin_id = admin_user.id

    db.session.commit()

    return jsonify({
        "message": f"Usuário bloqueado por {days} dia(s) com sucesso",
        "user": serialize_user(target_user)
    })  

@app.route("/admin/users/<int:target_user_id>/unblock", methods=["PATCH"])
def unblock_user(target_user_id):
    data = request.get_json() or {}

    admin_user_id = data.get("admin_user_id")

    if not admin_user_id:
        return jsonify({"message": "Administrador não informado"}), 400

    admin_user = User.query.get(admin_user_id)
    if not admin_user or not admin_user.is_admin:
        return jsonify({"message": "Acesso negado"}), 403

    target_user = User.query.get(target_user_id)
    if not target_user:
        return jsonify({"message": "Usuário não encontrado"}), 404
    
    if target_user.is_admin:
        return jsonify({"message": "Não é permitido desbloquear administrador"}), 400

    target_user.blocked_until = None

    db.session.commit()

    return jsonify({
        "message": "Usuário desbloqueado com sucesso",
        "user": serialize_user(target_user)
    }) 
    
@app.route("/admin/users/<int:target_user_id>/plan", methods=["PATCH"])
def update_user_plan(target_user_id):
    data = request.get_json() or {}

    admin_user_id = data.get("admin_user_id")
    new_plan = (data.get("plan") or "").strip().upper()
    vip_expires_at = (data.get("vip_expires_at") or "").strip()

    if not admin_user_id:
        return jsonify({"message": "Administrador não informado"}), 400

    admin_user = User.query.get(admin_user_id)
    if not admin_user or not admin_user.is_admin:
        return jsonify({"message": "Acesso negado"}), 403

    allowed_plans = ["FREE", "VIP_BRONZE", "VIP_PRATA", "VIP_OURO", "VIP_PREMIUM"]
    if new_plan not in allowed_plans:
        return jsonify({"message": "Plano inválido"}), 400

    target_user = User.query.get(target_user_id)
    if not target_user:
        return jsonify({"message": "Usuário não encontrado"}), 404

    
    target_user.plan = new_plan

    if new_plan == "FREE":
        target_user.vip_expires_at = None
    else:
        target_user.vip_expires_at = utc_now() + timedelta(days=30)

    db.session.commit()

    return jsonify({
        "message": f"Plano do usuário alterado para {new_plan} com sucesso",
        "user": serialize_user(target_user)
    })    

@app.route("/admin/ads/<int:ad_id>/block", methods=["PATCH"])
def block_ad(ad_id):
    data = request.get_json() or {}

    admin_user_id = data.get("admin_user_id")
    days = data.get("days")
    report_id = data.get("report_id")

    if not admin_user_id:
        return jsonify({"message": "Administrador não informado"}), 400

    admin_user = User.query.get(admin_user_id)
    if not admin_user or not admin_user.is_admin:
        return jsonify({"message": "Acesso negado"}), 403

    try:
        days = int(days)
    except (TypeError, ValueError):
        return jsonify({"message": "Quantidade de dias inválida"}), 400

    if days <= 0:
        return jsonify({"message": "Informe uma quantidade de dias maior que zero"}), 400

    ad = Ad.query.get(ad_id)
    if not ad:
        return jsonify({"message": "Anúncio não encontrado"}), 404

    ad.blocked_until = utc_now() + timedelta(days=days)

    if report_id:
        report = Report.query.get(report_id)
        if report:
            report.status = "RESOLVED"
            report.action_taken = "AD_BLOCKED"
            report.action_days = days
            report.reviewed_at = utc_now()
            report.reviewed_by_admin_id = admin_user.id

    db.session.commit()

    return jsonify({
        "message": f"Anúncio bloqueado por {days} dia(s) com sucesso",
        "ad": serialize_ad(ad)
    })
    
@app.route("/admin/ads/<int:ad_id>/unblock", methods=["PATCH"])
def unblock_ad(ad_id):
    data = request.get_json() or {}

    admin_user_id = data.get("admin_user_id")

    if not admin_user_id:
        return jsonify({"message": "Administrador não informado"}), 400

    admin_user = User.query.get(admin_user_id)
    if not admin_user or not admin_user.is_admin:
        return jsonify({"message": "Acesso negado"}), 403

    ad = Ad.query.get(ad_id)
    if not ad:
        return jsonify({"message": "Anúncio não encontrado"}), 404

    ad.blocked_until = None
    db.session.commit()

    return jsonify({
        "message": "Anúncio desbloqueado com sucesso",
        "ad": serialize_ad(ad)
    })    
    
    
@app.route("/admin/ads/<int:ad_id>/delete", methods=["DELETE"])
def admin_delete_ad(ad_id):
    data = request.get_json() or {}

    admin_user_id = data.get("admin_user_id")

    if not admin_user_id:
        return jsonify({"message": "Administrador não informado"}), 400

    admin_user = User.query.get(admin_user_id)
    if not admin_user or not admin_user.is_admin:
        return jsonify({"message": "Acesso negado"}), 403

    ad = Ad.query.get(ad_id)
    if not ad:
        return jsonify({"message": "Anúncio não encontrado"}), 404

    if ad.main_image:
        old_image_path = ad.main_image.lstrip("/")
        if os.path.exists(old_image_path):
            os.remove(old_image_path)

    if ad.main_video:
        old_video_path = ad.main_video.lstrip("/")
        if os.path.exists(old_video_path):
            os.remove(old_video_path)

    db.session.delete(ad)
    db.session.commit()

    return jsonify({"message": "Anúncio excluído com sucesso"})    
    
@app.route("/users/<int:user_id>", methods=["GET"])
def get_user(user_id):
    user = User.query.get(user_id)

    if not user:
        return jsonify({"message": "Usuário não encontrado"}), 404

    enforce_user_plan(user)
    sync_user_ads_with_plan(user)
    db.session.commit()

    return jsonify(serialize_user(user))
    
@app.route("/users/<int:user_id>/vip-purchases", methods=["GET"])
def get_user_vip_purchases(user_id):
    if not session.get("user_id"):
        return jsonify({"message": "Faça login para acessar seu histórico de pagamentos."}), 401

    if int(user_id) != int(session["user_id"]) and not session.get("is_admin"):
        return jsonify({"message": "Acesso negado"}), 403

    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "Usuário não encontrado"}), 404

    purchases = VipPurchase.query.filter_by(user_id=user_id)\
        .order_by(VipPurchase.created_at.desc())\
        .all()

    return jsonify([serialize_vip_purchase(purchase) for purchase in purchases]), 200    
    
@app.route("/users/<int:user_id>", methods=["PATCH"])
def update_user_profile(user_id):
    if not session.get("user_id"):
        return jsonify({"message": "Faça login para atualizar seus dados."}), 401

    if int(user_id) != int(session["user_id"]):
        return jsonify({"message": "Acesso negado"}), 403

    user = User.query.get(user_id)

    if not user:
        return jsonify({"message": "Usuário não encontrado"}), 404

    data = request.get_json() or {}

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    current_password = (data.get("current_password") or "").strip()
    new_password = (data.get("new_password") or "").strip()
    confirm_password = (data.get("confirm_password") or "").strip()

    if not name:
        return jsonify({"message": "Informe o nome"}), 400

    if not email:
        return jsonify({"message": "Informe o e-mail"}), 400

    existing_email = User.query.filter(User.email == email, User.id != user.id).first()
    if existing_email:
        return jsonify({"message": "Este e-mail já está em uso por outro usuário"}), 400

    if new_password or confirm_password or current_password:
        if not current_password:
            return jsonify({"message": "Informe sua senha atual para alterar a senha"}), 400

        if not check_password_hash(user.password_hash, current_password):
            return jsonify({"message": "Senha atual incorreta"}), 400

        if not new_password or not confirm_password:
            return jsonify({"message": "Informe a nova senha e a confirmação"}), 400

        if new_password != confirm_password:
            return jsonify({"message": "A nova senha e a confirmação não coincidem"}), 400

        if len(new_password) < 6:
            return jsonify({"message": "A nova senha deve ter pelo menos 6 caracteres"}), 400

        user.password_hash = generate_password_hash(new_password)

    user.name = name
    user.email = email
    session["user_name"] = user.name

    db.session.commit()

    return jsonify({
        "message": "Perfil atualizado com sucesso",
        "user": serialize_user(user)
    }), 200    

@app.route("/admin/users", methods=["GET"])
def admin_list_users():
    users = User.query.all()

    result = []
    for u in users:
        latest_report = Report.query.filter_by(reported_user_id=u.id).order_by(Report.created_at.desc()).first()

        is_blocked = bool(u.blocked_until and u.blocked_until > utc_now())

        block_reason = None

        if is_blocked:
            latest_report = Report.query.filter_by(reported_user_id=u.id)\
                .order_by(Report.created_at.desc()).first()

            if latest_report and latest_report.reporter_message:
                block_reason = latest_report.reporter_message
            else:
                block_reason = "Bloqueio manual do administrador"
            
        result.append({
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "cpf": u.cpf,
            "is_admin": getattr(u, "is_admin", False),
            "is_blocked": is_blocked,
            "blocked_until": u.blocked_until.isoformat() if u.blocked_until else None,
            "block_reason": block_reason,
            "plan": u.plan,
            "vip_expires_at": u.vip_expires_at.isoformat() if u.vip_expires_at else None
        })

    return jsonify(result)

@app.route("/admin/users-page")
@admin_required_page
def admin_users_page():
    return render_template("admin_users.html", active_page="users")

@app.route("/admin/users/create", methods=["POST"])
def admin_create_user():
    data = request.get_json() or {}

    name = data.get("name", "").strip()
    cpf = normalize_cpf(data.get("cpf", ""))
    email = data.get("email", "").strip().lower()
    phone = data.get("phone", "").strip()
    password = data.get("password", "").strip()

    if not name or not cpf or not email or not phone or not password:
        return jsonify({"message": "Preencha nome, CPF, e-mail, telefone e senha"}), 400
        
    if not is_valid_cpf(cpf):
        return jsonify({"message": "CPF inválido"}), 400    

    existing_email = User.query.filter_by(email=email).first()
    if existing_email:
        return jsonify({"message": "E-mail já cadastrado"}), 400

    existing_cpf = User.query.filter_by(cpf=cpf).first()
    if existing_cpf:
        return jsonify({"message": "CPF já cadastrado"}), 400

    user = User(
        name=name,
        cpf=cpf,
        email=email,
        phone=phone,
        password_hash=generate_password_hash(password),
        plan="FREE"
    )

    db.session.add(user)
    db.session.commit()

    return jsonify({"message": "Usuário cadastrado com sucesso"}) 


    
@app.route("/admin/users/<int:user_id>/delete", methods=["DELETE"])
def admin_delete_user(user_id):
    user = User.query.get(user_id)

    if not user:
        return jsonify({"message": "Usuário não encontrado"}), 404

    if getattr(user, "is_admin", False):
        return jsonify({"message": "Não é permitido excluir administrador"}), 400

    try:
        # 🔥 PASSO 1 — apagar anúncios do usuário
        ads = Ad.query.filter_by(user_id=user.id).all()

        for ad in ads:
            db.session.delete(ad)

        # 🔥 PASSO 2 — apagar usuário
        db.session.delete(user)

        db.session.commit()

        return jsonify({"message": "Usuário excluído com sucesso"})

    except Exception as e:
        db.session.rollback()
        print("ERRO AO EXCLUIR USUÁRIO:", e)

        return jsonify({
            "message": "Erro ao excluir usuário",
            "error": str(e)
        }), 500   
        
@app.route("/admin/dashboard-data")
def admin_dashboard_data():
    total_users = User.query.count()
    vip_users = User.query.filter(User.plan != "FREE").count()
    blocked_users = User.query.filter(User.blocked_until.isnot(None)).count()
    vip_bronze = User.query.filter_by(plan="VIP_BRONZE").count()
    vip_prata = User.query.filter_by(plan="VIP_PRATA").count()
    vip_ouro = User.query.filter_by(plan="VIP_OURO").count()
    vip_premium = User.query.filter_by(plan="VIP_PREMIUM").count()

    total_ads = Ad.query.count()
    active_ads = Ad.query.filter_by(is_active=True).count()

    total_reports = Report.query.count()
    pending_reports = Report.query.filter_by(status="OPEN").count()

    total_locations = ManagedLocation.query.count()
    blocked_locations = BlockedLocation.query.count()

    # Usuários por plano
    users_by_plan_rows = db.session.query(User.plan, db.func.count(User.id)).group_by(User.plan).all()

    users_by_plan = [
        {
            "plan": row[0] or "FREE",
            "total": row[1]
        }
        for row in users_by_plan_rows
    ]

    return jsonify({
        "summary": {
        "total_users": total_users,
        "vip_users": vip_users,
        "blocked_users": blocked_users,

        "vip_bronze": vip_bronze,
        "vip_prata": vip_prata,
        "vip_ouro": vip_ouro,
        "vip_premium": vip_premium,

        "total_ads": total_ads,
        "active_ads": active_ads,
        "total_reports": total_reports,
        "pending_reports": pending_reports,
        "total_locations": total_locations,
        "blocked_locations": blocked_locations
    },
        "users_by_plan": users_by_plan
    }) 

    
# =========================
# INIT DATABASE
# =========================

def initialize_database():
    with app.app_context():
        db.create_all()
        ensure_admin_user()

initialize_database()

# =========================
# MAIN
# =========================

if __name__ == "__main__":
    app.run(debug=True)