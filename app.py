from flask import (
    Flask,
    request,
    jsonify,
    render_template,
    make_response,
    session,
    redirect,
    url_for,
    send_from_directory,
    Response,
    send_file,
    abort
)
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import case, or_, func
from datetime import datetime, timedelta, UTC, date
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image, ImageOps
import os
import json
import gzip
import io
import uuid
import subprocess
import requests
import time
from zoneinfo import ZoneInfo
from threading import Lock
from urllib.request import urlopen, Request
from urllib.parse import (
    quote,
    urlparse,
    unquote
)
from functools import wraps
from flask_mail import Mail, Message
import secrets
import hashlib
import re
import unicodedata
import base64
import qrcode
from decimal import Decimal, InvalidOperation




load_dotenv()

app = Flask(__name__)

app.jinja_env.globals["timedelta"] = timedelta

APP_VERSION = (
    os.getenv("RENDER_GIT_COMMIT")
    or os.getenv("APP_VERSION")
    or "local-dev"
)[:12]

app.config["APP_VERSION"] = APP_VERSION

# =========================
# CACHE DE LOCALIDADES
# =========================

LOCATION_CACHE = {
    "states": {
        "data": None,
        "expires_at": 0
    },
    "cities": {},
    "neighborhoods": {}
}

LOCATION_CACHE_LOCK = Lock()

STATES_CACHE_SECONDS = 24 * 60 * 60
CITIES_CACHE_SECONDS = 24 * 60 * 60
NEIGHBORHOODS_CACHE_SECONDS = 6 * 60 * 60

MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN", "")

BASE_URL = os.getenv("BASE_URL", "https://www.cataloginpk.com.br")


# =========================
# ADZUNA API
# =========================

ADZUNA_APP_ID = (
    os.getenv("ADZUNA_APP_ID")
    or ""
).strip()

ADZUNA_APP_KEY = (
    os.getenv("ADZUNA_APP_KEY")
    or ""
).strip()

ADZUNA_COUNTRY = "br"

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
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True, "pool_recycle": 300}

db = SQLAlchemy(app)
mail = Mail(app)

RENDER_DISK_PATH = os.getenv("RENDER_DISK_PATH", "")
UPLOAD_BASE = RENDER_DISK_PATH if RENDER_DISK_PATH else os.path.join("static", "uploads")

UPLOAD_IMAGE_FOLDER = os.path.join(
    UPLOAD_BASE,
    "images"
)

UPLOAD_VIDEO_FOLDER = os.path.join(
    UPLOAD_BASE,
    "videos"
)

UPLOAD_THUMBNAIL_FOLDER = os.path.join(
    UPLOAD_BASE,
    "thumbnails"
)

os.makedirs(
    UPLOAD_IMAGE_FOLDER,
    exist_ok=True
)

os.makedirs(
    UPLOAD_VIDEO_FOLDER,
    exist_ok=True
)

os.makedirs(
    UPLOAD_THUMBNAIL_FOLDER,
    exist_ok=True
)

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
ALLOWED_VIDEO_EXTENSIONS = {"mp4"}

# =========================
# COMPROVANTES DE PASSEIOS
# =========================

ALLOWED_TRIP_RECEIPT_EXTENSIONS = {
    "jpg",
    "jpeg",
    "png",
    "webp",
    "heic",
    "heif",
    "pdf"
}

MAX_TRIP_RECEIPT_SIZE = (
    20 * 1024 * 1024
)

def save_trip_receipt(
    receipt_file,
    trip_id
):
    """
    Valida e salva um comprovante de passeio.

    Retorna:
        caminho_publico, erro, status_http
    """

    if (
        not receipt_file
        or not receipt_file.filename
    ):
        return (
            None,
            "Selecione um comprovante.",
            400
        )


    filename = (
        receipt_file.filename
        or ""
    ).strip()

    filename_lower = filename.lower()


    # =========================
    # EXTENSÃO
    # =========================

    if "." not in filename_lower:

        return (
            None,
            (
                "Não foi possível identificar "
                "o formato do comprovante. "
                "Envie uma foto ou arquivo PDF."
            ),
            400
        )


    extension = (
        filename_lower
        .rsplit(".", 1)[1]
        .strip()
    )


    if (
        extension
        not in
        ALLOWED_TRIP_RECEIPT_EXTENSIONS
    ):

        return (
            None,
            (
                "Formato de comprovante não aceito. "
                "Envie JPG, JPEG, PNG, WEBP, "
                "HEIC, HEIF ou PDF."
            ),
            400
        )


    # =========================
    # TAMANHO
    # =========================

    try:

        receipt_file.stream.seek(
            0,
            os.SEEK_END
        )

        file_size = (
            receipt_file.stream.tell()
        )

        receipt_file.stream.seek(0)

    except Exception as error:

        print(
            "ERRO AO VERIFICAR COMPROVANTE:",
            repr(error),
            flush=True
        )

        return (
            None,
            (
                "Não foi possível verificar "
                "o comprovante enviado."
            ),
            400
        )


    if file_size <= 0:

        return (
            None,
            (
                "O comprovante enviado está vazio. "
                "Selecione o arquivo novamente."
            ),
            400
        )


    if (
        file_size >
        MAX_TRIP_RECEIPT_SIZE
    ):

        return (
            None,
            (
                "O comprovante é muito grande. "
                "O tamanho máximo permitido é 20 MB."
            ),
            413
        )


    # =========================
    # NOME DO ARQUIVO
    # =========================

    receipt_filename = (
        f"trip_{trip_id}_"
        f"{uuid.uuid4().hex}."
        f"{extension}"
    )


    # =========================
    # PASTA
    # =========================

    receipt_folder = os.path.join(
        UPLOAD_BASE,
        "trip_receipts"
    )

    os.makedirs(
        receipt_folder,
        exist_ok=True
    )


    receipt_full_path = os.path.join(
        receipt_folder,
        receipt_filename
    )


    # =========================
    # SALVAR
    # =========================

    try:

        receipt_file.save(
            receipt_full_path
        )

    except Exception as error:

        print(
            "ERRO AO SALVAR COMPROVANTE:",
            repr(error),
            flush=True
        )

        return (
            None,
            (
                "Não foi possível salvar "
                "o comprovante."
            ),
            500
        )


    receipt_path = (
        f"/media/trip-receipts/"
        f"{receipt_filename}"
    )


    return (
        receipt_path,
        None,
        200
    )

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

def static_asset(filename):
    return url_for(
        "static",
        filename=filename,
        v=app.config["APP_VERSION"]
    )


app.jinja_env.globals["static_asset"] = static_asset

@app.after_request
def disable_dynamic_cache(response):
    content_type = response.headers.get(
        "Content-Type",
        ""
    ).lower()

    if (
        "text/html" in content_type
        or request.path == "/service-worker.js"
        or request.path.startswith("/ads/")
        or request.path.startswith("/item/")
        or request.path.startswith("/search")
        or request.path.startswith("/admin/")
        or request.path == "/admin/users"
    ):
        response.headers["Cache-Control"] = (
            "no-store, no-cache, "
            "must-revalidate, max-age=0"
        )
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    return response

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
    free_can_use_location = db.Column(db.Boolean, nullable=False, default=False)

    bronze_ads_limit = db.Column(db.Integer, nullable=False, default=5)
    bronze_keywords_limit = db.Column(db.Integer, nullable=False, default=10)
    bronze_can_use_images = db.Column(db.Boolean, nullable=False, default=True)
    bronze_can_use_videos = db.Column(db.Boolean, nullable=False, default=False)
    bronze_can_appear_in_vip_list = db.Column(db.Boolean, nullable=False, default=True)
    bronze_can_show_full_details = db.Column(db.Boolean, nullable=False, default=True)
    bronze_price = db.Column(db.Float, nullable=False, default=19.90)
    bronze_can_use_vitrine = db.Column(db.Boolean, nullable=False, default=True)
    bronze_can_use_location = db.Column(db.Boolean, nullable=False, default=False)

    prata_ads_limit = db.Column(db.Integer, nullable=False, default=10)
    prata_keywords_limit = db.Column(db.Integer, nullable=False, default=15)
    prata_can_use_images = db.Column(db.Boolean, nullable=False, default=True)
    prata_can_use_videos = db.Column(db.Boolean, nullable=False, default=True)
    prata_can_appear_in_vip_list = db.Column(db.Boolean, nullable=False, default=True)
    prata_can_show_full_details = db.Column(db.Boolean, nullable=False, default=True)
    prata_price = db.Column(db.Float, nullable=False, default=39.90)
    prata_can_use_vitrine = db.Column(db.Boolean, nullable=False, default=True)
    prata_can_use_location = db.Column(db.Boolean, nullable=False, default=True)

    ouro_ads_limit = db.Column(db.Integer, nullable=False, default=20)
    ouro_keywords_limit = db.Column(db.Integer, nullable=False, default=20)
    ouro_can_use_images = db.Column(db.Boolean, nullable=False, default=True)
    ouro_can_use_videos = db.Column(db.Boolean, nullable=False, default=True)
    ouro_can_appear_in_vip_list = db.Column(db.Boolean, nullable=False, default=True)
    ouro_can_show_full_details = db.Column(db.Boolean, nullable=False, default=True)
    ouro_price = db.Column(db.Float, nullable=False, default=59.90)
    ouro_can_use_vitrine = db.Column(db.Boolean, nullable=False, default=True)
    ouro_can_use_location = db.Column(db.Boolean, nullable=False, default=True)

    premium_ads_limit = db.Column(db.Integer, nullable=False, default=50)
    premium_keywords_limit = db.Column(db.Integer, nullable=False, default=30)
    premium_can_use_images = db.Column(db.Boolean, nullable=False, default=True)
    premium_can_use_videos = db.Column(db.Boolean, nullable=False, default=True)
    premium_can_appear_in_vip_list = db.Column(db.Boolean, nullable=False, default=True)
    premium_can_show_full_details = db.Column(db.Boolean, nullable=False, default=True)
    premium_price = db.Column(db.Float, nullable=False, default=99.90)
    premium_can_use_vitrine = db.Column(db.Boolean, nullable=False, default=True)
    premium_can_use_location = db.Column(db.Boolean, nullable=False, default=True)
    
    support_whatsapp = db.Column(db.String(30), nullable=True)
    instagram_url = db.Column(
        db.String(500),
        nullable=True
    )
    
    # =========================
    # PROMOÇÕES VIP
    # =========================

    new_user_vip_promotion_enabled = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )

    new_user_vip_promotion_plan = db.Column(
        db.String(20),
        nullable=False,
        default="VIP_BRONZE"
    )

    new_user_vip_promotion_days = db.Column(
        db.Integer,
        nullable=False,
        default=30
    )

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
    
    slug = db.Column(
        db.String(255),
        nullable=True,
        index=True
    )
    
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
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)

    plan = db.Column(db.String(20), default="FREE")
    main_image = db.Column(db.String(500))
    main_video = db.Column(db.String(500))
    is_active = db.Column(db.Boolean, default=True)
    
    show_on_home = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        index=True
    )
    
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


# ==========================================
# OLIMPÍADAS - CHAVES DE ACESSO ÀS SÚMULAS
# ==========================================

class OlympicScoresheetAccessKey(db.Model):
    __tablename__ = "olympic_scoresheet_access_keys"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    name = db.Column(
        db.String(150),
        nullable=False
    )

    key_hash = db.Column(
        db.String(255),
        nullable=False,
        unique=True,
        index=True
    )

    is_active = db.Column(
        db.Boolean,
        nullable=False,
        default=True
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )

    expires_at = db.Column(
        db.DateTime,
        nullable=True
    )

    last_used_at = db.Column(
        db.DateTime,
        nullable=True
    )


# ==========================================
# OLIMPÍADAS BOMBEIRO MIRIM
# ==========================================

class OlympicEdition(db.Model):
    __tablename__ = "olympic_editions"

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(
        db.String(200),
        nullable=False
    )

    year = db.Column(
        db.Integer,
        nullable=False
    )

    start_date = db.Column(
        db.Date,
        nullable=True
    )

    end_date = db.Column(
        db.Date,
        nullable=True
    )

    description = db.Column(
        db.Text,
        nullable=True
    )

    is_active = db.Column(
        db.Boolean,
        nullable=False,
        default=True
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )    
    

# ==========================================
# OLIMPÍADAS - EQUIPES
# ==========================================

class OlympicTeam(db.Model):
    __tablename__ = "olympic_teams"

    id = db.Column(db.Integer, primary_key=True)

    edition_id = db.Column(
        db.Integer,
        db.ForeignKey("olympic_editions.id"),
        nullable=False
    )

    name = db.Column(
        db.String(100),
        nullable=False
    )

    color = db.Column(
        db.String(50),
        nullable=False
    )

    coach = db.Column(
        db.String(150),
        nullable=False
    )

    shift = db.Column(
        db.String(20),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )

    edition = db.relationship(
        "OlympicEdition",
        backref=db.backref(
            "teams",
            lazy=True
        )
    )

    __table_args__ = (
        db.UniqueConstraint(
            "edition_id",
            "color",
            "shift",
            name="uq_olympic_team_edition_color_shift"
        ),
    )
    

# ==========================================
# OLIMPÍADAS - ATLETAS
# ==========================================

class OlympicAthlete(db.Model):

    __tablename__ = "olympic_athletes"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    edition_id = db.Column(
        db.Integer,
        db.ForeignKey("olympic_editions.id"),
        nullable=False
    )

    team_id = db.Column(
        db.Integer,
        db.ForeignKey("olympic_teams.id"),
        nullable=True
    )
    
    # Turno do brigadino
    # Permite identificar o turno mesmo sem equipe
    shift = db.Column(
        db.String(20),
        nullable=True
    )

    name = db.Column(
        db.String(150),
        nullable=False
    )

    birth_date = db.Column(
        db.Date,
        nullable=True
    )
    
    age = db.Column(
        db.Integer,
        nullable=True
    )

    sex = db.Column(
        db.String(10),
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )

    edition = db.relationship(
        "OlympicEdition",
        backref=db.backref("athletes", lazy=True)
    )

    team = db.relationship(
        "OlympicTeam",
        backref=db.backref("athletes", lazy=True)
    )


class OlympicModality(db.Model):
    __tablename__ = "olympic_modalities"

    id = db.Column(db.Integer, primary_key=True)

    edition_id = db.Column(
        db.Integer,
        db.ForeignKey("olympic_editions.id"),
        nullable=False
    )

    name = db.Column(
        db.String(100),
        nullable=False
    )

    description = db.Column(db.Text, nullable=True)

    match_duration_minutes = db.Column(
        db.Integer,
        nullable=True
    )
    
    
    max_matches_per_team_per_day = db.Column(
        db.Integer,
        nullable=False,
        default=1
    )
    
    max_matches_per_modality_per_day = db.Column(
        db.Integer,
        nullable=True
    )
  

    is_active = db.Column(
        db.Boolean,
        nullable=False,
        default=True
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )

    edition = db.relationship(
        "OlympicEdition",
        backref=db.backref("modalities", lazy=True)
    )

    __table_args__ = (
        db.UniqueConstraint(
            "edition_id",
            "name",
            name="uq_olympic_modality_edition_name"
        ),
    )


class OlympicModalityRegistration(db.Model):
    __tablename__ = "olympic_modality_registrations"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    edition_id = db.Column(
        db.Integer,
        db.ForeignKey("olympic_editions.id"),
        nullable=False
    )

    modality_id = db.Column(
        db.Integer,
        db.ForeignKey("olympic_modalities.id"),
        nullable=False
    )

    athlete_id = db.Column(
        db.Integer,
        db.ForeignKey("olympic_athletes.id"),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp()
    )

    # Relacionamentos com os registros existentes
    edition = db.relationship(
        "OlympicEdition",
        backref=db.backref(
            "modality_registrations",
            lazy=True
        )
    )

    modality = db.relationship(
        "OlympicModality",
        backref=db.backref(
            "registrations",
            lazy=True
        )
    )

    athlete = db.relationship(
        "OlympicAthlete",
        backref=db.backref(
            "modality_registrations",
            lazy=True
        )
    )

    __table_args__ = (
        db.UniqueConstraint(
            "modality_id",
            "athlete_id",
            name="uq_olympic_modality_registration"
        ),
    )



# ==========================================
# OLIMPÍADAS - CONFRONTOS E PARTIDAS
# ==========================================

class OlympicMatch(db.Model):
    __tablename__ = "olympic_matches"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    edition_id = db.Column(
        db.Integer,
        db.ForeignKey("olympic_editions.id"),
        nullable=False
    )

    modality_id = db.Column(
        db.Integer,
        db.ForeignKey("olympic_modalities.id"),
        nullable=False
    )

    team_a_id = db.Column(
        db.Integer,
        db.ForeignKey("olympic_teams.id"),
        nullable=False
    )

    team_b_id = db.Column(
        db.Integer,
        db.ForeignKey("olympic_teams.id"),
        nullable=False
    )

    match_date = db.Column(
        db.Date,
        nullable=False
    )

    match_time = db.Column(
        db.Time,
        nullable=False
    )

    shift = db.Column(
        db.String(20),
        nullable=False
    )

    phase = db.Column(
        db.String(30),
        nullable=False,
        default="CLASSIFICATORIA"
    )

    status = db.Column(
        db.String(20),
        nullable=False,
        default="AGENDADO"
    )

    score_a = db.Column(
        db.Integer,
        nullable=True
    )

    score_b = db.Column(
        db.Integer,
        nullable=True
    )
    
    red_cards_a = db.Column(
        db.Integer,
        nullable=True
    )
    
    red_cards_b = db.Column(
        db.Integer,
        nullable=True
    )

    yellow_cards_a = db.Column(
        db.Integer,
        nullable=True
    )
    
    yellow_cards_b = db.Column(
        db.Integer,
        nullable=True
    )
    
    fouls_a = db.Column(
        db.Integer,
        nullable=True
    )

    fouls_b = db.Column(
        db.Integer,
        nullable=True
    )

    notes = db.Column(
        db.Text,
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )

    edition = db.relationship(
        "OlympicEdition",
        backref=db.backref("matches", lazy=True)
    )

    modality = db.relationship(
        "OlympicModality",
        backref=db.backref("matches", lazy=True)
    )

    team_a = db.relationship(
        "OlympicTeam",
        foreign_keys=[team_a_id]
    )

    team_b = db.relationship(
        "OlympicTeam",
        foreign_keys=[team_b_id]
    )

    __table_args__ = (
        db.CheckConstraint(
            "team_a_id <> team_b_id",
            name="ck_olympic_match_different_teams"
        ),
        db.CheckConstraint(
            "score_a IS NULL OR score_a >= 0",
            name="ck_olympic_match_score_a"
        ),
        db.CheckConstraint(
            "score_b IS NULL OR score_b >= 0",
            name="ck_olympic_match_score_b"
        ),
    )
    
# ==========================================
# OLIMPÍADAS - CLASSIFICAÇÃO AUTOMÁTICA
# ==========================================

def get_olympic_classification_matches(
    edition_id,
    modality_id,
    shift
):
    """
    Busca somente os confrontos finalizados
    da fase classificatória, separados por
    edição, modalidade e turno.

    Não altera dados no banco.
    """

    matches = (
        OlympicMatch.query
        .filter_by(
            edition_id=edition_id,
            modality_id=modality_id,
            shift=shift.upper(),
            phase="CLASSIFICATORIA",
            status="FINALIZADO"
        )
        .order_by(OlympicMatch.id)
        .all()
    )

    return matches  


def calculate_olympic_classification(
    edition_id,
    modality_id,
    shift
):
    """
    Calcula a classificação por turno e modalidade.

    Desempates:
    1. Pontos
    2. Saldo de gols
    3. Menos cartões vermelhos
    4. Menos cartões amarelos
    5. Menos faltas
    """

    normalized_shift = (shift or "").strip().upper()
    
    modality = db.session.get(OlympicModality, modality_id)

    modality_name = (
        modality.name.strip().lower()
        if modality else ""
    )

    uses_goal_difference = (
        modality_name in ("futsal", "golzinho")
    )

    teams = (
        OlympicTeam.query
        .filter(
            OlympicTeam.edition_id == edition_id,
            db.func.upper(OlympicTeam.shift) == normalized_shift
        )
        .order_by(OlympicTeam.id)
        .all()
    )

    classification = {}

    for team in teams:
        classification[team.id] = {
            "team_id": team.id,
            "team_name": team.name,
            "coach": team.coach,
            "played": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "points": 0,
            "goals_for": 0,
            "goals_against": 0,
            "goal_difference": 0,
            "red_cards": 0,
            "yellow_cards": 0,
            "fouls": 0
        }

    matches = get_olympic_classification_matches(
        edition_id,
        modality_id,
        normalized_shift
    )

    for match in matches:

        if (
            match.team_a_id not in classification
            or match.team_b_id not in classification
            or match.score_a is None
            or match.score_b is None
        ):
            continue

        team_a = classification[match.team_a_id]
        team_b = classification[match.team_b_id]

        team_a["played"] += 1
        team_b["played"] += 1

        if uses_goal_difference:
            team_a["goals_for"] += match.score_a
            team_a["goals_against"] += match.score_b

            team_b["goals_for"] += match.score_b
            team_b["goals_against"] += match.score_a

        team_a["red_cards"] += match.red_cards_a or 0
        team_b["red_cards"] += match.red_cards_b or 0

        team_a["yellow_cards"] += match.yellow_cards_a or 0
        team_b["yellow_cards"] += match.yellow_cards_b or 0

        team_a["fouls"] += match.fouls_a or 0
        team_b["fouls"] += match.fouls_b or 0

        if match.score_a > match.score_b:
            team_a["wins"] += 1
            team_a["points"] += 3
            team_b["losses"] += 1

        elif match.score_b > match.score_a:
            team_b["wins"] += 1
            team_b["points"] += 3
            team_a["losses"] += 1

        else:
            team_a["draws"] += 1
            team_b["draws"] += 1
            team_a["points"] += 1
            team_b["points"] += 1

    for team in classification.values():
        team["goal_difference"] = (
            team["goals_for"] - team["goals_against"]
        )

    if uses_goal_difference:
        ordered_classification = sorted(
            classification.values(),
            key=lambda team: (
                -team["points"],
                -team["goal_difference"],
                team["red_cards"],
                team["yellow_cards"],
                team["fouls"],
                team["team_id"]
            )
        )
    else:
        ordered_classification = sorted(
            classification.values(),
            key=lambda team: (
                -team["points"],
                -team["wins"],
                team["team_id"]
            )
        )

    for position, team in enumerate(
        ordered_classification,
        start=1
    ):
        team["position"] = position

    return ordered_classification
    
        


# ==========================================
# OLIMPÍADAS - CLASSIFICAÇÃO GERAL
# ==========================================

def calculate_olympic_overall_standings(edition_id):
    teams = OlympicTeam.query.filter_by(
        edition_id=edition_id
    ).order_by(OlympicTeam.id).all()

    modalities = OlympicModality.query.filter_by(
        edition_id=edition_id,
        is_active=True
    ).order_by(OlympicModality.name).all()

    standings = {}

    for team in teams:
        standings[team.id] = {
            "team_id": team.id,
            "color": team.color,
            "coach": team.coach,
            "shift": team.shift,
            "shift_titles": 0,
            "provisional_titles": 0,
            "intershift_titles": 0,
            "total_titles": 0,
            "bonus_points": 0,
            "won_modalities": [],
            "provisional_modalities": []

        }

    
    modality_results = []
    pending = []
    modality_leaders = []


    for modality in modalities:
        champions = {}

        for shift in ("MATUTINO", "VESPERTINO"):
            matches = OlympicMatch.query.filter(
                OlympicMatch.edition_id == edition_id,
                OlympicMatch.modality_id == modality.id,
                OlympicMatch.phase == "CLASSIFICATORIA",
                db.func.upper(OlympicMatch.shift) == shift
            ).all()

            
            # Verifica se todos os confrontos classificatórios
            # foram concluídos e possuem resultados válidos.
            classification_complete = bool(matches) and all(
                match.status == "FINALIZADO"
                and match.score_a is not None
                and match.score_b is not None
                for match in matches
            )

            # Verifica se existe pelo menos um resultado válido.
            has_results = any(
                match.status == "FINALIZADO"
                and match.score_a is not None
                and match.score_b is not None
                for match in matches
            )

            
            # Sem resultados, ainda não há liderança provisória.
            if not has_results:
                pending.append({
                    "modality": modality.name,
                    "shift": shift,
                    "reason": "Aguardando resultados"
                })

                # Mantém a modalidade visível na tabela,
                # mesmo sem confrontos finalizados.
                modality_leaders.append({
                    "modality": modality.name,
                    "shift": shift,
                    "team_id": None,
                    "color": "—",
                    "coach": "—",
                    "points": 0,
                    "status": "AGUARDANDO"
                })

                continue


            # Se ainda existem confrontos pendentes,
            # a classificação será considerada provisória.
            if not classification_complete:
                pending.append({
                    "modality": modality.name,
                    "shift": shift,
                    "reason": "Classificatória não encerrada"
                })


            classification = calculate_olympic_classification(
                edition_id,
                modality.id,
                shift
            )

            if not classification:
                continue

            first = classification[0]

            # Verifica empate conforme os critérios da modalidade.
            modality_name = modality.name.strip().lower()

            if modality_name in ("futsal", "golzinho"):
                def ranking_key(item):
                    return (
                        item["points"],
                        item["goal_difference"],
                        -item["red_cards"],
                        -item["yellow_cards"],
                        -item["fouls"]
                    )
            else:
                def ranking_key(item):
                    return (
                        item["points"],
                        item["wins"]
                    )

            tied = [
                item for item in classification
                if ranking_key(item) == ranking_key(first)
            ]

            
            
            if len(tied) > 1:
                pending.append({
                    "modality": modality.name,
                    "shift": shift,
                    "reason": (
                        "Desempate regulamentar necessário"
                        if classification_complete
                        else "Empate provisório na liderança"
                    )
                })


                # Registra as equipes empatadas na liderança.
                tied_teams = [
                    (
                        f'{standings[item["team_id"]]["color"]} — '
                        f'{standings[item["team_id"]]["coach"]}'
                    )
                    for item in tied
                ]

                modality_leaders.append({
                    "modality": modality.name,
                    "shift": shift,
                    "team_id": None,
                    "color": " / ".join(tied_teams),
                    "coach": "Desempate pendente",
                    "points": first["points"],
                    "status": (
                        "DESEMPATE"
                        if classification_complete
                        else "EMPATE_PROVISORIO"
                    )

                })

                continue


            
            winner_id = first["team_id"]

            # Registra a liderança para a tabela por modalidade.
            modality_leaders.append({
                "modality": modality.name,
                "shift": shift,
                "team_id": winner_id,
                "color": standings[winner_id]["color"],
                "coach": standings[winner_id]["coach"],
                "points": first["points"],
                "status": (
                    "DEFINITIVO"
                    if classification_complete
                    else "PARCIAL"
                )
            })

            if classification_complete:
                # Título confirmado somente após o encerramento
                # de todos os confrontos classificatórios.
                champions[shift] = winner_id

                standings[winner_id]["shift_titles"] += 1

                standings[winner_id]["won_modalities"].append(
                    f"{modality.name} — {shift.title()}"
                )

                modality_results.append({
                    "modality": modality.name,
                    "stage": "Campeã do turno",
                    "shift": shift,
                    "winner": (
                        f'{standings[winner_id]["color"]} — '
                        f'{standings[winner_id]["coach"]}'
                    )
                })

            else:
                # Liderança provisória enquanto houver jogos pendentes.
                standings[winner_id]["provisional_titles"] += 1

                standings[winner_id]["provisional_modalities"].append(
                    f"{modality.name} — {shift.title()}"
                )


        # A final interturnos só pode ter resultado
        # reconhecido depois de ambas as campeãs
        # dos turnos estarem confirmadas.
        if len(champions) != 2:
            continue

        finals = OlympicMatch.query.filter(
            OlympicMatch.edition_id == edition_id,
            OlympicMatch.modality_id == modality.id,
            OlympicMatch.phase == "FINAL_ENTRE_TURNOS"
        ).all()

        if len(finals) != 1:
            pending.append({
                "modality": modality.name,
                "shift": "INTERTURNOS",
                "reason": "Final interturnos não definida"
            })
            continue

        final = finals[0]

        if (
            final.status != "FINALIZADO"
            or final.score_a is None
            or final.score_b is None
        ):
            pending.append({
                "modality": modality.name,
                "shift": "INTERTURNOS",
                "reason": "Final interturnos pendente"
            })
            continue

        expected_teams = set(champions.values())
        actual_teams = {
            final.team_a_id,
            final.team_b_id
        }

        if expected_teams != actual_teams:
            pending.append({
                "modality": modality.name,
                "shift": "INTERTURNOS",
                "reason": "Final não corresponde às campeãs dos turnos"
            })
            continue

        if final.score_a == final.score_b:
            pending.append({
                "modality": modality.name,
                "shift": "INTERTURNOS",
                "reason": "Final exige desempate"
            })
            continue

        winner_id = (
            final.team_a_id
            if final.score_a > final.score_b
            else final.team_b_id
        )

        standings[winner_id]["intershift_titles"] += 1
        standings[winner_id]["bonus_points"] += 3
        standings[winner_id]["won_modalities"].append(
            f"{modality.name} — Interturnos"
        )

        modality_results.append({
            "modality": modality.name,
            "stage": "Campeã interturnos",
            "shift": "INTERTURNOS",
            "winner": (
                f'{standings[winner_id]["color"]} — '
                f'{standings[winner_id]["coach"]}'
            )
        })

    
    for team in standings.values():
        # Soma títulos definitivos, provisórios
        # e conquistas das finais interturnos.
        team["total_titles"] = (
            team["shift_titles"]
            + team["provisional_titles"]
            + team["intershift_titles"]
        )


    ordered = sorted(
        standings.values(),
        key=lambda team: (
            -team["total_titles"],
            team["team_id"]
        )
    )

    for team in ordered:
        team["position"] = (
            1 + sum(
                other["total_titles"] > team["total_titles"]
                for other in ordered
            )
        )

    champion = None

    if not pending and ordered:
        highest = ordered[0]["total_titles"]

        leaders = [
            team for team in ordered
            if team["total_titles"] == highest
        ]

        if highest > 0 and len(leaders) == 1:
            champion = leaders[0]

    
    return {
        "teams": ordered,
        "confirmed": modality_results,
        "pending": pending,
        "modality_leaders": sorted(
            modality_leaders,
            key=lambda item: (
                0 if item["shift"] == "MATUTINO" else 1,
                item["modality"].lower()
            )
        ),
        "champion": champion,
        "complete": len(pending) == 0
    }

  
# ==========================================
# OLIMPÍADAS - CONSULTAR CLASSIFICAÇÃO GERAL
# ==========================================

@app.route(
    "/admin/olimpiadas/classificacao-geral/<int:edition_id>",
    methods=["GET"]
)
def admin_olympic_overall_standings(edition_id):

    edition = db.session.get(OlympicEdition, edition_id)

    if not edition:
        return jsonify({
            "success": False,
            "message": "Edição das Olimpíadas não encontrada."
        }), 404

    standings = calculate_olympic_overall_standings(edition_id)

    return jsonify({
        "success": True,
        "edition_id": edition_id,
        "edition_name": edition.name,
        "standings": standings
    })
    
# ==========================================
# OLIMPÍADAS - CONSULTAR CLASSIFICAÇÃO
# ==========================================

@app.route(
    "/admin/olimpiadas/classificacao/<int:edition_id>/<int:modality_id>/<shift>",
    methods=["GET"]
)

def admin_olympic_classification(
    edition_id,
    modality_id,
    shift
):

    classification = calculate_olympic_classification(
        edition_id,
        modality_id,
        shift
    )

    return jsonify({
        "edition_id": edition_id,
        "modality_id": modality_id,
        "shift": shift,
        "classification": classification
    })
    
# ==========================================
# OLIMPÍADAS - PÁGINA DA CLASSIFICAÇÃO
# ==========================================

@app.route(
    "/admin/olimpiadas/classificacao/<int:edition_id>/<int:modality_id>/<shift>/pagina",
    methods=["GET"]
)

def admin_olympic_classification_page(
    edition_id,
    modality_id,
    shift
):

    classification = calculate_olympic_classification(
        edition_id,
        modality_id,
        shift
    )

    modality = db.session.get(
        OlympicModality,
        modality_id
    )
    
    
    # Ranking de artilharia: Futsal e Golzinho
    artilharia = []

    if modality and modality.name.strip().lower() in ("futsal", "golzinho"):
        gols_por_atleta = (
            db.session.query(
                OlympicAthlete.id.label("athlete_id"),
                OlympicAthlete.name.label("athlete_name"),
                OlympicTeam.name.label("team_name"),
                OlympicTeam.coach.label("coach"),
                func.sum(OlympicMatchGoal.goals).label("total_goals")
            )
            .join(
                OlympicMatchGoal,
                OlympicMatchGoal.athlete_id == OlympicAthlete.id
            )
            .join(
                OlympicMatch,
                OlympicMatch.id == OlympicMatchGoal.match_id
            )
            .join(
                OlympicTeam,
                OlympicTeam.id == OlympicAthlete.team_id
            )
            .filter(
                OlympicMatch.edition_id == edition_id,
                OlympicMatch.modality_id == modality_id,
                func.upper(OlympicMatch.shift) == shift.strip().upper(),
                OlympicMatch.phase == "CLASSIFICATORIA",
                OlympicMatch.status == "FINALIZADO",
                OlympicMatchGoal.goals > 0
            )
            .group_by(
                OlympicAthlete.id,
                OlympicAthlete.name,
                OlympicTeam.name,
                OlympicTeam.coach
            )
            .order_by(
                func.sum(OlympicMatchGoal.goals).desc(),
                OlympicAthlete.name.asc()
            )
            .all()
        )

        artilharia = [
            {
                "position": position,
                "athlete_name": item.athlete_name,
                "team_name": item.team_name,
                "coach": item.coach,
                "goals": int(item.total_goals)
            }
            for position, item in enumerate(gols_por_atleta, start=1)
        ]


    return render_template(
        "admin_olympic_classification.html",
        edition_id=edition_id,
        modality_id=modality_id,
        modality_name=modality.name if modality else "Modalidade",
        shift=shift,
        classification=classification,
        artilharia=artilharia
    )

# ==========================================
# OLIMPÍADAS - PARTICIPANTES POR CONFRONTO
# ==========================================

class OlympicMatchParticipant(db.Model):
    __tablename__ = "olympic_match_participants"

    id = db.Column(db.Integer, primary_key=True)

    match_id = db.Column(
        db.Integer,
        db.ForeignKey("olympic_matches.id"),
        nullable=False,
        index=True
    )

    athlete_id = db.Column(
        db.Integer,
        db.ForeignKey("olympic_athletes.id"),
        nullable=False,
        index=True
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )

    match = db.relationship("OlympicMatch")
    athlete = db.relationship("OlympicAthlete")

    __table_args__ = (
        db.UniqueConstraint(
            "match_id",
            "athlete_id",
            name="uq_olympic_match_participant"
        ),
    )    

# ==========================================
# OLIMPÍADAS - GOLS POR ATLETA
# ==========================================

class OlympicMatchGoal(db.Model):
    __tablename__ = "olympic_match_goals"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    match_id = db.Column(
        db.Integer,
        db.ForeignKey("olympic_matches.id"),
        nullable=False,
        index=True
    )

    athlete_id = db.Column(
        db.Integer,
        db.ForeignKey("olympic_athletes.id"),
        nullable=False,
        index=True
    )

    goals = db.Column(
        db.Integer,
        nullable=False,
        default=0
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )

    match = db.relationship(
        "OlympicMatch",
        backref=db.backref(
            "athlete_goals",
            lazy=True,
            cascade="all, delete-orphan"
        )
    )

    athlete = db.relationship(
        "OlympicAthlete"
    )

    __table_args__ = (
        db.UniqueConstraint(
            "match_id",
            "athlete_id",
            name="uq_olympic_match_goal_athlete"
        ),
        db.CheckConstraint(
            "goals >= 0",
            name="ck_olympic_match_goals_nonnegative"
        ),
    )
    
# ==========================================
# OLIMPÍADAS - TENTATIVAS POR ATLETA
# BASQUETE E PÊNALTIS
# ==========================================

class OlympicMatchAttempt(db.Model):
    __tablename__ = "olympic_match_attempts"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    match_id = db.Column(
        db.Integer,
        db.ForeignKey("olympic_matches.id"),
        nullable=False,
        index=True
    )

    athlete_id = db.Column(
        db.Integer,
        db.ForeignKey("olympic_athletes.id"),
        nullable=False,
        index=True
    )

    attempt_number = db.Column(
        db.Integer,
        nullable=False
    )

    successful = db.Column(
        db.Boolean,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )

    match = db.relationship(
        "OlympicMatch",
        backref=db.backref(
            "athlete_attempts",
            lazy=True,
            cascade="all, delete-orphan"
        )
    )

    athlete = db.relationship(
        "OlympicAthlete"
    )

    __table_args__ = (
        db.UniqueConstraint(
            "match_id",
            "athlete_id",
            "attempt_number",
            name="uq_olympic_match_athlete_attempt"
        ),
        db.CheckConstraint(
            "attempt_number BETWEEN 1 AND 5",
            name="ck_olympic_match_attempt_number"
        ),
    )    

# ==========================================
# OLIMPÍADAS - CONFIGURAÇÕES DO CALENDÁRIO
# ==========================================

class OlympicCalendarSettings(db.Model):
    __tablename__ = "olympic_calendar_settings"

    id = db.Column(db.Integer, primary_key=True)

    edition_id = db.Column(
        db.Integer,
        db.ForeignKey("olympic_editions.id"),
        nullable=False,
        unique=True
    )

    # Intervalo entre confrontos
    interval_minutes = db.Column(
        db.Integer,
        nullable=False,
        default=5
    )

    rest_minutes = db.Column(db.Integer, nullable=False, default=10)

    game_weekdays = db.Column(
        db.JSON,
        nullable=False,
        default=lambda: [0, 2]
    )

    allow_simultaneous_matches = db.Column(db.Boolean, nullable=False, default=False)

    # Horários do turno matutino
    morning_start = db.Column(db.Time, nullable=True)
    morning_end = db.Column(db.Time, nullable=True)

    # Horários do turno vespertino
    afternoon_start = db.Column(db.Time, nullable=True)
    afternoon_end = db.Column(db.Time, nullable=True)
    
    # Horários sem jogos — lanche / intervalo
    morning_break_start = db.Column(db.Time, nullable=True)
    morning_break_end = db.Column(db.Time, nullable=True)

    afternoon_break_start = db.Column(db.Time, nullable=True)
    afternoon_break_end = db.Column(db.Time, nullable=True)

    # Intervalo do lanche - matutino
    morning_break_start = db.Column(db.Time, nullable=True)
    morning_break_end = db.Column(db.Time, nullable=True)

    # Intervalo do lanche - vespertino
    afternoon_break_start = db.Column(db.Time, nullable=True)
    afternoon_break_end = db.Column(db.Time, nullable=True)

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )

    edition = db.relationship(
        "OlympicEdition",
        backref=db.backref(
            "calendar_settings",
            uselist=False
        )
    )

    __table_args__ = (
        db.CheckConstraint(
            "interval_minutes >= 0",
            name="ck_olympic_calendar_interval"
        ),
        db.CheckConstraint(
            "rest_minutes >= 0",
            name="ck_olympic_calendar_rest"
        ),
    )


def generate_olympic_round_robin_pairs(teams):
    """
    Gera confrontos de turno único:
    cada equipe enfrenta todas as outras uma vez.
    Não grava dados no banco.
    """
    pairs = []

    ordered_teams = sorted(
        teams,
        key=lambda team: team.id
    )

    for i in range(len(ordered_teams)):
        for j in range(i + 1, len(ordered_teams)):
            pairs.append((
                ordered_teams[i],
                ordered_teams[j]
            ))

    return pairs


def generate_olympic_pairs_by_shift(teams):
    """
    Separa as equipes por turno e gera
    confrontos de turno único em cada grupo.
    Não grava dados no banco.
    """
    teams_by_shift = {}

    for team in teams:
        shift = (team.shift or "").strip().upper()

        if not shift:
            continue

        teams_by_shift.setdefault(shift, []).append(team)

    matches_by_shift = {}

    for shift, shift_teams in teams_by_shift.items():
        matches_by_shift[shift] = (
            generate_olympic_round_robin_pairs(shift_teams)
        )

    return matches_by_shift


def get_olympic_calendar_participants(edition_id):
    """
    Busca todas as equipes e modalidades ativas
    de uma edição e prepara os confrontos por turno.

    Não grava dados no banco.
    """

    teams = (
        OlympicTeam.query
        .filter_by(edition_id=edition_id)
        .order_by(OlympicTeam.id)
        .all()
    )

    modalities = (
        OlympicModality.query
        .filter_by(
            edition_id=edition_id,
            is_active=True
        )
        .order_by(OlympicModality.id)
        .all()
    )

    pairs_by_shift = generate_olympic_pairs_by_shift(teams)

    return {
        "teams": teams,
        "modalities": modalities,
        "pairs_by_shift": pairs_by_shift
    }


def get_olympic_available_dates(start_date, end_date, game_weekdays):
    """
    Retorna as datas disponíveis para os confrontos,
    respeitando os dias da semana configurados.

    Segunda-feira = 0
    Domingo = 6

    Não grava dados no banco.
    """

    if start_date > end_date:
        raise ValueError(
            "A data final não pode ser anterior à data inicial."
        )

    allowed_weekdays = set(game_weekdays or [])

    if not allowed_weekdays:
        raise ValueError(
            "Selecione pelo menos um dia da semana."
        )

    available_dates = []
    current_date = start_date

    while current_date <= end_date:

        if current_date.weekday() in allowed_weekdays:
            available_dates.append(current_date)

        current_date += timedelta(days=1)

    return available_dates


def get_olympic_available_times(
    shift_start,
    shift_end,
    match_duration_minutes,
    interval_minutes
):
    """
    Calcula os horários disponíveis em um turno.

    Cada confronto precisa terminar até o horário
    final do turno.

    Não grava dados no banco.
    """

    if match_duration_minutes <= 0:
        raise ValueError(
            "A duração do confronto deve ser maior que zero."
        )

    if interval_minutes < 0:
        raise ValueError(
            "O intervalo não pode ser negativo."
        )

    start_datetime = datetime.combine(
        date.today(),
        shift_start
    )

    end_datetime = datetime.combine(
        date.today(),
        shift_end
    )

    available_times = []

    current_datetime = start_datetime

    while (
        current_datetime + timedelta(
            minutes=match_duration_minutes
        ) <= end_datetime
    ):
        available_times.append(
            current_datetime.time()
        )

        current_datetime += timedelta(
            minutes=match_duration_minutes + interval_minutes
        )

    return available_times


def olympic_team_has_enough_rest(
    team_id,
    proposed_start,
    proposed_duration_minutes,
    scheduled_matches,
    rest_minutes
):
    """
    Verifica se uma equipe terá descanso suficiente
    entre o confronto proposto e os já agendados.

    proposed_start: datetime
    scheduled_matches: lista de dicionários contendo
        team_a_id, team_b_id, start e duration_minutes

    Não grava dados no banco.
    """

    if proposed_duration_minutes <= 0 or rest_minutes < 0:
        raise ValueError("Duração ou descanso inválido.")

    proposed_end = proposed_start + timedelta(
        minutes=proposed_duration_minutes
    )

    for match in scheduled_matches:

        if team_id not in (
            match["team_a_id"],
            match["team_b_id"]
        ):
            continue

        existing_start = match["start"]

        existing_end = existing_start + timedelta(
            minutes=match["duration_minutes"]
        )

        if (
            proposed_start < existing_end + timedelta(minutes=rest_minutes)
            and proposed_end + timedelta(minutes=rest_minutes) > existing_start
        ):
            return False

    return True


def olympic_team_within_daily_limit(
    team_id,
    modality_id,
    proposed_date,
    scheduled_matches,
    max_matches_per_team_per_day
):
    """
    Verifica se a equipe ainda pode disputar
    outro confronto da mesma modalidade no dia.

    scheduled_matches: lista de dicionários com:
        team_a_id, team_b_id, modality_id, start

    Não grava dados no banco.
    """

    if max_matches_per_team_per_day <= 0:
        raise ValueError(
            "O limite diário por equipe deve ser maior que zero."
        )

    matches_today = 0

    for match in scheduled_matches:

        if match["modality_id"] != modality_id:
            continue

        if match["start"].date() != proposed_date:
            continue

        if team_id in (
            match["team_a_id"],
            match["team_b_id"]
        ):
            matches_today += 1

    return matches_today < max_matches_per_team_per_day


def olympic_modality_within_daily_limit(
    modality_id,
    proposed_date,
    scheduled_matches,
    max_matches_per_modality_per_day
):
    """
    Verifica o limite total de confrontos
    de uma modalidade em determinado dia.

    Considera os dois turnos em conjunto.

    Um limite None significa sem restrição.
    Não grava dados no banco.
    """

    if max_matches_per_modality_per_day is None:
        return True

    if max_matches_per_modality_per_day <= 0:
        raise ValueError(
            "O limite diário da modalidade deve ser maior que zero."
        )

    matches_today = 0

    for match in scheduled_matches:

        if match["modality_id"] != modality_id:
            continue

        if match["start"].date() == proposed_date:
            matches_today += 1

    return matches_today < max_matches_per_modality_per_day


def olympic_time_slot_is_available(
    proposed_start,
    proposed_duration_minutes,
    scheduled_matches,
    interval_minutes,
    allow_simultaneous_matches
):
    """
    Verifica conflitos de horário entre confrontos.

    Quando confrontos simultâneos estão desativados,
    respeita também o intervalo mínimo entre jogos.

    Não grava dados no banco.
    """

    if proposed_duration_minutes <= 0 or interval_minutes < 0:
        raise ValueError("Duração ou intervalo inválido.")

    if allow_simultaneous_matches:
        return True

    proposed_end = proposed_start + timedelta(
        minutes=proposed_duration_minutes
    )

    for match in scheduled_matches:

        existing_start = match["start"]

        # Confrontos de datas diferentes não entram em conflito.
        if existing_start.date() != proposed_start.date():
            continue

        existing_end = existing_start + timedelta(
            minutes=match["duration_minutes"]
        )

        interval = timedelta(minutes=interval_minutes)

        if (
            proposed_start < existing_end + interval
            and proposed_end + interval > existing_start
        ):
            return False

    return True


def prepare_olympic_classification_matches(edition_id):
    """
    Prepara os confrontos classificatórios de turno único
    para todas as modalidades ativas.

    Não define datas nem horários.
    Não grava dados no banco.
    """

    participants = get_olympic_calendar_participants(edition_id)

    modalities = participants["modalities"]
    pairs_by_shift = participants["pairs_by_shift"]

    prepared_matches = []

    for modality in modalities:
        for shift, pairs in pairs_by_shift.items():
            for team_a, team_b in pairs:
                prepared_matches.append({
                    "edition_id": edition_id,
                    "modality_id": modality.id,
                    "team_a_id": team_a.id,
                    "team_b_id": team_b.id,
                    "shift": shift,
                    "phase": "CLASSIFICATORIA",
                    "duration_minutes": modality.match_duration_minutes,
                    "max_matches_per_team_per_day":
                        modality.max_matches_per_team_per_day,
                    "max_matches_per_modality_per_day":
                        modality.max_matches_per_modality_per_day
                })

    return prepared_matches


def get_olympic_shift_window(settings, shift):
    """
    Retorna os horários de início e fim de um turno.

    Aceita as identificações MATUTINO e VESPERTINO,
    além de MANHA e TARDE.

    Não altera dados no banco.
    """

    normalized_shift = (shift or "").strip().upper()

    if normalized_shift in ("MATUTINO", "MANHA", "MANHÃ"):
        shift_start = settings.morning_start
        shift_end = settings.morning_end

    elif normalized_shift in ("VESPERTINO", "TARDE"):
        shift_start = settings.afternoon_start
        shift_end = settings.afternoon_end

    else:
        raise ValueError(
            f"Turno não reconhecido: {shift}"
        )

    if shift_start is None or shift_end is None:
        raise ValueError(
            f"Os horários do turno {shift} não estão configurados."
        )

    if shift_start >= shift_end:
        raise ValueError(
            f"O horário inicial do turno {shift} "
            "deve ser anterior ao horário final."
        )

    return shift_start, shift_end


def get_olympic_match_duration(match):
    """
    Obtém e valida a duração de um confronto preparado.

    Não grava dados no banco.
    """

    duration = match.get("duration_minutes")

    if duration is None:
        raise ValueError(
            f"A modalidade de ID {match['modality_id']} "
            "não possui duração configurada."
        )

    try:
        duration = int(duration)
    except (TypeError, ValueError):
        raise ValueError(
            f"Duração inválida para a modalidade "
            f"de ID {match['modality_id']}."
        )

    if duration <= 0:
        raise ValueError(
            f"A duração da modalidade de ID "
            f"{match['modality_id']} deve ser maior que zero."
        )

    return duration

def count_olympic_team_daily_matches(
    team_id,
    game_date,
    scheduled_matches
):
    """
    Conta todos os confrontos de uma equipe
    em determinada data, independentemente
    da modalidade.

    Considera confrontos existentes e aqueles
    adicionados à prévia do calendário.
    """

    return sum(
        1
        for match in scheduled_matches
        if match["start"].date() == game_date
        and team_id in (
            match["team_a_id"],
            match["team_b_id"]
        )
    )

def find_olympic_match_slot(
    match,
    available_dates,
    settings,
    scheduled_matches,
    break_times=None
):
    """
    Encontra uma data e um horário válidos para o confronto.

    Retorna um datetime ou None se não houver vaga.
    Não grava dados no banco.
    """

    duration = get_olympic_match_duration(match)

    shift_start, shift_end = get_olympic_shift_window(
        settings,
        match["shift"]
    )

    interval_minutes = settings.interval_minutes
    rest_minutes = settings.rest_minutes

    # Prioriza datas com menor quantidade de jogos
    # para as duas equipes envolvidas no confronto.

    def daily_balance_score(game_date):

        team_a_games = count_olympic_team_daily_matches(
            match["team_a_id"],
            game_date,
            scheduled_matches
        )

        team_b_games = count_olympic_team_daily_matches(
            match["team_b_id"],
            game_date,
            scheduled_matches
        )

        return (
            max(team_a_games, team_b_games),
            team_a_games + team_b_games
        )

    balanced_dates = sorted(
        available_dates,
        key=daily_balance_score
    )

    for game_date in balanced_dates:

        if not olympic_modality_within_daily_limit(
            match["modality_id"],
            game_date,
            scheduled_matches,
            match["max_matches_per_modality_per_day"]
        ):
            continue

        if not all(
            olympic_team_within_daily_limit(
                team_id,
                match["modality_id"],
                game_date,
                scheduled_matches,
                match["max_matches_per_team_per_day"]
            )
            for team_id in (
                match["team_a_id"],
                match["team_b_id"]
            )
        ):
            continue

        current = datetime.combine(game_date, shift_start)
        window_end = datetime.combine(game_date, shift_end)

        # Intervalo sem jogos definido para este turno
        # Normaliza o turno para localizar o intervalo de lanche
        normalized_shift = (match["shift"] or "").strip().upper()

        if normalized_shift in ("MANHA", "MANHÃ"):
            normalized_shift = "MATUTINO"

        elif normalized_shift == "TARDE":
            normalized_shift = "VESPERTINO"

        shift_break = (break_times or {}).get(normalized_shift)

        break_start = None
        break_end = None

        if shift_break:
            break_start = datetime.combine(
                game_date,
                shift_break[0]
            )
            break_end = datetime.combine(
                game_date,
                shift_break[1]
            )

        while current + timedelta(minutes=duration) <= window_end:

            # Não permite confrontos durante o intervalo
            if (
                break_start is not None
                and current < break_end
                and current + timedelta(minutes=duration) > break_start
            ):
                current = break_end
                continue

            if olympic_time_slot_is_available(
                current,
                duration,
                scheduled_matches,
                interval_minutes,
                settings.allow_simultaneous_matches
            ):

                if all(
                    olympic_team_has_enough_rest(
                        team_id,
                        current,
                        duration,
                        scheduled_matches,
                        rest_minutes
                    )
                    for team_id in (
                        match["team_a_id"],
                        match["team_b_id"]
                    )
                ):
                    return current

            current += timedelta(minutes=1)

    return None



def build_olympic_calendar(
    prepared_matches,
    available_dates,
    settings,
    existing_matches=None,
    break_times=None
):
    """
    Distribui novos confrontos nas datas disponíveis.

    Considera os confrontos existentes para evitar
    conflitos de horários, descanso e limites diários.

    Não grava dados no banco.
    """

    scheduled_matches = list(existing_matches or [])
    new_scheduled_matches = []
    unscheduled_matches = []

    for match in prepared_matches:

        start = find_olympic_match_slot(
            match,
            available_dates,
            settings,
            scheduled_matches,
            break_times=break_times
        )

        if start is None:
            unscheduled_matches.append(match.copy())
            continue

        scheduled_match = match.copy()

        scheduled_match["start"] = start
        scheduled_match["duration_minutes"] = (
            get_olympic_match_duration(match)
        )

        scheduled_matches.append(scheduled_match)
        new_scheduled_matches.append(scheduled_match)

    return {
        "scheduled_matches": new_scheduled_matches,
        "unscheduled_matches": unscheduled_matches
    }



def get_existing_olympic_match_keys(edition_id):
    """
    Identifica os confrontos classificatórios já
    cadastrados na edição.

    A ordem das equipes não altera a identificação.
    Não modifica dados no banco.
    """

    
    existing_matches = OlympicMatch.query.filter(
        OlympicMatch.edition_id == edition_id,
        OlympicMatch.phase == "CLASSIFICATORIA",
        OlympicMatch.status != "CANCELADO"
    ).all()


    existing_keys = set()

    for match in existing_matches:
        team_ids = tuple(sorted((
            match.team_a_id,
            match.team_b_id
        )))

        existing_keys.add((
            match.modality_id,
            team_ids
        ))

    return existing_keys


def filter_new_olympic_matches(
    edition_id,
    prepared_matches
):
    """
    Remove da lista os confrontos classificatórios
    que já estão cadastrados no banco de dados.

    Preserva os confrontos existentes.
    Não grava nem altera dados no banco.
    """

    existing_keys = get_existing_olympic_match_keys(
        edition_id
    )

    new_matches = []
    skipped_matches = []

    for match in prepared_matches:

        team_ids = tuple(sorted((
            match["team_a_id"],
            match["team_b_id"]
        )))

        match_key = (
            match["modality_id"],
            team_ids
        )

        if match_key in existing_keys:
            skipped_matches.append(match.copy())
            continue

        new_matches.append(match.copy())

        # Evita duplicações dentro da própria lista.
        existing_keys.add(match_key)

    return {
        "new_matches": new_matches,
        "skipped_matches": skipped_matches
    }


def get_existing_olympic_scheduled_matches(edition_id):
    """
    Carrega os confrontos existentes para que o gerador
    respeite seus horários, descanso e limites diários.

    Não modifica dados no banco.
    """

    existing_matches = OlympicMatch.query.filter_by(
        edition_id=edition_id
    ).all()

    scheduled_matches = []

    
    for match in existing_matches:

        # Jogos finalizados ou cancelados não ocupam
        # horários na nova geração do calendário.
        if match.status in ("FINALIZADO", "CANCELADO"):
            continue

        if match.match_date is None or match.match_time is None:
            continue


        duration = match.modality.match_duration_minutes

        if duration is None or duration <= 0:
            raise ValueError(
                f"O confronto de ID {match.id} possui "
                "uma modalidade sem duração válida."
            )

        scheduled_matches.append({
            "match_id": match.id,
            "modality_id": match.modality_id,
            "team_a_id": match.team_a_id,
            "team_b_id": match.team_b_id,
            "shift": match.shift,
            "start": datetime.combine(
                match.match_date,
                match.match_time
            ),
            "duration_minutes": duration,
            "existing": True
        })

    return scheduled_matches


def generate_olympic_calendar_preview(
    edition_id,
    start_date,
    end_date,
    break_times=None
):
    """
    Monta uma prévia completa do calendário olímpico.

    Respeita as configurações da edição e os
    confrontos já cadastrados.

    Não grava nem altera dados no banco.
    """

    settings = OlympicCalendarSettings.query.filter_by(
        edition_id=edition_id
    ).first()

    if settings is None:
        raise ValueError(
            "Configure o calendário antes de gerar os confrontos."
        )

    available_dates = get_olympic_available_dates(
        start_date,
        end_date,
        settings.game_weekdays
    )

    if not available_dates:
        raise ValueError(
            "Não existem dias permitidos no período informado."
        )

    prepared_matches = prepare_olympic_classification_matches(
        edition_id
    )

    filtered = filter_new_olympic_matches(
        edition_id,
        prepared_matches
    )

    existing_matches = get_existing_olympic_scheduled_matches(
        edition_id
    )

    result = build_olympic_calendar(
        filtered["new_matches"],
        available_dates,
        settings,
        existing_matches,
        break_times=break_times
    )

    return {
        "scheduled_matches": result["scheduled_matches"],
        "unscheduled_matches": result["unscheduled_matches"],
        "skipped_matches": filtered["skipped_matches"],
        "existing_matches_count": len(existing_matches)
    }



# =========================
# PASSEIOS / EVENTOS
# =========================

class TripEvent(db.Model):
    __tablename__ = "trip_events"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    title = db.Column(
        db.String(200),
        nullable=False
    )

    slug = db.Column(
        db.String(255),
        nullable=False,
        unique=True,
        index=True
    )

    description = db.Column(
        db.Text,
        nullable=True
    )

    destination = db.Column(
        db.String(200),
        nullable=True
    )

    event_date = db.Column(
        db.Date,
        nullable=False
    )

    departure_time = db.Column(
        db.Time,
        nullable=True
    )

    return_time = db.Column(
        db.Time,
        nullable=True
    )

    price = db.Column(
        db.Float,
        nullable=False,
        default=0
    )

    max_spots = db.Column(
        db.Integer,
        nullable=True
    )

    registration_deadline = db.Column(
        db.DateTime,
        nullable=True
    )

    payment_instructions = db.Column(
        db.Text,
        nullable=True
    )
    
    pix_key = db.Column(
        db.String(255),
        nullable=True
    )

    pix_key_type = db.Column(
        db.String(30),
        nullable=True
    )

    pix_receiver_name = db.Column(
        db.String(100),
        nullable=True
    )

    pix_receiver_city = db.Column(
        db.String(100),
        nullable=True
    )

    banner = db.Column(
        db.String(500),
        nullable=True
    )

    is_active = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        index=True
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )

    registrations = db.relationship(
        "TripRegistration",
        backref="trip",
        lazy=True,
        cascade="all, delete-orphan"
    )
    
    required_fields = db.Column(
        db.JSON,
        nullable=True
    )


class TripRegistration(db.Model):
    __tablename__ = "trip_registrations"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    trip_id = db.Column(
        db.Integer,
        db.ForeignKey("trip_events.id"),
        nullable=False,
        index=True
    )

    student_name = db.Column(db.String(200), nullable=True)
    guardian_name = db.Column(db.String(200), nullable=True)
    age = db.Column(db.Integer, nullable=True)
    platoon = db.Column(db.String(30), nullable=True, index=True)
    shift = db.Column(db.String(20), nullable=True, index=True)
    
    transport_route = db.Column(
        db.String(50),
        nullable=True,
        index=True
    )

    guardian_whatsapp = db.Column(db.String(30), nullable=True)

    payment_receipt = db.Column(
        db.String(500),
        nullable=True
    )

    payment_status = db.Column(
        db.String(20),
        nullable=False,
        default="PENDENTE",
        index=True
    )

    registration_status = db.Column(
        db.String(30),
        nullable=False,
        default="AGUARDANDO_PAGAMENTO",
        index=True
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )    
    
# =========================
# EMPREGOS / ESTÁGIOS
# =========================

class JobVacancy(db.Model):
    __tablename__ = "job_vacancies"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    # Identificação da origem
    source = db.Column(
        db.String(50),
        nullable=False,
        default="CATLOGIN",
        index=True
    )

    external_id = db.Column(
        db.String(255),
        nullable=True,
        index=True
    )

    # Dados principais
    title = db.Column(
        db.String(255),
        nullable=False,
        index=True
    )

    company = db.Column(
        db.String(255),
        nullable=True,
        index=True
    )

    description = db.Column(
        db.Text,
        nullable=True
    )

    # Localização
    country = db.Column(
        db.String(100),
        nullable=True,
        default="Brasil"
    )

    state = db.Column(
        db.String(100),
        nullable=True,
        index=True
    )

    city = db.Column(
        db.String(150),
        nullable=True,
        index=True
    )

    location_text = db.Column(
        db.String(255),
        nullable=True
    )

    # Informações da vaga
    job_type = db.Column(
        db.String(50),
        nullable=True,
        index=True
    )

    work_model = db.Column(
        db.String(30),
        nullable=True,
        index=True
    )

    salary = db.Column(
        db.String(150),
        nullable=True
    )

    # Link externo da vaga
    external_url = db.Column(
        db.String(1000),
        nullable=True
    )

    # Contato para vagas próprias do CataLogin
    contact_email = db.Column(
        db.String(255),
        nullable=True
    )

    contact_whatsapp = db.Column(
        db.String(30),
        nullable=True
    )

    # Controle
    is_active = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        index=True
    )

    is_featured = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        index=True
    )

    # Datas
    published_at = db.Column(
        db.DateTime,
        nullable=True,
        index=True
    )

    expires_at = db.Column(
        db.DateTime,
        nullable=True,
        index=True
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True
    )

    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )    

class SiteVisitor(db.Model):
    __tablename__ = "site_visitors"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    visitor_id = db.Column(
        db.String(100),
        nullable=False,
        unique=True,
        index=True
    )

    first_visit_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True
    )

    last_visit_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True
    )


class SearchMetric(db.Model):
    __tablename__ = "search_metrics"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    visitor_id = db.Column(
        db.String(100),
        nullable=True,
        index=True
    )

    search_term = db.Column(
        db.String(255),
        nullable=True,
        index=True
    )

    searched_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True
    )
    
def classify_job_type(title, jooble_type):
    text = (
        f"{title or ''} {jooble_type or ''}"
    ).upper()

    if (
        "ESTÁGIO" in text
        or "ESTAGIO" in text
        or "ESTAGIÁRIO" in text
        or "ESTAGIARIO" in text
    ):
        return "ESTAGIO"

    if (
        "APRENDIZ" in text
        or "JOVEM APRENDIZ" in text
    ):
        return "JOVEM_APRENDIZ"

    if "TEMPORÁRIO" in text or "TEMPORARIO" in text:
        return "TEMPORARIO"

    if "FREELANCER" in text or "FREELA" in text:
        return "FREELANCER"

    return "EMPREGO"


def clean_job_description(value):
    text = str(value or "")

    text = re.sub(
        r"<[^>]+>",
        "",
        text
    )

    text = (
        text
        .replace("&nbsp;", " ")
        .replace("&amp;", "&")
    )

    return " ".join(
        text.split()
    ) 

EXTERNAL_JOB_MAX_AGE_DAYS = 30


def deactivate_old_external_jobs():
    cutoff_date = (
        utc_now()
        - timedelta(
            days=EXTERNAL_JOB_MAX_AGE_DAYS
        )
    )

    old_jobs = (
        JobVacancy.query
        .filter(
            JobVacancy.source.in_(
                [
                    "JOOBLE",
                    "ADZUNA",
                    "JSEARCH"
                ]
            ),
            JobVacancy.is_active.is_(True),
            JobVacancy.published_at.isnot(None),
            JobVacancy.published_at < cutoff_date
        )
        .all()
    )

    deactivated = 0

    for vacancy in old_jobs:
        vacancy.is_active = False
        deactivated += 1

    return deactivated

JOOBLE_AUTO_SEARCHES = [
    {
        "keywords": "administrativo",
        "location": "Brasilia"
    },
    {
        "keywords": "estagio",
        "location": "Brasilia"
    },
    {
        "keywords": "jovem aprendiz",
        "location": "Brasilia"
    },
    {
        "keywords": "vendas",
        "location": "Brasilia"
    }
]


ADZUNA_AUTO_SEARCHES = [
    {
        "keywords": "administrativo",
        "location": "Brasilia"
    },
    {
        "keywords": "estagio",
        "location": "Brasilia"
    },
    {
        "keywords": "atendimento",
        "location": "Brasilia"
    },
    {
        "keywords": "logistica",
        "location": "Brasilia"
    },
    {
        "keywords": "tecnologia",
        "location": "Brasilia"
    }
]

# =========================
# JSEARCH - PESQUISAS AUTOMÁTICAS
# =========================

JSEARCH_AUTO_SEARCHES = [
    {
        "query": "auxiliar administrativo em Brasilia DF Brazil"
    },
    {
        "query": "atendente em Brasilia DF Brazil"
    },
    {
        "query": "vendedor em Brasilia DF Brazil"
    },
    {
        "query": "estagio em Brasilia DF Brazil"
    },
    {
        "query": "jovem aprendiz em Brasilia DF Brazil"
    }
]

def import_jooble_search(
    keywords,
    location
):
    payload = {
        "keywords": keywords,
        "location": location,
        "page": "1"
    }

    result = jooble_request(
        payload
    )

    jobs = (
        result.get("jobs")
        or []
    )

    created = 0
    updated = 0
    ignored = 0

    for item in jobs:

        external_id = str(
            item.get("id")
            or ""
        ).strip()

        if not external_id:
            ignored += 1
            continue

        title = (
            item.get("title")
            or ""
        ).strip()

        if not title:
            ignored += 1
            continue

        company = (
            item.get("company")
            or ""
        ).strip()

        location_text = (
            item.get("location")
            or ""
        ).strip()

        city = None
        state = None

        if location_text:
            parts = [
                part.strip()
                for part
                in location_text.split(",")
                if part.strip()
            ]

            if parts:
                city = parts[0]

            if len(parts) > 1:
                state = parts[-1]

        description = (
            clean_job_description(
                item.get("snippet")
            )
        )

        salary = (
            item.get("salary")
            or ""
        ).strip()

        external_url = (
            item.get("link")
            or ""
        ).strip()

        jooble_type = (
            item.get("type")
            or ""
        ).strip()

        job_type = classify_job_type(
            title,
            jooble_type
        )

        published_at = None

        updated_raw = (
            item.get("updated")
            or ""
        ).strip()

        if updated_raw:
            try:
                published_at = (
                    datetime.fromisoformat(
                        updated_raw.replace(
                            "Z",
                            "+00:00"
                        )
                    )
                )

                if (
                    published_at.tzinfo
                    is not None
                ):
                    published_at = (
                        published_at.replace(
                            tzinfo=None
                        )
                    )

            except Exception:
                published_at = utc_now()

        existing = (
            JobVacancy.query
            .filter_by(
                source="JOOBLE",
                external_id=external_id
            )
            .first()
        )

        if existing:

            existing.title = title
            existing.company = (
                company or None
            )
            existing.description = (
                description or None
            )
            existing.country = "Brasil"
            existing.state = state
            existing.city = city
            existing.location_text = (
                location_text or None
            )
            existing.job_type = job_type
            existing.salary = (
                salary or None
            )
            existing.external_url = (
                external_url or None
            )
            existing.published_at = (
                published_at
            )
            existing.is_active = True

            updated += 1

            continue
            
        cross_duplicate = (
            find_cross_source_job_duplicate(
                source="JOOBLE",
                title=title,
                company=company,
                city=city
            )
        )

        if cross_duplicate:

            print(
                "DUPLICATA ENTRE APIS IGNORADA:",
                "JOOBLE",
                "->",
                cross_duplicate.source,
                "|",
                title,
                "|",
                company,
                "|",
                city,
                flush=True
            )

            ignored += 1
            continue    

        vacancy = JobVacancy(
            source="JOOBLE",
            external_id=external_id,
            title=title,
            company=company or None,
            description=description or None,
            country="Brasil",
            state=state,
            city=city,
            location_text=(
                location_text or None
            ),
            job_type=job_type,
            work_model=None,
            salary=salary or None,
            external_url=(
                external_url or None
            ),
            is_active=True,
            is_featured=False,
            published_at=published_at
        )

        db.session.add(vacancy)

        created += 1

    return {
        "received": len(jobs),
        "created": created,
        "updated": updated,
        "ignored": ignored
    }
    
def run_automatic_job_import():

    summary = {
        "searches": 0,
        "received": 0,
        "created": 0,
        "updated": 0,
        "ignored": 0,

        "jooble": {
            "searches": 0,
            "received": 0,
            "created": 0,
            "updated": 0,
            "ignored": 0,
            "error": None
        },

        "adzuna": {
            "searches": 0,
            "received": 0,
            "created": 0,
            "updated": 0,
            "ignored": 0,
            "error": None
        },

        "jsearch": {
            "searches": 0,
            "received": 0,
            "created": 0,
            "updated": 0,
            "ignored": 0,
            "error": None
        }
    }

    # =========================
    # JOOBLE
    # =========================

    for search in JOOBLE_AUTO_SEARCHES:

        try:
            result = import_jooble_search(
                keywords=search["keywords"],
                location=search["location"]
            )

            summary["jooble"]["searches"] += 1
            summary["jooble"]["received"] += (
                result["received"]
            )
            summary["jooble"]["created"] += (
                result["created"]
            )
            summary["jooble"]["updated"] += (
                result["updated"]
            )
            summary["jooble"]["ignored"] += (
                result["ignored"]
            )

        except Exception as error:

            db.session.rollback()

            print(
                "ERRO JOOBLE AUTOMÁTICA:",
                search,
                repr(error),
                flush=True
            )

            summary["jooble"]["error"] = str(
                error
            )

            break

    # =========================
    # ADZUNA
    # =========================

    for search in ADZUNA_AUTO_SEARCHES:

        try:
            result = import_adzuna_search(
                keywords=search["keywords"],
                location=search["location"],
                page=1,
                results_per_page=30
            )

            summary["adzuna"]["searches"] += 1
            summary["adzuna"]["received"] += (
                result["received"]
            )
            summary["adzuna"]["created"] += (
                result["created"]
            )
            summary["adzuna"]["updated"] += (
                result["updated"]
            )
            summary["adzuna"]["ignored"] += (
                result["ignored"]
            )

        except Exception as error:

            db.session.rollback()

            print(
                "ERRO ADZUNA AUTOMÁTICA:",
                search,
                repr(error),
                flush=True
            )

            summary["adzuna"]["error"] = str(
                error
            )

            break

    # =========================
    # JSEARCH
    # =========================

    for search in JSEARCH_AUTO_SEARCHES:

        try:
            result = import_jsearch_search(
                query=search["query"],
                num_pages=1,
                country="br",
                language="pt",
                location=(
                    "Brasilia, Distrito Federal, Brazil"
                ),
                date_posted="all"
            )

            summary["jsearch"]["searches"] += 1
            summary["jsearch"]["received"] += (
                result["received"]
            )
            summary["jsearch"]["created"] += (
                result["created"]
            )
            summary["jsearch"]["updated"] += (
                result["updated"]
            )
            summary["jsearch"]["ignored"] += (
                result["ignored"]
            )

        except Exception as error:

            db.session.rollback()

            print(
                "ERRO JSEARCH AUTOMÁTICA:",
                search,
                repr(error),
                flush=True
            )

            summary["jsearch"]["error"] = str(
                error
            )

            break

    # =========================
    # TOTAL GERAL
    # =========================

    for source in (
        "jooble",
        "adzuna",
        "jsearch"
    ):
        summary["searches"] += (
            summary[source]["searches"]
        )

        summary["received"] += (
            summary[source]["received"]
        )

        summary["created"] += (
            summary[source]["created"]
        )

        summary["updated"] += (
            summary[source]["updated"]
        )

        summary["ignored"] += (
            summary[source]["ignored"]
        )

    # =========================
    # LIMPEZA DE VAGAS ANTIGAS
    # =========================

    deactivated = (
        deactivate_old_external_jobs()
    )

    summary["deactivated"] = (
        deactivated
    )

    db.session.commit()

    return summary
    
class AffiliateStore(db.Model):
    __tablename__ = "affiliate_stores"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    name = db.Column(
        db.String(120),
        nullable=False
    )

    logo_url = db.Column(
        db.Text,
        nullable=True
    )

    affiliate_url = db.Column(
        db.Text,
        nullable=False
    )

    is_active = db.Column(
        db.Boolean,
        nullable=False,
        default=True
    )

    display_order = db.Column(
        db.Integer,
        nullable=False,
        default=0
    )

    click_count = db.Column(
        db.Integer,
        nullable=False,
        default=0
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )    
    
class AffiliateProduct(db.Model):
    __tablename__ = "affiliate_products"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    title = db.Column(
        db.String(255),
        nullable=False
    )

    store = db.Column(
        db.String(120),
        nullable=True
    )

    category = db.Column(
        db.String(120),
        nullable=True
    )

    description = db.Column(
        db.Text,
        nullable=True
    )

    image_url = db.Column(
        db.Text,
        nullable=True
    )

    affiliate_url = db.Column(
        db.Text,
        nullable=False
    )
    
    external_product_id = db.Column(
        db.String(100),
        nullable=True,
        index=True
    )

    store_code = db.Column(
        db.String(50),
        nullable=True,
        index=True
    )

    
    old_price = db.Column(
        db.Numeric(10, 2),
        nullable=True
    )

    price = db.Column(
        db.Numeric(10, 2),
        nullable=True
    )

    is_active = db.Column(
        db.Boolean,
        default=True,
        nullable=False
    )

    is_featured = db.Column(
        db.Boolean,
        default=False,
        nullable=False
    )

    expires_at = db.Column(
        db.DateTime,
        nullable=True
    )

    click_count = db.Column(
        db.Integer,
        default=0,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )   

# =========================
# HELPERS
# =========================

def get_cached_location(category, key=None):
    now = time.time()

    with LOCATION_CACHE_LOCK:
        if key is None:
            cached_item = LOCATION_CACHE.get(
                category
            )
        else:
            cached_item = (
                LOCATION_CACHE
                .get(category, {})
                .get(key)
            )

        if not cached_item:
            return None

        expires_at = cached_item.get(
            "expires_at",
            0
        )

        if expires_at <= now:
            if key is None:
                LOCATION_CACHE[category] = {
                    "data": None,
                    "expires_at": 0
                }
            else:
                LOCATION_CACHE.get(
                    category,
                    {}
                ).pop(key, None)

            return None

        return cached_item.get("data")


def set_cached_location(
    category,
    data,
    ttl_seconds,
    key=None
):
    cached_item = {
        "data": data,
        "expires_at": (
            time.time() + ttl_seconds
        )
    }

    with LOCATION_CACHE_LOCK:
        if key is None:
            LOCATION_CACHE[category] = (
                cached_item
            )
        else:
            LOCATION_CACHE.setdefault(
                category,
                {}
            )[key] = cached_item

def generate_reset_token():
    return secrets.token_urlsafe(32)


def hash_reset_token(raw_token):
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    
def utc_now():
    return datetime.now(UTC).replace(tzinfo=None) 

def brasilia_now():
    return datetime.now(
        ZoneInfo("America/Sao_Paulo")
    ).replace(tzinfo=None)    
    


def format_job_age(published_at):
    if not published_at:
        return ""

    now = utc_now()

    difference = now - published_at

    total_seconds = int(
        difference.total_seconds()
    )

    if total_seconds < 0:
        total_seconds = 0

    minutes = total_seconds // 60
    hours = total_seconds // 3600
    days = total_seconds // 86400

    if minutes < 1:
        return "Publicado agora"

    if minutes < 60:
        if minutes == 1:
            return "Publicado há 1 minuto"

        return (
            f"Publicado há {minutes} minutos"
        )

    if hours < 24:
        if hours == 1:
            return "Publicado há 1 hora"

        return (
            f"Publicado há {hours} horas"
        )

    if days == 1:
        return "Publicado há 1 dia"

    return (
        f"Publicado há {days} dias"
    )  

app.jinja_env.globals[
    "format_job_age"
] = format_job_age  

def normalize_job_search_text(value):
    value = str(value or "").strip().lower()

    value = unicodedata.normalize(
        "NFKD",
        value
    )

    value = "".join(
        char
        for char in value
        if not unicodedata.combining(char)
    )

    return " ".join(
        value.split()
    )


def normalized_job_column(column):
    return func.lower(
        func.translate(
            column,
            "áàâãäéèêëíìîïóòôõöúùûüçÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ",
            "aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC"
        )
    )  
    
def find_cross_source_job_duplicate(
    source,
    title,
    company,
    city
):
    source = (
        str(source or "")
        .strip()
        .upper()
    )

    # Deduplicação somente entre APIs externas.
    if source not in {
        "JOOBLE",
        "ADZUNA",
        "JSEARCH"
    }:
        return None

    title = (
        str(title or "")
        .strip()
    )

    company = (
        str(company or "")
        .strip()
    )

    city = (
        str(city or "")
        .strip()
    )

    # Sem empresa ou cidade, não arriscamos
    # considerar duas vagas como iguais.
    if (
        not title
        or not company
        or not city
    ):
        return None

    normalized_title = (
        normalize_job_search_text(
            title
        )
    )

    normalized_company = (
        normalize_job_search_text(
            company
        )
    )

    normalized_city = (
        normalize_job_search_text(
            city
        )
    )

    other_sources = [
        item
        for item in [
            "JOOBLE",
            "ADZUNA",
            "JSEARCH"
        ]
        if item != source
    ]

    duplicate = (
        JobVacancy.query
        .filter(
            JobVacancy.source.in_(
                other_sources
            ),
            normalized_job_column(
                JobVacancy.title
            ) == normalized_title,
            normalized_job_column(
                JobVacancy.company
            ) == normalized_company,
            normalized_job_column(
                JobVacancy.city
            ) == normalized_city
        )
        .order_by(
            JobVacancy.is_active.desc(),
            JobVacancy.published_at.desc()
        )
        .first()
    )

    return duplicate    
    
def generate_slug(text):
    text = str(text or "").strip().lower()

    text = unicodedata.normalize(
        "NFKD",
        text
    )

    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )

    text = re.sub(
        r"[^a-z0-9]+",
        "-",
        text
    )

    return text.strip("-")    
    
def build_ad_slug(ad):
    city_slug = generate_slug(ad.city)

    title_slug = generate_slug(ad.title)

    if not city_slug:
        city_slug = "local"

    if not title_slug:
        title_slug = "anuncio"

    return f"{city_slug}/{title_slug}-{ad.id}"   


def get_platoon_by_age(age):
    try:
        age = int(age)
    except (TypeError, ValueError):
        return None

    if age in (7, 8, 9):
        return "1º Pelotão"

    if age in (10, 11):
        return "2º Pelotão"

    if age in (12, 13, 14, 15):
        return "3º Pelotão"

    return None
    
def pix_crc16(payload):
    polynomial = 0x1021
    result = 0xFFFF

    for byte in payload.encode("utf-8"):
        result ^= byte << 8

        for _ in range(8):
            if result & 0x8000:
                result = (
                    (result << 1) ^ polynomial
                ) & 0xFFFF
            else:
                result = (
                    result << 1
                ) & 0xFFFF

    return f"{result:04X}"


def pix_field(field_id, value):
    value = str(value)

    return (
        f"{field_id}"
        f"{len(value):02d}"
        f"{value}"
    )


def normalize_pix_text(value, max_length):
    value = str(value or "").strip().upper()

    value = unicodedata.normalize(
        "NFKD",
        value
    )

    value = "".join(
        char
        for char in value
        if not unicodedata.combining(char)
    )

    value = re.sub(
        r"[^A-Z0-9 .-]",
        "",
        value
    )

    return value[:max_length]


def build_pix_payload(
    pix_key,
    receiver_name,
    receiver_city,
    amount
):
    pix_key = str(
        pix_key or ""
    ).strip()

    receiver_name = normalize_pix_text(
        receiver_name,
        25
    )

    receiver_city = normalize_pix_text(
        receiver_city,
        15
    )

    amount = float(
        amount or 0
    )

    merchant_account = (
        pix_field(
            "00",
            "BR.GOV.BCB.PIX"
        )
        + pix_field(
            "01",
            pix_key
        )
    )

    additional_data = pix_field(
        "05",
        "***"
    )

    payload = ""

    payload += pix_field(
        "00",
        "01"
    )

    payload += pix_field(
        "26",
        merchant_account
    )

    payload += pix_field(
        "52",
        "0000"
    )

    payload += pix_field(
        "53",
        "986"
    )

    if amount > 0:
        payload += pix_field(
            "54",
            f"{amount:.2f}"
        )

    payload += pix_field(
        "58",
        "BR"
    )

    payload += pix_field(
        "59",
        receiver_name
    )

    payload += pix_field(
        "60",
        receiver_city
    )

    payload += pix_field(
        "62",
        additional_data
    )

    payload += "6304"

    crc = pix_crc16(
        payload
    )

    return payload + crc


def generate_pix_qr_base64(payload):
    qr = qrcode.QRCode(
        version=None,
        error_correction=(
            qrcode.constants.ERROR_CORRECT_M
        ),
        box_size=8,
        border=4
    )

    qr.add_data(
        payload
    )

    qr.make(
        fit=True
    )

    image = qr.make_image(
        fill_color="black",
        back_color="white"
    )

    buffer = io.BytesIO()

    image.save(
        buffer,
        format="PNG"
    )

    return base64.b64encode(
        buffer.getvalue()
    ).decode("utf-8")    

def get_seo_service_links(
    min_ads=2,
    limit=40
):
    ads = (
        Ad.query
        .join(
            User,
            Ad.user_id == User.id
        )
        .filter(
            Ad.is_active.is_(True),
            Ad.slug.isnot(None),
            Ad.slug != "",
            Ad.city.isnot(None),
            Ad.city != "",
            or_(
                Ad.blocked_until.is_(None),
                Ad.blocked_until <= utc_now()
            ),
            or_(
                User.blocked_until.is_(None),
                User.blocked_until <= utc_now()
            )
        )
        .all()
    )

    ignored_keywords = {
        "a",
        "o",
        "as",
        "os",
        "de",
        "da",
        "do",
        "das",
        "dos",
        "e",
        "em",
        "para",
        "com",
        "por",
        "um",
        "uma"
    }

    grouped = {}

    for ad in ads:
        city_name = (
            ad.city or ""
        ).strip()

        city_slug = generate_slug(
            city_name
        )

        if not city_slug:
            continue

        for keyword_obj in ad.keywords:
            keyword = (
                keyword_obj.keyword or ""
            ).strip()

            service_slug = generate_slug(
                keyword
            )

            if (
                not service_slug
                or service_slug in ignored_keywords
                or len(service_slug) < 3
            ):
                continue

            key = (
                city_slug,
                service_slug
            )

            if key not in grouped:
                grouped[key] = {
                    "city": city_name,
                    "city_slug": city_slug,
                    "service": keyword,
                    "service_slug": service_slug,
                    "ad_ids": set()
                }

            grouped[key]["ad_ids"].add(
                ad.id
            )

    links = []

    for item in grouped.values():
        total = len(
            item["ad_ids"]
        )

        if total < min_ads:
            continue

        links.append({
            "city": item["city"],
            "city_slug": item["city_slug"],
            "service": item["service"],
            "service_slug": item["service_slug"],
            "total_ads": total,
            "url": (
                f"/servicos/"
                f"{item['city_slug']}/"
                f"{item['service_slug']}"
            )
        })

    links.sort(
        key=lambda item: (
            -item["total_ads"],
            item["city"].casefold(),
            item["service"].casefold()
        )
    )

    return links[:limit]    


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
    
@app.route("/metrics/visit", methods=["POST"])
def register_site_visit():
    try:
        # Não conta administradores como visitantes.
        current_user_id = session.get("user_id")

        if current_user_id:
            current_user = db.session.get(
                User,
                current_user_id
            )

            if current_user and current_user.is_admin:
                return jsonify({
                    "registered": False,
                    "reason": "admin"
                })

        visitor_id = (
            request.cookies.get("catalogo_visitor_id")
            or str(uuid.uuid4())
        )

        now = utc_now()

        visitor = SiteVisitor.query.filter_by(
            visitor_id=visitor_id
        ).first()

        if visitor:
            visitor.last_visit_at = now
        else:
            visitor = SiteVisitor(
                visitor_id=visitor_id,
                first_visit_at=now,
                last_visit_at=now
            )

            db.session.add(visitor)

        db.session.commit()

        response = jsonify({
            "registered": True
        })

        response.set_cookie(
            "catalogo_visitor_id",
            visitor_id,
            max_age=60 * 60 * 24 * 365 * 2,
            httponly=True,
            secure=not app.debug,
            samesite="Lax"
        )

        return response

    except Exception as error:
        db.session.rollback()

        print(
            "Erro ao registrar visitante:",
            error
        )

        return jsonify({
            "registered": False
        }), 500

@app.route("/metrics/search", methods=["POST"])
def register_search_metric():
    try:
        data = request.get_json(silent=True) or {}
        # Tentativas individuais de Basquete e Pênaltis.
        athlete_attempts_data = data.get("athlete_attempts", [])

        if not isinstance(athlete_attempts_data, list):
            return jsonify({
                "success": False,
                "message": "Formato inválido dos arremessos individuais."
            }), 400

        search_term = str(
            data.get("term") or ""
        ).strip().lower()

        search_term = search_term[:255]

        visitor_id = request.cookies.get(
            "catalogo_visitor_id"
        )

        metric = SearchMetric(
            visitor_id=visitor_id,
            search_term=search_term or None,
            searched_at=utc_now()
        )

        db.session.add(metric)
        db.session.commit()

        return jsonify({
            "registered": True
        }), 201

    except Exception as error:
        db.session.rollback()

        print(
            "Erro ao registrar pesquisa:",
            error
        )

        return jsonify({
            "registered": False
        }), 500        

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


# ==========================================
# OLIMPÍADAS - SEGURANÇA DAS CHAVES DE SÚMULAS
# ==========================================

def generate_olympic_scoresheet_key():
    """
    Gera uma chave aleatória de acesso às súmulas.
    A chave original deve ser exibida somente
    no momento do cadastro.
    """
    return secrets.token_urlsafe(32)


def hash_olympic_scoresheet_key(access_key):
    """
    Calcula o hash da chave para armazenamento
    e consulta no banco de dados.
    """
    return hashlib.sha256(
        access_key.encode("utf-8")
    ).hexdigest()


def validate_olympic_scoresheet_key(access_key):
    """
    Verifica se a chave existe, está ativa
    e ainda não expirou.

    Retorna o registro da chave quando válida.
    Caso contrário, retorna None.
    """

    if not isinstance(access_key, str):
        return None

    access_key = access_key.strip()

    if not access_key or len(access_key) > 256:
        return None

    key_hash = hash_olympic_scoresheet_key(
        access_key
    )

    access_record = (
        OlympicScoresheetAccessKey.query
        .filter_by(key_hash=key_hash)
        .first()
    )

    if access_record is None:
        return None

    if not access_record.is_active:
        return None

    if (
        access_record.expires_at is not None
        and access_record.expires_at <= datetime.utcnow()
    ):
        return None

    return access_record
    

# ==========================================
# OLIMPÍADAS - AUTORIZAÇÃO EXTERNA DAS SÚMULAS
# ==========================================

def olympic_scoresheet_access_required(view_func):

    @wraps(view_func)
    def wrapper(*args, **kwargs):

        access_id = session.get(
            "olympic_scoresheet_access_id"
        )

        if not access_id:
            return redirect(
                url_for("olympic_scoresheet_external_login")
            )

        access_record = db.session.get(
            OlympicScoresheetAccessKey,
            access_id
        )

        if access_record is None:
            session.pop(
                "olympic_scoresheet_access_id",
                None
            )
            return redirect(
                url_for("olympic_scoresheet_external_login")
            )

        if not access_record.is_active:
            session.pop(
                "olympic_scoresheet_access_id",
                None
            )
            return redirect(
                url_for("olympic_scoresheet_external_login")
            )

        if (
            access_record.expires_at is not None
            and access_record.expires_at <= datetime.utcnow()
        ):
            session.pop(
                "olympic_scoresheet_access_id",
                None
            )
            return redirect(
                url_for("olympic_scoresheet_external_login")
            )

        return view_func(*args, **kwargs)

    return wrapper
    

# ==========================================
# OLIMPÍADAS - PÁGINA EXTERNA DE ACESSO
# ÀS SÚMULAS
# ==========================================

@app.route(
    "/olimpiadas/sumulas/acesso",
    methods=["GET"]
)
def olympic_scoresheet_external_login():

    access_id = session.get(
        "olympic_scoresheet_access_id"
    )

    if access_id:

        access_record = db.session.get(
            OlympicScoresheetAccessKey,
            access_id
        )

        if (
            access_record is not None
            and access_record.is_active
            and (
                access_record.expires_at is None
                or access_record.expires_at > datetime.utcnow()
            )
        ):
            return redirect(
                url_for("olympic_scoresheet_external_home")
            )

        session.pop(
            "olympic_scoresheet_access_id",
            None
        )

    response = make_response(
        render_template(
            "olympic_scoresheet_external_login.html"
        )
    )

    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"

    return response


# ==========================================
# OLIMPÍADAS - AUTENTICAÇÃO EXTERNA DAS SÚMULAS
# ==========================================

@app.route(
    "/olimpiadas/sumulas/autenticar",
    methods=["POST"]
)
def olympic_scoresheet_external_authenticate():

    # Impede o uso de uma sessão antiga de acesso às súmulas.
    session.pop("olympic_scoresheet_access_id", None)

    # Exige JSON para a autenticação.
    if not request.is_json:
        return jsonify({
            "success": False,
            "message": "Requisição inválida."
        }), 400

    # Proteção contra requisições de outras origens.
    if not olympic_admin_same_origin():
        return jsonify({
            "success": False,
            "message": "Origem da requisição não autorizada."
        }), 403

    data = request.get_json(silent=True) or {}
    access_key = data.get("access_key")

    
    if not isinstance(access_key, str) or not access_key.strip():

        return jsonify({
            "success": False,
            "message": "Chave de acesso inválida."
        }), 401

    access_record = validate_olympic_scoresheet_key(
        access_key
    )

    if access_record is None:
        return jsonify({
            "success": False,
            "message": "Chave inválida, revogada ou expirada."
        }), 401

    # Registra a identificação da chave na sessão.
    # As rotas protegidas continuarão verificando
    # se ela permanece ativa e dentro da validade.
    session.clear()
    session["olympic_scoresheet_access_id"] = access_record.id
    session.permanent = False

    access_record.last_used_at = datetime.utcnow()
    db.session.commit()

    response = jsonify({
        "success": True,
        "message": "Acesso autorizado.",
        "redirect_url": url_for(
            "olympic_scoresheet_external_home"
        )
    })

    response.headers["Cache-Control"] = "no-store"

    return response


# ==========================================
# OLIMPÍADAS - CONFRONTOS EXTERNOS
# ==========================================

@app.route(
    "/olimpiadas/sumulas/confrontos",
    methods=["GET"]
)
@olympic_scoresheet_access_required
def olympic_scoresheet_external_home():

    edition = (
        OlympicEdition.query
        .filter_by(is_active=True)
        .order_by(OlympicEdition.year.desc())
        .first()
    )

    if edition is None:
        abort(404, description="Nenhuma edição ativa encontrada.")

    matches = (
        OlympicMatch.query
        .filter_by(edition_id=edition.id)
        .order_by(
            OlympicMatch.match_date,
            OlympicMatch.match_time,
            OlympicMatch.id
        )
        .all()
    )

    response = make_response(
        render_template(
            "olympic_scoresheet_external_home.html",
            edition=edition,
            matches=matches
        )
    )

    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"

    return response


def admin_required_page(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("auth_page"))

        if not session.get("is_admin"):
            return redirect(url_for("search_page"))

        return view_func(*args, **kwargs)
    return wrapper
    

# ==========================================
# OLIMPÍADAS - ADMINISTRAÇÃO DAS CHAVES
# DE ACESSO ÀS SÚMULAS
# ==========================================

def olympic_admin_api_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):

        if (
            not session.get("user_id")
            or not session.get("is_admin")
        ):
            return jsonify({
                "success": False,
                "message": "Acesso administrativo necessário."
            }), 403

        return view_func(*args, **kwargs)

    return wrapper


def olympic_admin_same_origin():
    """
    Confere a origem das requisições que
    modificam as chaves de acesso.
    """

    origin = request.headers.get("Origin")
    referer = request.headers.get("Referer")

    if not origin and not referer:
        return False

    source = origin or referer

    source_url = urlparse(source)

    return (
        source_url.scheme == request.scheme
        and source_url.netloc == request.host
    )


# ==========================================
# LISTAR CHAVES CADASTRADAS
# ==========================================

@app.route(
    "/admin/olimpiadas/chaves-sumulas",
    methods=["GET"]
)
@olympic_admin_api_required
def admin_list_olympic_scoresheet_keys():

    records = (
        OlympicScoresheetAccessKey.query
        .order_by(
            OlympicScoresheetAccessKey.id.desc()
        )
        .all()
    )

    return jsonify({
        "success": True,
        "keys": [
            {
                "id": record.id,
                "name": record.name,
                "is_active": record.is_active,
                "created_at": (
                    record.created_at.isoformat()
                    if record.created_at else None
                ),
                "expires_at": (
                    record.expires_at.isoformat()
                    if record.expires_at else None
                ),
                "last_used_at": (
                    record.last_used_at.isoformat()
                    if record.last_used_at else None
                )
            }
            for record in records
        ]
    })


# ==========================================
# CADASTRAR NOVA CHAVE
# ==========================================

@app.route(
    "/admin/olimpiadas/chaves-sumulas",
    methods=["POST"]
)
@olympic_admin_api_required
def admin_create_olympic_scoresheet_key():

    if not olympic_admin_same_origin():
        return jsonify({
            "success": False,
            "message": "Origem da requisição não autorizada."
        }), 403

    if not request.is_json:
        return jsonify({
            "success": False,
            "message": "Envie os dados em JSON."
        }), 415

    data = request.get_json(silent=True) or {}

    name = str(data.get("name") or "").strip()

    if not name or len(name) > 150:
        return jsonify({
            "success": False,
            "message": "Informe um nome de até 150 caracteres."
        }), 400

    
    expires_in_days = data.get("expires_in_days")
    expires_at = None

    if expires_in_days not in (None, ""):

        if (
            isinstance(expires_in_days, bool)
            or not str(expires_in_days).isdigit()
        ):
            return jsonify({
                "success": False,
                "message": "Prazo de validade inválido."
            }), 400

        expires_in_days = int(expires_in_days)

        if not 1 <= expires_in_days <= 365:
            return jsonify({
                "success": False,
                "message": "O prazo deve ser de 1 a 365 dias."
            }), 400

        expires_at = (
            datetime.utcnow()
            + timedelta(days=expires_in_days)
        )

    # Chave personalizada
    access_key = data.get("access_key")

    if not isinstance(access_key, str) or not access_key.strip():
        return jsonify({
            "success": False,
            "message": "Informe uma chave de acesso."
        }), 400

    access_key = access_key.strip()

    key_hash = hash_olympic_scoresheet_key(access_key)

    existing_key = (
        OlympicScoresheetAccessKey.query
        .filter_by(key_hash=key_hash)
        .first()
    )

    if existing_key:
        return jsonify({
            "success": False,
            "message": "Esta chave já está cadastrada."
        }), 409

    record = OlympicScoresheetAccessKey(
        name=name,
        key_hash=key_hash,
        is_active=True,
        expires_at=expires_at
    )




    try:
        db.session.add(record)
        db.session.commit()

    except Exception:
        db.session.rollback()
        app.logger.exception(
            "Erro ao cadastrar chave de súmula."
        )

        return jsonify({
            "success": False,
            "message": "Não foi possível cadastrar a chave."
        }), 500

    response = jsonify({
        "success": True,
        "message": "Chave cadastrada com sucesso.",
        "id": record.id,
        "name": record.name,
        "access_key": access_key
    })

    response.headers["Cache-Control"] = "no-store"

    return response, 201


# ==========================================
# REVOGAR CHAVE DE ACESSO
# ==========================================

@app.route(
    "/admin/olimpiadas/chaves-sumulas/<int:key_id>/revogar",
    methods=["POST"]
)
@olympic_admin_api_required
def admin_revoke_olympic_scoresheet_key(key_id):

    if not olympic_admin_same_origin():
        return jsonify({
            "success": False,
            "message": "Origem da requisição não autorizada."
        }), 403

    record = db.session.get(
        OlympicScoresheetAccessKey,
        key_id
    )

    if record is None:
        return jsonify({
            "success": False,
            "message": "Chave não encontrada."
        }), 404

    if not record.is_active:
        return jsonify({
            "success": False,
            "message": "Esta chave já está revogada."
        }), 400

    try:
        record.is_active = False
        db.session.commit()

    except Exception:
        db.session.rollback()
        app.logger.exception(
            "Erro ao revogar chave de súmula."
        )

        return jsonify({
            "success": False,
            "message": "Não foi possível revogar a chave."
        }), 500

    return jsonify({
        "success": True,
        "message": "Chave revogada com sucesso."
    })
    
    
@app.route(
    "/admin/olimpiadas/geral/<int:edition_id>",
    methods=["GET"]
)
@admin_required_page
def admin_olympic_overall_page(edition_id):
    edition = db.session.get(
        OlympicEdition,
        edition_id
    )

    if edition is None:
        return "Edição não encontrada", 404

    result = calculate_olympic_overall_standings(
        edition_id
    )

    return render_template(
        "admin_olympic_overall.html",
        edition=edition,
        result=result
    )


# ==========================================
# OLIMPÍADAS - CLASSIFICAÇÃO GERAL PÚBLICA
# ==========================================

@app.route(
    "/olimpiadas/classificacao-geral/<int:edition_id>",
    methods=["GET"]
)
def public_olympic_overall_page(edition_id):

    edition = db.session.get(
        OlympicEdition,
        edition_id
    )

    if edition is None:
        return "Edição não encontrada", 404

    result = calculate_olympic_overall_standings(
        edition_id
    )

    return render_template(
        "public_olympic_overall.html",
        edition=edition,
        result=result
    )


# ==========================================
# OLIMPÍADAS - ANDAMENTO DAS CLASSIFICATÓRIAS
# ==========================================

@app.route(
    "/admin/olimpiadas/andamento/<int:edition_id>",
    methods=["GET"]
)
@admin_required_page
def admin_olympic_classification_progress(edition_id):

    edition = db.session.get(OlympicEdition, edition_id)

    if edition is None:
        return jsonify({
            "success": False,
            "message": "Edição não encontrada."
        }), 404

    modalities = (
        OlympicModality.query
        .filter_by(edition_id=edition_id, is_active=True)
        .order_by(OlympicModality.name)
        .all()
    )

    progress = []

    for modality in modalities:
        shifts = []

        for shift in ("MATUTINO", "VESPERTINO"):

            matches = OlympicMatch.query.filter(
                OlympicMatch.edition_id == edition_id,
                OlympicMatch.modality_id == modality.id,
                OlympicMatch.phase == "CLASSIFICATORIA",
                db.func.upper(OlympicMatch.shift) == shift
            ).all()

            finished = sum(
                1 for match in matches
                if match.status == "FINALIZADO"
                and match.score_a is not None
                and match.score_b is not None
            )

            total = len(matches)
            pending = total - finished

            classification = calculate_olympic_classification(
                edition_id,
                modality.id,
                shift
            )

            leader = None
            tie = False

            if classification and finished > 0:
                first = classification[0]

                def ranking_key(item):
                    return (
                        item["points"],
                        item["goal_difference"],
                        -item["red_cards"],
                        -item["yellow_cards"],
                        -item["fouls"]
                    )

                tie = sum(
                    ranking_key(item) == ranking_key(first)
                    for item in classification
                ) > 1

                leader = {
                    "team": first["team_name"],
                    "coach": first["coach"],
                    "points": first["points"]
                }

            completed = (
                total > 0
                and pending == 0
                and not tie
                and leader is not None
            )

            shifts.append({
                "shift": shift,
                "total": total,
                "finished": finished,
                "pending": pending,
                "leader": leader,
                "tie": tie,
                "completed": completed
            })

        progress.append({
            "modality": modality.name,
            "shifts": shifts
        })

    return jsonify({
        "success": True,
        "edition_id": edition_id,
        "progress": progress
    })


# ==========================================
# OLIMPÍADAS - GERAR FINAIS INTERTURNOS
# ==========================================

@app.route(
    "/admin/olimpiadas/gerar-finais/<int:edition_id>",
    methods=["POST"]
)
@admin_required_page
def admin_generate_olympic_intershift_finals(edition_id):
    
    preview_only = request.args.get("preview") == "1"

    edition = db.session.get(OlympicEdition, edition_id)

    if not edition:
        return jsonify({
            "success": False,
            "message": "Edição não encontrada."
        }), 404

    if not edition.is_active:
        return jsonify({
            "success": False,
            "message": "A edição está inativa."
        }), 400

    final_date = date(2026, 11, 28)

    if (
        (edition.start_date and final_date < edition.start_date)
        or (edition.end_date and final_date > edition.end_date)
    ):
        return jsonify({
            "success": False,
            "message": "A data das finais está fora do período da edição."
        }), 400

    settings = OlympicCalendarSettings.query.filter_by(
        edition_id=edition_id
    ).first()

    if not settings:
        return jsonify({
            "success": False,
            "message": "Configure primeiro o calendário."
        }), 400

    modalities = OlympicModality.query.filter_by(
        edition_id=edition_id,
        is_active=True
    ).order_by(OlympicModality.id).all()

    start_window = datetime.combine(
        final_date,
        datetime.strptime("08:30", "%H:%M").time()
    )

    end_window = datetime.combine(
        final_date,
        datetime.strptime("11:30", "%H:%M").time()
    )

    scheduled = get_existing_olympic_scheduled_matches(
        edition_id
    )

    created = []
    pending = []
    already_exists = []

    for modality in modalities:

        existing = OlympicMatch.query.filter_by(
            edition_id=edition_id,
            modality_id=modality.id,
            phase="FINAL_ENTRE_TURNOS"
        ).first()

        if existing:
            already_exists.append(modality.name)
            continue

        champions = {}
        reason = None

        for shift in ("MATUTINO", "VESPERTINO"):

            matches = OlympicMatch.query.filter(
                OlympicMatch.edition_id == edition_id,
                OlympicMatch.modality_id == modality.id,
                OlympicMatch.phase == "CLASSIFICATORIA",
                db.func.upper(OlympicMatch.shift) == shift
            ).all()
            
            
            # Confirma que os 10 confrontos do turno
            # estão cadastrados, sem duplicações.

            shift_teams = OlympicTeam.query.filter(
                OlympicTeam.edition_id == edition_id,
                db.func.upper(OlympicTeam.shift) == shift
            ).all()

            expected_count = (
                len(shift_teams) * (len(shift_teams) - 1) // 2
            )

            unique_pairs = {
                tuple(sorted((m.team_a_id, m.team_b_id)))
                for m in matches
            }
            
            valid_team_ids = {
                team.id for team in shift_teams
            }

            valid_pairs = all(
                m.team_a_id in valid_team_ids
                and m.team_b_id in valid_team_ids
                for m in matches
            )

            if (
                len(shift_teams) != 5
                or len(matches) != expected_count
                or len(unique_pairs) != expected_count
                or not valid_pairs
            ):
                reason = (
                    f"Calendário do {shift.lower()} incompleto "
                    "ou com confrontos duplicados"
                )
                break


            if not matches or any(
                m.status != "FINALIZADO"
                or m.score_a is None
                or m.score_b is None
                for m in matches
            ):
                reason = f"Classificatória do {shift.lower()} pendente"
                break

            ranking = calculate_olympic_classification(
                edition_id,
                modality.id,
                shift
            )

            if not ranking:
                reason = f"Sem classificação no {shift.lower()}"
                break

            modality_name = modality.name.strip().lower()

            if modality_name in ("futsal", "golzinho"):
                def ranking_key(item):
                    return (
                        item["points"],
                        item["goal_difference"],
                        -item["red_cards"],
                        -item["yellow_cards"],
                        -item["fouls"]
                    )
            else:
                def ranking_key(item):
                    return (
                        item["points"],
                        item["wins"]
                    )

            if sum(
                ranking_key(item) == ranking_key(ranking[0])
                for item in ranking
            ) != 1:
                reason = f"Desempate pendente no {shift.lower()}"
                break

            champions[shift] = ranking[0]["team_id"]

        if reason:
            pending.append({
                "modality": modality.name,
                "reason": reason
            })
            continue

        try:
            duration = get_olympic_match_duration({
                "modality_id": modality.id,
                "duration_minutes": modality.match_duration_minutes
            })
        except ValueError as error:
            pending.append({
                "modality": modality.name,
                "reason": str(error)
            })
            continue

        team_a_id = champions["MATUTINO"]
        team_b_id = champions["VESPERTINO"]

        candidate = start_window
        selected = None

        while candidate + timedelta(minutes=duration) <= end_window:

            available = olympic_time_slot_is_available(
                candidate,
                duration,
                scheduled,
                settings.interval_minutes,
                settings.allow_simultaneous_matches
            )

            rested = all(
                olympic_team_has_enough_rest(
                    team_id,
                    candidate,
                    duration,
                    scheduled,
                    settings.rest_minutes
                )
                for team_id in (team_a_id, team_b_id)
            )

            if available and rested:
                selected = candidate
                break

            candidate += timedelta(minutes=5)

        if selected is None:
            pending.append({
                "modality": modality.name,
                "reason": "Sem horário disponível entre 08h30 e 11h30"
            })
            continue

        match = OlympicMatch(
            edition_id=edition_id,
            modality_id=modality.id,
            team_a_id=team_a_id,
            team_b_id=team_b_id,
            match_date=final_date,
            match_time=selected.time(),
            shift="INTERTURNOS",
            phase="FINAL_ENTRE_TURNOS",
            status="AGENDADO"
        )

        db.session.add(match)

        scheduled.append({
            "team_a_id": team_a_id,
            "team_b_id": team_b_id,
            "modality_id": modality.id,
            "start": selected,
            "duration_minutes": duration
        })

        team_a = db.session.get(OlympicTeam, team_a_id)
        team_b = db.session.get(OlympicTeam, team_b_id)

        created.append({
            "modality": modality.name,
            "time": selected.strftime("%H:%M"),
            "team_a": f"{team_a.color} — {team_a.coach}",
            "team_b": f"{team_b.color} — {team_b.coach}"
        })

    
    if preview_only:
        db.session.rollback()
    else:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            return jsonify({
                "success": False,
                "message": (
                    "Erro ao salvar as finais. "
                    "Nenhum novo confronto foi confirmado."
                )
            }), 500


    return jsonify({
        "success": True,
        "preview": preview_only,
        "created": created,
        "pending": pending,
        "already_exists": already_exists,
        "message": (
            f"{len(created)} final(is) pronta(s) para geração."
            if preview_only
            else f"{len(created)} final(is) cadastrada(s)."
        )
    })


def plan_priority_case():
    return case(
        (Ad.plan == "ADMIN", 0),
        (Ad.plan == "VIP_PREMIUM", 1),
        (Ad.plan == "VIP_OURO", 2),
        (Ad.plan == "VIP_PRATA", 3),
        (Ad.plan == "VIP_BRONZE", 4),
        else_=5
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
    
def grant_promotional_vip(user, plan, days):
    allowed_vip_plans = [
        "VIP_BRONZE",
        "VIP_PRATA",
        "VIP_OURO",
        "VIP_PREMIUM"
    ]

    if not user:
        return False

    if user.is_admin or user.plan == "ADMIN":
        return False

    plan = (plan or "").strip().upper()

    if plan not in allowed_vip_plans:
        return False

    try:
        days = int(days)
    except (TypeError, ValueError):
        return False

    if days < 1 or days > 365:
        return False

    now = utc_now()
    promotional_expiration = now + timedelta(days=days)

    # Não reduz o prazo de um VIP que já vence mais tarde.
    if (
        is_vip_plan(user.plan)
        and user.vip_expires_at
        and user.vip_expires_at > promotional_expiration
    ):
        sync_user_ads_with_plan(user)
        return True

    user.plan = plan
    user.vip_expires_at = promotional_expiration

    sync_user_ads_with_plan(user, plan)

    return True    

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
        existing_admin.plan = "ADMIN"
        existing_admin.vip_expires_at = None
        existing_admin.password_hash = generate_password_hash(admin_password)
        db.session.commit()
        return

    admin_user = User(
        name="Administrador",
        email=admin_email,
        phone="(00) 00000-0000",
        password_hash=generate_password_hash(admin_password),
        plan="ADMIN",
        vip_expires_at=None,
        is_admin=True
    )

    db.session.add(admin_user)
    db.session.commit()
    
    
    
def allowed_file(filename, allowed_extensions):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_extensions
    
def get_vitrine_thumbnail_url(
    original_image_url
):
    if not original_image_url:
        return None

    original_path = resolve_media_file_path(
        original_image_url
    )

    if (
        not original_path
        or not os.path.isfile(original_path)
    ):
        return original_image_url

    original_filename = os.path.basename(
        original_path
    )

    filename_without_extension = (
        os.path.splitext(
            original_filename
        )[0]
    )

    thumbnail_filename = (
        f"{filename_without_extension}.webp"
    )

    thumbnail_path = os.path.join(
        UPLOAD_THUMBNAIL_FOLDER,
        thumbnail_filename
    )

    if not os.path.isfile(thumbnail_path):
        try:
            with Image.open(
                original_path
            ) as image:
                image = ImageOps.exif_transpose(
                    image
                )

                if image.mode not in (
                    "RGB",
                    "RGBA"
                ):
                    image = image.convert("RGB")

                image.thumbnail(
                    (500, 500),
                    Image.Resampling.LANCZOS
                )

                image.save(
                    thumbnail_path,
                    format="WEBP",
                    quality=75,
                    method=6,
                    optimize=True
                )

        except Exception as error:
            print(
                "Erro ao gerar miniatura:",
                original_path,
                error,
                flush=True
            )

            return original_image_url

    return (
        f"/media/thumbnails/"
        f"{thumbnail_filename}"
    )    

def resolve_media_file_path(media_url):
    if not media_url:
        return None

    media_url = str(media_url).strip()
    if not media_url:
        return None

    normalized = media_url.replace("\\", "/").strip()
    
    if normalized.startswith("/media/images/"):
        relative_part = normalized[len("/media/images/"):]
        return os.path.join(UPLOAD_IMAGE_FOLDER, relative_part)

    if normalized.startswith("/media/videos/"):
        relative_part = normalized[len("/media/videos/"):]
        return os.path.join(UPLOAD_VIDEO_FOLDER, relative_part)

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
        
    if getattr(user, "is_admin", False):
        user.plan = "ADMIN"
        user.vip_expires_at = None

        user_ads = Ad.query.filter_by(user_id=user.id).all()
        for ad in user_ads:
            ad.plan = "ADMIN"
            ad.is_active = True

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
        
    if getattr(user, "is_admin", False):
        user.plan = "ADMIN"
        user.vip_expires_at = None
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
    if ad.plan == "ADMIN":
        plan_rules = {
            "can_use_images": True,
            "can_use_videos": True,
            "can_show_full_details": True
        }
    else:
        plan_rules = get_plan_rules(ad.plan)

    safe_main_image = ad.main_image if plan_rules.get("can_use_images") else None
    safe_main_video = ad.main_video if plan_rules.get("can_use_videos") else None

    return {
        "id": ad.id,
        "slug": ad.slug,
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
        "latitude": ad.latitude,
        "longitude": ad.longitude,
        "plan": ad.plan,
        "main_image": safe_main_image,
        "main_video": safe_main_video,
        "is_active": ad.is_active,
        "show_on_home": bool(
            ad.show_on_home
        ),
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
        "ADMIN": {
            "ads_limit": 999999,
            "keywords_limit": 999999,
            "can_use_images": True,
            "can_use_videos": True,
            "can_appear_in_vip_list": True,
            "can_show_full_details": True,
            "can_use_vitrine": True,
            "can_use_location": True
        },
        "FREE": {
            "ads_limit": settings.free_ads_limit,
            "keywords_limit": settings.free_keywords_limit,
            "can_use_images": settings.free_can_use_images,
            "can_use_videos": settings.free_can_use_videos,
            "can_appear_in_vip_list": settings.free_can_appear_in_vip_list,
            "can_show_full_details": settings.free_can_show_full_details,
            "can_use_vitrine": settings.free_can_use_vitrine,
            "can_use_location": settings.free_can_use_location
        },
        "VIP_BRONZE": {
            "ads_limit": settings.bronze_ads_limit,
            "keywords_limit": settings.bronze_keywords_limit,
            "can_use_images": settings.bronze_can_use_images,
            "can_use_videos": settings.bronze_can_use_videos,
            "can_appear_in_vip_list": settings.bronze_can_appear_in_vip_list,
            "can_show_full_details": settings.bronze_can_show_full_details,
            "can_use_vitrine": settings.bronze_can_use_vitrine,
            "can_use_location": settings.bronze_can_use_location
        },
        "VIP_PRATA": {
            "ads_limit": settings.prata_ads_limit,
            "keywords_limit": settings.prata_keywords_limit,
            "can_use_images": settings.prata_can_use_images,
            "can_use_videos": settings.prata_can_use_videos,
            "can_appear_in_vip_list": settings.prata_can_appear_in_vip_list,
            "can_show_full_details": settings.prata_can_show_full_details,
            "can_use_vitrine": settings.prata_can_use_vitrine,
            "can_use_location": settings.prata_can_use_location
        },
        "VIP_OURO": {
            "ads_limit": settings.ouro_ads_limit,
            "keywords_limit": settings.ouro_keywords_limit,
            "can_use_images": settings.ouro_can_use_images,
            "can_use_videos": settings.ouro_can_use_videos,
            "can_appear_in_vip_list": settings.ouro_can_appear_in_vip_list,
            "can_show_full_details": settings.ouro_can_show_full_details,
            "can_use_vitrine": settings.ouro_can_use_vitrine,
            "can_use_location": settings.ouro_can_use_location
        },
        "VIP_PREMIUM": {
            "ads_limit": settings.premium_ads_limit,
            "keywords_limit": settings.premium_keywords_limit,
            "can_use_images": settings.premium_can_use_images,
            "can_use_videos": settings.premium_can_use_videos,
            "can_appear_in_vip_list": settings.premium_can_appear_in_vip_list,
            "can_show_full_details": settings.premium_can_show_full_details,
            "can_use_vitrine": settings.premium_can_use_vitrine,
            "can_use_location": settings.premium_can_use_location
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


@app.route(
    "/admin/olimpiadas/edicoes/<int:edition_id>/calendario/previa",
    methods=["POST"]
)
@admin_required_page
def admin_olympic_calendar_preview(edition_id):

    """
    Gera uma prévia do calendário sem salvar confrontos.
    """

    try:
        data = request.get_json(silent=True) or {}

        start_date_text = data.get("start_date")
        end_date_text = data.get("end_date")
        
        # Horários sem jogos, exclusivos da geração automática
        break_times = {}

        for shift, prefix in (
            ("MATUTINO", "morning"),
            ("VESPERTINO", "afternoon")
        ):
            start_text = data.get(f"{prefix}_break_start") or ""
            end_text = data.get(f"{prefix}_break_end") or ""

            if bool(start_text) != bool(end_text):
                raise ValueError(
                    f"Informe o início e o fim do intervalo "
                    f"do turno {shift.lower()}."
                )

            if start_text:
                break_start = datetime.strptime(
                    start_text, "%H:%M"
                ).time()

                break_end = datetime.strptime(
                    end_text, "%H:%M"
                ).time()

                if break_end <= break_start:
                    raise ValueError(
                        f"O término do intervalo do turno "
                        f"{shift.lower()} deve ser posterior ao início."
                    )

                break_times[shift] = (
                    break_start,
                    break_end
                )

        if not start_date_text or not end_date_text:
            return jsonify({
                "ok": False,
                "error": "Informe as datas inicial e final."
            }), 400

        start_date = date.fromisoformat(start_date_text)
        end_date = date.fromisoformat(end_date_text)

        if end_date < start_date:
            return jsonify({
                "ok": False,
                "error": "A data final não pode ser anterior à inicial."
            }), 400

        edition = db.session.get(OlympicEdition, edition_id)

        if edition is None:
            return jsonify({
                "ok": False,
                "error": "Edição das Olimpíadas não encontrada."
            }), 404

        result = generate_olympic_calendar_preview(
            edition_id,
            start_date,
            end_date,
            break_times=break_times
        )
        
        modalities_by_id = {
            modality.id: modality
            for modality in OlympicModality.query.filter_by(
                edition_id=edition_id
            ).all()
        }

        teams_by_id = {
            team.id: team
            for team in OlympicTeam.query.filter_by(
                edition_id=edition_id
            ).all()
        }


        scheduled = []

        for match in result["scheduled_matches"]:
            scheduled.append({
                
                "modality_id": match["modality_id"],
                "modality_name": modalities_by_id[
                    match["modality_id"]
                ].name,
                "team_a_id": match["team_a_id"],
                "team_a_name": teams_by_id[
                    match["team_a_id"]
                ].name,
                "team_a_coach": teams_by_id[
                    match["team_a_id"]
                ].coach,
                "team_b_id": match["team_b_id"],
                "team_b_name": teams_by_id[
                    match["team_b_id"]
                ].name,
                "team_b_coach": teams_by_id[
                    match["team_b_id"]
                ].coach,

                "shift": match["shift"],
                "date": match["start"].date().isoformat(),
                "time": match["start"].strftime("%H:%M"),
                "duration_minutes": match["duration_minutes"]
            })

        return jsonify({
            "ok": True,
            "scheduled_matches": scheduled,
            "unscheduled_matches": result["unscheduled_matches"],
            "scheduled_count": len(scheduled),
            "unscheduled_count": len(
                result["unscheduled_matches"]
            ),
            "skipped_count": len(
                result["skipped_matches"]
            ),
            "existing_matches_count": result[
                "existing_matches_count"
            ]
        })

    except (ValueError, TypeError) as exc:
        return jsonify({
            "ok": False,
            "error": str(exc)
        }), 400
        

@app.route(
    "/admin/olimpiadas/edicoes/<int:edition_id>/calendario/confirmar",
    methods=["POST"]
)
@admin_required_page
def admin_olympic_calendar_confirm(edition_id):
    """
    Confirma e salva os confrontos do calendário automático.

    Recalcula os horários respeitando os intervalos
    de lanche informados para cada turno.
    """

    data = request.get_json(silent=True) or {}

    start_date_text = data.get("start_date")
    end_date_text = data.get("end_date")
    
    # Intervalos de lanche exclusivos do calendário automático
    break_times = {}

    try:
        for shift, prefix in (
            ("MATUTINO", "morning"),
            ("VESPERTINO", "afternoon")
        ):
            start_text = data.get(f"{prefix}_break_start") or ""
            end_text = data.get(f"{prefix}_break_end") or ""

            if bool(start_text) != bool(end_text):
                raise ValueError(
                    f"Informe o início e o fim do intervalo "
                    f"do turno {shift.lower()}."
                )

            if start_text:
                break_start = datetime.strptime(
                    start_text, "%H:%M"
                ).time()

                break_end = datetime.strptime(
                    end_text, "%H:%M"
                ).time()

                if break_end <= break_start:
                    raise ValueError(
                        f"O término do intervalo do turno "
                        f"{shift.lower()} deve ser posterior ao início."
                    )

                break_times[shift] = (
                    break_start,
                    break_end
                )

    except (ValueError, TypeError) as exc:
        return jsonify({
            "ok": False,
            "error": str(exc)
        }), 400

    if not start_date_text or not end_date_text:
        return jsonify({
            "ok": False,
            "error": "Informe as datas inicial e final."
        }), 400

    try:
        start_date = date.fromisoformat(start_date_text)
        end_date = date.fromisoformat(end_date_text)

    except (ValueError, TypeError):
        return jsonify({
            "ok": False,
            "error": "Formato de data inválido."
        }), 400

    if end_date < start_date:
        return jsonify({
            "ok": False,
            "error": "A data final não pode ser anterior à inicial."
        }), 400

    edition = db.session.get(OlympicEdition, edition_id)

    if edition is None:
        return jsonify({
            "ok": False,
            "error": "Edição das Olimpíadas não encontrada."
        }), 404

    
    
    try:
        # Bloqueia confirmações simultâneas da mesma edição.
        # O bloqueio permanece ativo até commit ou rollback.
        db.session.execute(
            db.text(
                "SELECT pg_advisory_xact_lock(:lock_namespace, :edition_id)"
            ),
            {
                "lock_namespace": 20261101,
                "edition_id": edition_id
            }
        )

        
        # Descarta dados carregados anteriormente na sessão,
        # para consultar novamente os registros existentes.
        db.session.expire_all()

        # Recalcula os confrontos respeitando os horários de lanche.
        calendar = generate_olympic_calendar_preview(
            edition_id,
            start_date,
            end_date,
            break_times=break_times
        )


    
    except (ValueError, TypeError) as error:
        db.session.rollback()

        return jsonify({
            "ok": False,
            "error": str(error)
        }), 400
   
    
    except Exception:
        db.session.rollback()

        app.logger.exception(
            "Erro ao preparar calendário da edição %s",
            edition_id
        )

        return jsonify({
            "ok": False,
            "error": "Erro interno ao preparar o calendário."
        }), 500



    scheduled_matches = calendar["scheduled_matches"]
    unscheduled_matches = calendar["unscheduled_matches"]
    
    
    
    if not scheduled_matches:
        db.session.rollback()

        return jsonify({
            "ok": False,
            "error": "Não existem novos confrontos para salvar."
        }), 400


    try:
        for match in scheduled_matches:
            match_start = match["start"]

            new_match = OlympicMatch(
                edition_id=edition_id,
                modality_id=match["modality_id"],
                team_a_id=match["team_a_id"],
                team_b_id=match["team_b_id"],
                match_date=match_start.date(),
                match_time=match_start.time(),
                shift=match["shift"],
                phase="CLASSIFICATORIA",
                status="AGENDADO"
            )

            db.session.add(new_match)

        db.session.commit()

    except Exception:
        db.session.rollback()
        app.logger.exception(
            "Erro ao salvar calendário da edição %s",
            edition_id
        )

        return jsonify({
            "ok": False,
            "error": "Erro ao salvar os confrontos no banco de dados."
        }), 500


    
    return jsonify({
        "ok": True,
        "message": (
            f"Calendário salvo com sucesso! "
            f"{len(scheduled_matches)} confrontos cadastrados. "
            f"{len(unscheduled_matches)} confrontos sem horário disponível."
        ),
        "saved_count": len(scheduled_matches),
        "unscheduled_count": len(unscheduled_matches)
    })
       

# =========================
# SITEMAP SEO
# =========================

@app.route("/sitemap.xml")
def sitemap():
    ads = (
        Ad.query
        .join(
            User,
            Ad.user_id == User.id
        )
        .filter(
            Ad.is_active.is_(True),
            Ad.slug.isnot(None),
            Ad.slug != "",
            or_(
                Ad.blocked_until.is_(None),
                Ad.blocked_until <= utc_now()
            ),
            or_(
                User.blocked_until.is_(None),
                User.blocked_until <= utc_now()
            )
        )
        .order_by(
            Ad.created_at.desc()
        )
        .all()
    )
    
    jobs = (
        JobVacancy.query
        .filter(
            JobVacancy.is_active.is_(True)
        )
        .order_by(
            JobVacancy.updated_at.desc()
        )
        .all()
    )

    base_url = BASE_URL.rstrip("/")

    xml_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    ]

    # Página inicial
    xml_parts.append(
        f"""
        <url>
            <loc>{base_url}/</loc>
        </url>
        """
    )

    # Pesquisa
    xml_parts.append(
        f"""
        <url>
            <loc>{base_url}/search-page</loc>
        </url>
        """
    )

    # Vitrine
    xml_parts.append(
        f"""
        <url>
            <loc>{base_url}/vitrine-page</loc>
        </url>
        """
    )

    # Feed
    xml_parts.append(
        f"""
        <url>
            <loc>{base_url}/feed-page</loc>
        </url>
        """
    )
    
    # Anunciar empresa
    xml_parts.append(
        f"""
        <url>
            <loc>{base_url}/anunciar-empresa</loc>
        </url>
        """
    )
    
    # Buscar empresas
    xml_parts.append(
        f"""
        <url>
            <loc>{base_url}/buscar-empresas</loc>
        </url>
        """
    )
    
    # Catálogo
    xml_parts.append(
        f"""
        <url>
            <loc>{base_url}/catalogo</loc>
        </url>
        """
    )
    
    # Empregos
    xml_parts.append(
        f"""
        <url>
            <loc>{base_url}/empregos</loc>
        </url>
        """
    )

    # Páginas individuais dos anúncios
    for ad in ads:
        ad_url = (
            f"{base_url}/anuncio/{ad.slug}"
        )

        lastmod = ""

        if ad.created_at:
            lastmod = (
                ad.created_at
                .date()
                .isoformat()
            )

        if lastmod:
            xml_parts.append(
                f"""
                <url>
                    <loc>{ad_url}</loc>
                    <lastmod>{lastmod}</lastmod>
                </url>
                """
            )
        else:
            xml_parts.append(
                f"""
                <url>
                    <loc>{ad_url}</loc>
                </url>
                """
            )

    # ============================================================
    # VAGAS DE EMPREGO
    # ============================================================

    for vacancy in jobs:

        job_url = (
            f"{base_url}/empregos/{vacancy.id}"
        )

        lastmod_date = (
            vacancy.updated_at
            or vacancy.published_at
            or vacancy.created_at
        )

        if lastmod_date:
            lastmod = (
                lastmod_date
                .date()
                .isoformat()
            )

            xml_parts.append(
                f"""
                <url>
                    <loc>{job_url}</loc>
                    <lastmod>{lastmod}</lastmod>
                </url>
                """
            )

        else:
            xml_parts.append(
                f"""
                <url>
                    <loc>{job_url}</loc>
                </url>
                """
            )

    # ============================================================
    # PÁGINAS SEO DINÂMICAS — SERVIÇOS POR CIDADE
    # ============================================================

    seo_service_links = get_seo_service_links(
        min_ads=1,
        limit=1000
    )

    for item in seo_service_links:
        service_url = (
            f"{base_url}{item['url']}"
        )

        xml_parts.append(
            f"""
            <url>
                <loc>{service_url}</loc>
            </url>
            """
        )

    xml_parts.append(
        "</urlset>"
    )

    xml = "\n".join(
        xml_parts
    )

    return Response(
        xml,
        mimetype="application/xml"
    )
    
    
# =========================
# ROBOTS.TXT - SEO
# =========================

@app.route("/robots.txt")
def robots_txt():
    base_url = BASE_URL.rstrip("/")

    content = f"""User-agent: *
Allow: /

Sitemap: {base_url}/sitemap.xml
"""

    return Response(
        content,
        mimetype="text/plain"
    )    
    
@app.route("/")
def home():

    now = utc_now()

    featured_offers = (
        AffiliateProduct.query
        .filter(
            AffiliateProduct.is_active.is_(True),
            or_(
                AffiliateProduct.expires_at.is_(None),
                AffiliateProduct.expires_at >= now
            )
        )
        .order_by(
            AffiliateProduct.is_featured.desc(),
            AffiliateProduct.created_at.desc()
        )
        .limit(4)
        .all()
    )

    return render_template(
        "home.html",
        featured_offers=featured_offers
    )
    
@app.route("/anunciar-empresa")
def anunciar_empresa():
    return render_template("anunciar_empresa.html")

@app.route("/buscar-empresas")
def buscar_empresas():
    return render_template("buscar_empresas.html")    

@app.route("/catalogo")
def catalogo():
    page = request.args.get(
        "page",
        1,
        type=int
    )

    page = max(
        page,
        1
    )

    per_page = 20

    query = (
        Ad.query
        .join(
            User,
            Ad.user_id == User.id
        )
        .filter(
            Ad.is_active.is_(True),
            Ad.slug.isnot(None),
            Ad.slug != "",
            or_(
                Ad.blocked_until.is_(None),
                Ad.blocked_until <= utc_now()
            ),
            or_(
                User.blocked_until.is_(None),
                User.blocked_until <= utc_now()
            )
        )
    )

    total_ads = query.count()

    ads = (
        query
        .order_by(
            Ad.created_at.desc()
        )
        .offset(
            (page - 1) * per_page
        )
        .limit(
            per_page
        )
        .all()
    )

    total_pages = max(
        1,
        (
            total_ads + per_page - 1
        ) // per_page
    )

    if page > total_pages:
        return redirect(
            url_for(
                "catalogo",
                page=total_pages
            )
        )

    seo_service_links = (
        get_seo_service_links(
            min_ads=1,
            limit=40
        )
    )

    return render_template(
        "catalogo.html",
        ads=ads,
        page=page,
        total_pages=total_pages,
        total_ads=total_ads,
        seo_service_links=seo_service_links
    )
    
@app.route("/servicos/<city_slug>/<service_slug>")
def seo_service_page(city_slug, service_slug):
    city_slug = generate_slug(city_slug)
    service_slug = generate_slug(service_slug)

    if not city_slug or not service_slug:
        abort(404)

    # Descobre qual cidade real corresponde ao slug da URL.
    city_rows = (
        db.session.query(Ad.city)
        .join(
            User,
            Ad.user_id == User.id
        )
        .filter(
            Ad.is_active.is_(True),
            Ad.city.isnot(None),
            Ad.city != "",
            or_(
                Ad.blocked_until.is_(None),
                Ad.blocked_until <= utc_now()
            ),
            or_(
                User.blocked_until.is_(None),
                User.blocked_until <= utc_now()
            )
        )
        .distinct()
        .all()
    )

    real_city = None

    for row in city_rows:
        city_name = row[0]

        if generate_slug(city_name) == city_slug:
            real_city = city_name
            break

    if not real_city:
        abort(404)

    # O slug "pet-shop" vira "pet shop" para a pesquisa.
    service_term = service_slug.replace("-", " ").strip()

    query = (
        Ad.query
        .join(
            User,
            Ad.user_id == User.id
        )
        .filter(
            Ad.is_active.is_(True),
            Ad.slug.isnot(None),
            Ad.slug != "",
            Ad.city == real_city,
            or_(
                Ad.blocked_until.is_(None),
                Ad.blocked_until <= utc_now()
            ),
            or_(
                User.blocked_until.is_(None),
                User.blocked_until <= utc_now()
            ),
            or_(
                Ad.title.ilike(f"%{service_term}%"),
                Ad.description.ilike(f"%{service_term}%"),
                Ad.keywords.any(
                    Keyword.keyword.ilike(
                        f"%{service_term}%"
                    )
                )
            )
        )
        .order_by(
            plan_priority_case(),
            Ad.created_at.desc()
        )
    )

    ads = query.all()

    # Não criamos página SEO sem conteúdo real.
    if not ads:
        abort(404)

    # Recupera uma forma mais natural do nome do serviço
    # a partir das palavras-chave cadastradas.
    service_name = service_term.title()

    for ad in ads:
        for keyword in ad.keywords:
            if generate_slug(keyword.keyword) == service_slug:
                service_name = keyword.keyword.strip()
                break
        else:
            continue
        break

    canonical_url = (
        f"{BASE_URL.rstrip('/')}/servicos/"
        f"{city_slug}/{service_slug}"
    )

    seo_title = (
        f"{service_name} em {real_city} | CataLogin"
    )

    seo_description = (
        f"Encontre {service_name} em {real_city}. "
        f"Veja empresas, profissionais e serviços "
        f"cadastrados no CataLogin."
    )

    return render_template(
        "seo_service.html",
        ads=ads,
        city=real_city,
        city_slug=city_slug,
        service_name=service_name,
        service_slug=service_slug,
        total_ads=len(ads),
        canonical_url=canonical_url,
        seo_title=seo_title,
        seo_description=seo_description
    )    

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

@app.route("/terms-of-use")
def terms_of_use_page():
    return render_template("terms_of_use.html")    


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
    accepted_terms_of_use = bool(data.get("accepted_terms_of_use"))

    if not name or not cpf or not email or not phone or not password:
        return jsonify({"message": "Preencha todos os campos obrigatórios"}), 400

    if not accepted_privacy_policy or not accepted_terms_of_use:
        return jsonify({
            "message": "Você precisa aceitar a Política de Privacidade e os Termos de Uso para se cadastrar."
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
    
    
    query = Ad.query.join(User, Ad.user_id == User.id).filter(
        Ad.is_active == True,
        or_(Ad.blocked_until.is_(None), Ad.blocked_until <= utc_now()),
        or_(User.blocked_until.is_(None), User.blocked_until <= utc_now())
    )
    
    has_search = bool(term or country or state or city or municipality or neighborhood or street or complement)

    if not has_search:
        query = query.filter(
            or_(
                Ad.plan == "VIP_PREMIUM",
                Ad.show_on_home.is_(True)
            )
        )

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
    cached_states = get_cached_location(
        "states"
    )

    if cached_states is not None:
        return jsonify(cached_states)

    try:
        url = (
            "https://servicodados.ibge.gov.br/"
            "api/v1/localidades/estados?orderBy=nome"
        )

        data = fetch_ibge_json(url)

        states = [
            {
                "id": item["id"],
                "sigla": item["sigla"],
                "nome": item["nome"]
            }
            for item in data
        ]

        set_cached_location(
            "states",
            states,
            STATES_CACHE_SECONDS
        )

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
        
    city_cache_key = uf

    cached_cities = get_cached_location(
        "cities",
        city_cache_key
    )

    if cached_cities is not None:
        return jsonify(cached_cities)    

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
            
        set_cached_location(
            "cities",
            cities,
            CITIES_CACHE_SECONDS,
            city_cache_key
        )    

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
    neighborhood_cache_key = (
        state.casefold(),
        city.casefold()
    )

    cached_neighborhoods = (
        get_cached_location(
            "neighborhoods",
            neighborhood_cache_key
        )
    )

    if cached_neighborhoods is not None:
        return jsonify(
            cached_neighborhoods
        )

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
            "limit": 50
        }

        headers = {
            "User-Agent": "catalogo-app/1.0"
        }

        response = requests.get(url, params=params, headers=headers, timeout=(3, 7))
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
            
        set_cached_location(
            "neighborhoods",
            neighborhoods,
            NEIGHBORHOODS_CACHE_SECONDS,
            neighborhood_cache_key
        )
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

        
        all_names = set()

        for item in managed_streets:
            all_names.add(item["nome"])

        for item in ad_streets:
            all_names.add(item["nome"])

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

# ==========================================
# OLIMPÍADAS BOMBEIRO MIRIM - ADMINISTRAÇÃO
# ==========================================

@app.route("/admin/olimpiadas")
@admin_required_page
def admin_olympics_page():

    return render_template(
        "admin_olympics.html",
        active_page="olympics"
    )    


@app.route("/admin/olimpiadas/edicoes/criar", methods=["POST"])
@admin_required_page
def admin_create_olympic_edition():

    data = request.get_json(silent=True) or {}

    name = str(data.get("name") or "").strip()
    year_raw = data.get("year")
    description = str(data.get("description") or "").strip()

    if not name:
        return jsonify({
            "message": "Informe o nome da edição."
        }), 400

    try:
        year = int(year_raw)
    except (TypeError, ValueError):
        return jsonify({
            "message": "Informe um ano válido."
        }), 400

    if year < 2000 or year > 2100:
        return jsonify({
            "message": "Informe um ano entre 2000 e 2100."
        }), 400

    edition = OlympicEdition(
        name=name,
        year=year,
        description=description or None,
        is_active=True
    )

    try:
        db.session.add(edition)
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("Erro ao cadastrar edição das Olimpíadas")
        return jsonify({
            "message": "Não foi possível cadastrar a edição."
        }), 500

    return jsonify({
        "message": "Edição cadastrada com sucesso!",
        "edition": {
            "id": edition.id,
            "name": edition.name,
            "year": edition.year,
            "description": edition.description,
            "is_active": edition.is_active
        }
    }), 201
    

# ==========================================
# OLIMPÍADAS - LISTAR EDIÇÕES
# ==========================================

@app.route("/admin/olimpiadas/edicoes", methods=["GET"])
@admin_required_page
def admin_list_olympic_editions():

    editions = (
        OlympicEdition.query
        .order_by(
            OlympicEdition.year.desc(),
            OlympicEdition.id.desc()
        )
        .all()
    )

    return jsonify({
        "editions": [
            {
                "id": edition.id,
                "name": edition.name,
                "year": edition.year,
                "start_date": (
                    edition.start_date.isoformat()
                    if edition.start_date else None
                ),
                "end_date": (
                    edition.end_date.isoformat()
                    if edition.end_date else None
                ),
                "description": edition.description,
                "is_active": edition.is_active
            }
            for edition in editions
        ]
    }), 200
    

# ==========================================
# OLIMPÍADAS - EDITAR EDIÇÃO
# ==========================================

@app.route("/admin/olimpiadas/edicoes/<int:edition_id>/editar", methods=["PUT"])
@admin_required_page
def admin_update_olympic_edition(edition_id):

    edition = db.session.get(OlympicEdition, edition_id)

    if not edition:
        return jsonify({
            "message": "Edição não encontrada."
        }), 404

    data = request.get_json(silent=True) or {}

    name = str(data.get("name") or "").strip()
    description = str(data.get("description") or "").strip()

    try:
        year = int(data.get("year"))
    except (TypeError, ValueError):
        return jsonify({
            "message": "Informe um ano válido."
        }), 400

    if not name:
        return jsonify({
            "message": "Informe o nome da edição."
        }), 400

    if year < 2000 or year > 2100:
        return jsonify({
            "message": "Informe um ano entre 2000 e 2100."
        }), 400

    edition.name = name
    edition.year = year
    edition.description = description or None

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("Erro ao atualizar edição das Olimpíadas")

        return jsonify({
            "message": "Não foi possível atualizar a edição."
        }), 500

    return jsonify({
        "message": "Edição atualizada com sucesso!",
        "edition": {
            "id": edition.id,
            "name": edition.name,
            "year": edition.year,
            "description": edition.description,
            "is_active": edition.is_active
        }
    }), 200
    

# ==========================================
# OLIMPÍADAS - ATIVAR / DESATIVAR EDIÇÃO
# ==========================================

@app.route(
    "/admin/olimpiadas/edicoes/<int:edition_id>/situacao",
    methods=["PUT"]
)
@admin_required_page
def admin_toggle_olympic_edition(edition_id):

    edition = db.session.get(OlympicEdition, edition_id)

    if not edition:
        return jsonify({
            "message": "Edição não encontrada."
        }), 404

    edition.is_active = not edition.is_active

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception(
            "Erro ao alterar situação da edição das Olimpíadas"
        )
        return jsonify({
            "message": "Não foi possível alterar a situação da edição."
        }), 500

    return jsonify({
        "message": (
            "Edição ativada com sucesso!"
            if edition.is_active
            else "Edição desativada com sucesso!"
        ),
        "id": edition.id,
        "is_active": edition.is_active
    }), 200
    

# ==========================================
# OLIMPÍADAS - CADASTRAR EQUIPE
# ==========================================

@app.route("/admin/olimpiadas/equipes/criar", methods=["POST"])
@admin_required_page
def admin_create_olympic_team():

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "message": "Envie os dados da equipe em formato JSON."
        }), 400

    try:
        edition_id = int(data.get("edition_id"))
    except (TypeError, ValueError):
        return jsonify({
            "message": "Selecione uma edição válida."
        }), 400

    edition = db.session.get(OlympicEdition, edition_id)

    if not edition:
        return jsonify({
            "message": "Edição não encontrada."
        }), 404

    if not edition.is_active:
        return jsonify({
            "message": "Não é possível cadastrar equipes em uma edição inativa."
        }), 400

    name = str(data.get("name") or "").strip()
    color = str(data.get("color") or "").strip()
    coach = str(data.get("coach") or "").strip()
    shift = str(data.get("shift") or "").strip().lower()

    if not name or not color or not coach:
        return jsonify({
            "message": "Informe o nome, a cor e o técnico da equipe."
        }), 400

    if shift not in ("matutino", "vespertino"):
        return jsonify({
            "message": "O turno deve ser matutino ou vespertino."
        }), 400

    if len(name) > 100 or len(color) > 50 or len(coach) > 150:
        return jsonify({
            "message": "Um ou mais campos excedem o tamanho permitido."
        }), 400

    existing_team = OlympicTeam.query.filter_by(
        edition_id=edition_id,
        color=color,
        shift=shift
    ).first()

    if existing_team:
        return jsonify({
            "message": "Já existe uma equipe com essa cor e turno nesta edição."
        }), 409

    team = OlympicTeam(
        edition_id=edition_id,
        name=name,
        color=color,
        coach=coach,
        shift=shift
    )

    try:
        db.session.add(team)
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("Erro ao cadastrar equipe das Olimpíadas")

        return jsonify({
            "message": "Não foi possível cadastrar a equipe."
        }), 500

    return jsonify({
        "message": "Equipe cadastrada com sucesso!",
        "team": {
            "id": team.id,
            "edition_id": team.edition_id,
            "name": team.name,
            "color": team.color,
            "coach": team.coach,
            "shift": team.shift
        }
    }), 201
    

# ==========================================
# OLIMPÍADAS - LISTAR EQUIPES POR EDIÇÃO
# ==========================================

@app.route(
    "/admin/olimpiadas/edicoes/<int:edition_id>/equipes",
    methods=["GET"]
)
@admin_required_page
def admin_list_olympic_teams(edition_id):

    edition = db.session.get(OlympicEdition, edition_id)

    if not edition:
        return jsonify({
            "message": "Edição não encontrada."
        }), 404

    teams = (
        OlympicTeam.query
        .filter_by(edition_id=edition_id)
        .order_by(
            OlympicTeam.shift.asc(),
            OlympicTeam.color.asc(),
            OlympicTeam.id.asc()
        )
        .all()
    )

    return jsonify({
        "edition": {
            "id": edition.id,
            "name": edition.name,
            "year": edition.year,
            "is_active": edition.is_active
        },
        "teams": [
            {
                "id": team.id,
                "edition_id": team.edition_id,
                "name": team.name,
                "color": team.color,
                "coach": team.coach,
                "shift": team.shift
            }
            for team in teams
        ]
    }), 200
    
    

# ==========================================
# OLIMPÍADAS - EDITAR EQUIPE
# ==========================================

@app.route(
    "/admin/olimpiadas/equipes/<int:team_id>/editar",
    methods=["PUT"]
)
@admin_required_page
def admin_edit_olympic_team(team_id):

    team = db.session.get(OlympicTeam, team_id)

    if not team:
        return jsonify({
            "message": "Equipe não encontrada."
        }), 404

    edition = db.session.get(
        OlympicEdition,
        team.edition_id
    )

    if not edition or not edition.is_active:
        return jsonify({
            "message": "Não é possível editar equipes de uma edição inativa."
        }), 400

    data = request.get_json(silent=True) or {}

    name = str(data.get("name") or "").strip()
    color = str(data.get("color") or "").strip()
    coach = str(data.get("coach") or "").strip()
    shift = str(data.get("shift") or "").strip().lower()

    if not all([name, color, coach, shift]):
        return jsonify({
            "message": "Preencha todos os campos da equipe."
        }), 400

    if shift not in ("matutino", "vespertino"):
        return jsonify({
            "message": "O turno deve ser matutino ou vespertino."
        }), 400

    if len(name) > 100 or len(color) > 50 or len(coach) > 150:
        return jsonify({
            "message": "Um ou mais campos excedem o tamanho permitido."
        }), 400

    duplicate = (
        OlympicTeam.query
        .filter(
            OlympicTeam.edition_id == team.edition_id,
            OlympicTeam.color == color,
            OlympicTeam.shift == shift,
            OlympicTeam.id != team.id
        )
        .first()
    )

    if duplicate:
        return jsonify({
            "message": "Já existe outra equipe com essa cor e turno nesta edição."
        }), 409

    try:
        team.name = name
        team.color = color
        team.coach = coach
        team.shift = shift

        db.session.commit()

    except Exception:
        db.session.rollback()

        return jsonify({
            "message": "Erro ao atualizar a equipe."
        }), 500

    return jsonify({
        "message": "Equipe atualizada com sucesso!",
        "team": {
            "id": team.id,
            "edition_id": team.edition_id,
            "name": team.name,
            "color": team.color,
            "coach": team.coach,
            "shift": team.shift
        }
    }), 200
    

# ==========================================
# OLIMPÍADAS - EXCLUIR EQUIPE
# ==========================================

@app.route(
    "/admin/olimpiadas/equipes/<int:team_id>/excluir",
    methods=["DELETE"]
)
@admin_required_page
def admin_delete_olympic_team(team_id):

    team = db.session.get(OlympicTeam, team_id)

    if not team:
        return jsonify({
            "message": "Equipe não encontrada."
        }), 404

    edition = db.session.get(
        OlympicEdition,
        team.edition_id
    )

    if not edition or not edition.is_active:
        return jsonify({
            "message": "Não é possível excluir equipes de uma edição inativa."
        }), 400

    try:
        db.session.delete(team)
        db.session.commit()

    except Exception:
        db.session.rollback()

        return jsonify({
            "message": (
                "Não foi possível excluir a equipe. "
                "Verifique se existem registros vinculados a ela."
            )
        }), 409

    return jsonify({
        "message": "Equipe excluída com sucesso!"
    }), 200
  
# ==========================================
# OLIMPÍADAS - EXCLUIR BRIGADINO SEM EQUIPE
# ==========================================

@app.route(
    "/admin/olimpiadas/edicoes/<int:edition_id>/novos-brigadinos/<int:athlete_id>",
    methods=["DELETE"]
)
@admin_required_page
def admin_delete_new_brigadino(edition_id, athlete_id):

    edition = db.session.get(OlympicEdition, edition_id)

    if not edition:
        return jsonify({
            "success": False,
            "message": "Edição das Olimpíadas não encontrada."
        }), 404

    athlete = db.session.get(OlympicAthlete, athlete_id)

    if not athlete or athlete.edition_id != edition_id:
        return jsonify({
            "success": False,
            "message": "Brigadino não encontrado nesta edição."
        }), 404

    # Protege brigadinos que já pertencem a uma equipe.
    if athlete.team_id is not None:
        return jsonify({
            "success": False,
            "message": (
                "Este brigadino já pertence a uma equipe "
                "e não pode ser excluído pela lista de espera."
            )
        }), 409

    try:
        athlete_name = athlete.name

        db.session.delete(athlete)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": (
                f"Brigadino {athlete_name} excluído "
                "da lista de espera com sucesso."
            )
        }), 200

    except Exception:
        db.session.rollback()

        app.logger.exception(
            "Erro ao excluir brigadino aguardando distribuição"
        )

        return jsonify({
            "success": False,
            "message": "Não foi possível excluir o brigadino."
        }), 500
  
# ==========================================
# OLIMPÍADAS - CONFIRMAR DISTRIBUIÇÃO
# ==========================================

@app.route(
    "/admin/olimpiadas/edicoes/<int:edition_id>/confirmar-distribuicao",
    methods=["POST"]
)
@admin_required_page
def admin_confirm_new_brigadinos_distribution(edition_id):

    data = request.get_json(silent=True) or {}
    distribution = data.get("distribution")

    if not isinstance(distribution, list) or not distribution:
        return jsonify({
            "success": False,
            "message": "Nenhuma distribuição foi enviada."
        }), 400

    edition = db.session.get(OlympicEdition, edition_id)

    if not edition:
        return jsonify({
            "success": False,
            "message": "Edição não encontrada."
        }), 404

    if not edition.is_active:
        return jsonify({
            "success": False,
            "message": "A edição selecionada não está ativa."
        }), 400

    # Consulta os brigadinos que ainda estão sem equipe.
    pending = OlympicAthlete.query.filter(
        OlympicAthlete.edition_id == edition_id,
        OlympicAthlete.team_id.is_(None)
    ).all()

    pending_by_id = {
        athlete.id: athlete for athlete in pending
    }

    # Todos os brigadinos pendentes devem estar na confirmação.
    submitted_ids = [
        item.get("athlete_id")
        for item in distribution
        if isinstance(item, dict)
    ]

    if (
        len(submitted_ids) != len(distribution)
        or len(submitted_ids) != len(set(submitted_ids))
        or set(submitted_ids) != set(pending_by_id)
    ):
        return jsonify({
            "success": False,
            "message": (
                "A lista de brigadinos mudou ou a distribuição "
                "está incompleta. Gere uma nova prévia."
            )
        }), 409

    # Consulta somente equipes da edição selecionada.
    teams = OlympicTeam.query.filter_by(
        edition_id=edition_id
    ).all()

    teams_by_id = {
        team.id: team for team in teams
    }

    # Valida toda a distribuição antes de modificar qualquer atleta.
    for item in distribution:

        athlete = pending_by_id[item["athlete_id"]]
        team = teams_by_id.get(item.get("team_id"))

        if not team:
            return jsonify({
                "success": False,
                "message": "Uma das equipes não pertence à edição."
            }), 400

        if (
            str(athlete.shift).lower()
            != str(team.shift).lower()
        ):
            return jsonify({
                "success": False,
                "message": (
                    f"A equipe selecionada para {athlete.name} "
                    "não pertence ao turno correto."
                )
            }), 400

    try:

        for item in distribution:
            athlete = pending_by_id[item["athlete_id"]]
            athlete.team_id = item["team_id"]

        db.session.commit()

        return jsonify({
            "success": True,
            "total": len(distribution),
            "message": (
                f"{len(distribution)} brigadino(s) "
                "distribuído(s) com sucesso."
            )
        }), 200

    except Exception:

        db.session.rollback()

        app.logger.exception(
            "Erro ao confirmar distribuição de brigadinos"
        )

        return jsonify({
            "success": False,
            "message": "Erro ao salvar a distribuição."
        }), 500    
 
# ==========================================
# OLIMPÍADAS - PRÉVIA DA DISTRIBUIÇÃO
# ==========================================

@app.route(
    "/admin/olimpiadas/edicoes/<int:edition_id>/previa-distribuicao",
    methods=["GET"]
)
@admin_required_page
def admin_preview_new_brigadinos_distribution(edition_id):

    edition = db.session.get(OlympicEdition, edition_id)

    if not edition:
        return jsonify({
            "success": False,
            "message": "Edição não encontrada."
        }), 404

    # Consulta somente os brigadinos ainda sem equipe.
    pending_athletes = (
        OlympicAthlete.query
        .filter(
            OlympicAthlete.edition_id == edition_id,
            OlympicAthlete.team_id.is_(None)
        )
        .all()
    )

    if not pending_athletes:
        return jsonify({
            "success": False,
            "message": "Não existem brigadinos aguardando distribuição."
        }), 400

    # Consulta as equipes da edição selecionada.
    teams = (
        OlympicTeam.query
        .filter_by(edition_id=edition_id)
        .all()
    )

    teams_data = []

    for team in teams:

        members = (
            OlympicAthlete.query
            .filter_by(
                edition_id=edition_id,
                team_id=team.id
            )
            .all()
        )

        teams_data.append({
            "id": team.id,
            "name": team.name,
            "color": team.color,
            "coach": team.coach,
            "shift": team.shift,
            "athletes": [
                {
                    "id": member.id,
                    "age": member.age,
                    "sex": member.sex
                }
                for member in members
            ]
        })

    pending_data = [
        {
            "id": athlete.id,
            "name": athlete.name,
            "age": athlete.age,
            "sex": athlete.sex,
            "shift": athlete.shift
        }
        for athlete in pending_athletes
    ]

    try:

        distribution = calculate_new_brigadinos_distribution(
            teams_data,
            pending_data
        )

    except (ValueError, TypeError) as error:

        return jsonify({
            "success": False,
            "message": str(error)
        }), 400

    return jsonify({
        "success": True,
        "edition_id": edition_id,
        "total": len(distribution),
        "distribution": distribution,
        "message": "Prévia gerada. Nenhuma alteração foi salva."
    }), 200
 
# ==========================================
# OLIMPÍADAS - ALGORITMO DE DISTRIBUIÇÃO
# ==========================================

def calculate_new_brigadinos_distribution(teams, new_athletes):

    import random

    # Cópia dos dados para simular a distribuição
    # sem modificar o banco de dados.
    team_states = []

    for team in teams:

        athletes = list(team["athletes"])

        team_states.append({
            "id": team["id"],
            "name": team["name"],
            "color": team["color"],
            "coach": team["coach"],
            "shift": team["shift"],
            "athletes": athletes
        })

    # Embaralha os novos brigadinos para evitar
    # que a ordem de cadastro determine o resultado.
    pending = list(new_athletes)
    random.shuffle(pending)

    distribution = []

    for athlete in pending:

        shift = athlete["shift"]

        eligible = [
            team for team in team_states
            if str(team["shift"]).lower() == str(shift).lower()
        ]

        if not eligible:
            raise ValueError(
                f"Não existem equipes disponíveis para o turno {shift}."
            )

        # PRIORIDADE 1: menor quantidade de integrantes
        minimum_total = min(
            len(team["athletes"]) for team in eligible
        )

        candidates = [
            team for team in eligible
            if len(team["athletes"]) == minimum_total
        ]

        # PRIORIDADE 2: equilíbrio de sexo
        # Prefere a equipe com menos integrantes
        # do mesmo sexo do novo brigadino.
        minimum_same_sex = min(
            sum(
                1 for member in team["athletes"]
                if member["sex"] == athlete["sex"]
            )
            for team in candidates
        )

        candidates = [
            team for team in candidates
            if sum(
                1 for member in team["athletes"]
                if member["sex"] == athlete["sex"]
            ) == minimum_same_sex
        ]

        # PRIORIDADE 3: equilíbrio de idade
        # Prefere a equipe com menos integrantes
        # da mesma faixa etária.
        def age_group(age):
            return "7-9" if int(age) <= 9 else "10-14"

        athlete_age_group = age_group(athlete["age"])

        minimum_same_age_group = min(
            sum(
                1 for member in team["athletes"]
                if age_group(member["age"]) == athlete_age_group
            )
            for team in candidates
        )

        candidates = [
            team for team in candidates
            if sum(
                1 for member in team["athletes"]
                if age_group(member["age"]) == athlete_age_group
            ) == minimum_same_age_group
        ]

        # PRIORIDADE 4: sorteio entre equipes empatadas
        selected_team = random.choice(candidates)

        distribution.append({
            "athlete_id": athlete["id"],
            "athlete_name": athlete["name"],
            "age": athlete["age"],
            "sex": athlete["sex"],
            "shift": athlete["shift"],
            "team_id": selected_team["id"],
            "team_name": selected_team["name"],
            "team_color": selected_team["color"],
            "team_coach": selected_team["coach"]
        })

        # Atualiza somente a simulação.
        # O próximo brigadino já considera
        # a quantidade atualizada de integrantes.
        selected_team["athletes"].append({
            "id": athlete["id"],
            "age": athlete["age"],
            "sex": athlete["sex"]
        })

    return distribution  
  
# ==========================================
# OLIMPÍADAS - EQUIPES PARA DISTRIBUIÇÃO
# ==========================================

@app.route(
    "/admin/olimpiadas/edicoes/<int:edition_id>/equipes-distribuicao",
    methods=["GET"]
)
@admin_required_page
def admin_olympic_distribution_teams(edition_id):

    edition = db.session.get(OlympicEdition, edition_id)

    if not edition:
        return jsonify({
            "success": False,
            "message": "Edição não encontrada."
        }), 404

    teams = (
        OlympicTeam.query
        .filter_by(edition_id=edition_id)
        .order_by(OlympicTeam.id.asc())
        .all()
    )

    result = []

    for team in teams:

        athletes = (
            OlympicAthlete.query
            .filter_by(
                edition_id=edition_id,
                team_id=team.id
            )
            .all()
        )

        result.append({
            "id": team.id,
            "name": team.name,
            "color": team.color,
            "coach": team.coach,
            "shift": team.shift,
            "total": len(athletes),
            "athletes": [
                {
                    "id": athlete.id,
                    "age": athlete.age,
                    "sex": athlete.sex
                }
                for athlete in athletes
            ]
        })

    return jsonify({
        "success": True,
        "teams": result
    }), 200
  
# ==========================================
# OLIMPÍADAS - LISTAR BRIGADINOS SEM EQUIPE
# ==========================================

@app.route(
    "/admin/olimpiadas/edicoes/<int:edition_id>/novos-brigadinos",
    methods=["GET"]
)
@admin_required_page
def admin_list_new_olympic_brigadinos(edition_id):

    edition = db.session.get(OlympicEdition, edition_id)

    if not edition:
        return jsonify({
            "success": False,
            "message": "Edição não encontrada."
        }), 404

    athletes = (
        OlympicAthlete.query
        .filter(
            OlympicAthlete.edition_id == edition_id,
            OlympicAthlete.team_id.is_(None)
        )
        .order_by(OlympicAthlete.name.asc())
        .all()
    )

    return jsonify({
        "success": True,
        "total": len(athletes),
        "brigadinos": [
            {
                "id": athlete.id,
                "name": athlete.name,
                "age": athlete.age,
                "sex": athlete.sex,
                "shift": athlete.shift
            }
            for athlete in athletes
        ]
    }), 200    

# ==========================================
# OLIMPÍADAS - CADASTRAR NOVO BRIGADINO
# ==========================================

@app.route(
    "/admin/olimpiadas/novos-brigadinos/criar",
    methods=["POST"]
)
@admin_required_page
def admin_create_new_olympic_brigadino():

    data = request.get_json(silent=True) or {}

    name = str(data.get("name") or "").strip()
    sex = str(data.get("sex") or "").strip().upper()
    shift = str(data.get("shift") or "").strip().lower()

    try:
        edition_id = int(data.get("edition_id"))
        age = int(data.get("age"))
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "message": "Edição ou idade inválida."
        }), 400

    if not name or len(name) > 150:
        return jsonify({
            "success": False,
            "message": "Informe um nome válido de até 150 caracteres."
        }), 400

    if age < 7 or age > 14:
        return jsonify({
            "success": False,
            "message": "A idade deve estar entre 7 e 14 anos."
        }), 400

    if sex not in ("MASCULINO", "FEMININO"):
        return jsonify({
            "success": False,
            "message": "Selecione o sexo do brigadino."
        }), 400

    if shift not in ("matutino", "vespertino"):
        return jsonify({
            "success": False,
            "message": "Selecione um turno válido."
        }), 400

    edition = db.session.get(OlympicEdition, edition_id)

    if not edition:
        return jsonify({
            "success": False,
            "message": "Edição não encontrada."
        }), 404

    if not edition.is_active:
        return jsonify({
            "success": False,
            "message": "A edição selecionada está inativa."
        }), 400
        
    # ==========================================
    # VERIFICAR POSSÍVEL CADASTRO DUPLICADO
    # ==========================================

    normalized_name = " ".join(name.casefold().split())

    existing_athletes = OlympicAthlete.query.filter_by(
        edition_id=edition_id,
        age=age
    ).all()

    possible_duplicates = [
        athlete
        for athlete in existing_athletes
        if " ".join((athlete.name or "").casefold().split())
        == normalized_name
    ]

    if possible_duplicates and data.get("confirm_duplicate") is not True:

        duplicates = []

        for athlete in possible_duplicates:

            team = (
                db.session.get(OlympicTeam, athlete.team_id)
                if athlete.team_id is not None
                else None
            )

            duplicates.append({
                "id": athlete.id,
                "name": athlete.name,
                "age": athlete.age,
                "team": (
                    f"{team.color} — {team.coach}"
                    if team else "Aguardando distribuição"
                )
            })

        return jsonify({
            "success": False,
            "possible_duplicate": True,
            "message": (
                "Já existe um brigadino com o mesmo "
                "nome completo e idade nesta edição."
            ),
            "duplicates": duplicates
        }), 409    
    

    try:
        athlete = OlympicAthlete(
            edition_id=edition_id,
            team_id=None,
            name=name,
            age=age,
            sex=sex,
            shift=shift
        )

        db.session.add(athlete)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Brigadino cadastrado e aguardando distribuição.",
            "athlete_id": athlete.id
        }), 201

    except Exception:
        db.session.rollback()
        app.logger.exception("Erro ao cadastrar novo brigadino")

        return jsonify({
            "success": False,
            "message": "Erro interno ao cadastrar brigadino."
        }), 500

# ==========================================
# OLIMPÍADAS - CADASTRAR ATLETA
# ==========================================

@app.route("/admin/olimpiadas/atletas/criar", methods=["POST"])
@admin_required_page
def admin_create_olympic_athlete():

    data = request.get_json(silent=True) or {}

    edition_id = data.get("edition_id")
    team_id = data.get("team_id")
    name = str(data.get("name") or "").strip()
    age_str = str(data.get("age") or "").strip()
    sex = str(data.get("sex") or "").strip().upper()

    # Valida os identificadores
    try:
        edition_id = int(edition_id)
        team_id = int(team_id)

        if edition_id <= 0 or team_id <= 0:
            raise ValueError()

    except (TypeError, ValueError):
        return jsonify({
            "message": "Edição ou equipe inválida."
        }), 400

    # Verifica a edição
    edition = db.session.get(
        OlympicEdition,
        edition_id
    )

    if not edition:
        return jsonify({
            "message": "Edição não encontrada."
        }), 404

    if not edition.is_active:
        return jsonify({
            "message": "Não é possível cadastrar atletas em uma edição inativa."
        }), 400

    # Verifica se a equipe pertence à edição
    team = db.session.get(
        OlympicTeam,
        team_id
    )

    if not team or team.edition_id != edition_id:
        return jsonify({
            "message": "A equipe não pertence à edição selecionada."
        }), 400

    # Valida o nome
    if not name:
        return jsonify({
            "message": "Informe o nome do atleta."
        }), 400

    if len(name) > 150:
        return jsonify({
            "message": "O nome do atleta excede 150 caracteres."
        }), 400

    # Valida a idade
    if not age_str.isdigit():
        return jsonify({
            "message": "Informe a idade do atleta em números inteiros."
        }), 400

    age = int(age_str)

    if age < 1 or age > 100:
        return jsonify({
            "message": "Informe uma idade válida entre 1 e 100 anos."
        }), 400

    # Valida o sexo
    if sex not in ("MASCULINO", "FEMININO"):
        return jsonify({
            "message": "Selecione o sexo masculino ou feminino."
        }), 400

    # Cria o atleta
    try:
        athlete = OlympicAthlete(
            edition_id=edition_id,
            team_id=team_id,
            name=name,
            age=age,
            sex=sex
        )

        db.session.add(athlete)
        db.session.commit()

    except Exception:
        db.session.rollback()

        return jsonify({
            "message": "Erro ao cadastrar atleta."
        }), 500

    return jsonify({
        "message": "Atleta cadastrado com sucesso!",
        "athlete": {
            "id": athlete.id,
            "edition_id": athlete.edition_id,
            "team_id": athlete.team_id,
            "name": athlete.name,
            "age": athlete.age,
            "sex": athlete.sex
        }
    }), 201
    

@app.route("/admin/olimpiadas/atletas/<int:athlete_id>/editar", methods=["PUT"])
@admin_required_page
def admin_edit_olympic_athlete(athlete_id):
    try:
        data = request.get_json(silent=True) or {}

        athlete = db.session.get(OlympicAthlete, athlete_id)

        if not athlete:
            return jsonify({
                "success": False,
                "message": "Atleta não encontrado."
            }), 404

        edition = db.session.get(
            OlympicEdition,
            athlete.edition_id
        )

        if not edition or not edition.is_active:
            return jsonify({
                "success": False,
                "message": "A edição não está ativa."
            }), 400

        name = str(data.get("name") or "").strip()
        team_id = data.get("team_id")
        age_str = str(data.get("age") or "").strip()
        sex = str(data.get("sex") or "").strip().upper()

        if not name or len(name) > 150:
            return jsonify({
                "success": False,
                "message": "Informe um nome válido de até 150 caracteres."
            }), 400

        try:
            team_id = int(team_id)
        except (TypeError, ValueError):
            return jsonify({
                "success": False,
                "message": "Selecione uma equipe válida."
            }), 400

        team = db.session.get(OlympicTeam, team_id)

        if not team or team.edition_id != athlete.edition_id:
            return jsonify({
                "success": False,
                "message": "A equipe não pertence à edição do atleta."
            }), 400

        # Validação da idade
        if not age_str.isdigit():
            return jsonify({
                "success": False,
                "message": "Informe a idade em números inteiros."
            }), 400

        age = int(age_str)

        if age < 1 or age > 100:
            return jsonify({
                "success": False,
                "message": "Informe uma idade válida entre 1 e 100 anos."
            }), 400

        # Validação do sexo
        if sex not in ("MASCULINO", "FEMININO"):
            return jsonify({
                "success": False,
                "message": "Selecione o sexo masculino ou feminino."
            }), 400

        athlete.name = name
        athlete.team_id = team_id
        athlete.age = age
        athlete.sex = sex

        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Atleta atualizado com sucesso!",
            "athlete": {
                "id": athlete.id,
                "edition_id": athlete.edition_id,
                "team_id": athlete.team_id,
                "name": athlete.name,
                "age": athlete.age,
                "sex": athlete.sex
            }
        }), 200

    except Exception:
        db.session.rollback()
        app.logger.exception("Erro ao editar atleta olímpico")

        return jsonify({
            "success": False,
            "message": "Erro interno ao atualizar o atleta."
        }), 500
    


@app.route("/admin/olimpiadas/atletas/<int:athlete_id>/excluir", methods=["DELETE"])
@admin_required_page
def admin_delete_olympic_athlete(athlete_id):
    try:
        # Localiza o atleta
        athlete = db.session.get(OlympicAthlete, athlete_id)

        if not athlete:
            return jsonify({
                "success": False,
                "message": "Atleta não encontrado."
            }), 404

        # Verifica a edição à qual o atleta pertence
        edition = db.session.get(
            OlympicEdition,
            athlete.edition_id
        )

        if not edition or not edition.is_active:
            return jsonify({
                "success": False,
                "message": "Não é possível excluir atletas de uma edição inativa."
            }), 400

        # Guarda o nome para a mensagem de confirmação
        athlete_name = athlete.name

        # Exclui o atleta
        db.session.delete(athlete)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": f"Atleta {athlete_name} excluído com sucesso!"
        }), 200

    except Exception:
        db.session.rollback()

        app.logger.exception(
            "Erro ao excluir atleta olímpico"
        )

        return jsonify({
            "success": False,
            "message": "Não foi possível excluir o atleta. Verifique se existem registros vinculados."
        }), 500



@app.route("/admin/olimpiadas/modalidades/criar", methods=["POST"])
@admin_required_page
def admin_create_olympic_modality():
    try:
        data = request.get_json(silent=True) or {}
        
        
        # Valida a duração do confronto em minutos
        try:
            match_duration_minutes = int(
                data.get("match_duration_minutes")
            )

            if match_duration_minutes <= 0:
                raise ValueError()

        except (TypeError, ValueError):
            return jsonify({
                "success": False,
                "message": "Informe uma duração válida, maior que zero."
            }), 400
            
        
        # Valida o limite de confrontos da modalidade por dia
        max_matches_per_modality_per_day = data.get(
            "max_matches_per_modality_per_day"
        )

        if max_matches_per_modality_per_day in (None, ""):
            max_matches_per_modality_per_day = None
        else:
            try:
                max_matches_per_modality_per_day = int(
                    max_matches_per_modality_per_day
                )

                if max_matches_per_modality_per_day <= 0:
                    raise ValueError()

            except (TypeError, ValueError):
                return jsonify({
                    "success": False,
                    "message": "O limite diário da modalidade deve ser maior que zero."
                }), 400
    
            
        
        # Valida o limite diário de confrontos por equipe
        try:
            max_matches_per_team_per_day = int(
                data.get("max_matches_per_team_per_day")
            )

            if max_matches_per_team_per_day <= 0:
                raise ValueError()

        except (TypeError, ValueError):
            return jsonify({
                "success": False,
                "message": "Informe um limite diário válido, maior que zero."
            }), 400
    


        edition_id = data.get("edition_id")
        name = str(data.get("name") or "").strip()
        description = str(
            data.get("description") or ""
        ).strip()

        # Valida a edição
        try:
            edition_id = int(edition_id)
        except (TypeError, ValueError):
            return jsonify({
                "success": False,
                "message": "Selecione uma edição válida."
            }), 400

        edition = db.session.get(
            OlympicEdition,
            edition_id
        )

        if not edition:
            return jsonify({
                "success": False,
                "message": "Edição não encontrada."
            }), 404

        if not edition.is_active:
            return jsonify({
                "success": False,
                "message": "Não é possível cadastrar modalidades em uma edição inativa."
            }), 400

        # Valida o nome da modalidade
        if not name or len(name) > 100:
            return jsonify({
                "success": False,
                "message": "Informe um nome de modalidade válido, com até 100 caracteres."
            }), 400

        # Impede modalidades duplicadas na mesma edição
        existing_modality = OlympicModality.query.filter(
            OlympicModality.edition_id == edition_id,
            db.func.lower(OlympicModality.name) == name.lower()
        ).first()

        if existing_modality:
            return jsonify({
                "success": False,
                "message": "Essa modalidade já está cadastrada nesta edição."
            }), 400

        # Cria a modalidade
        modality = OlympicModality(
            edition_id=edition_id,
            name=name,
            description=description,            
            match_duration_minutes=match_duration_minutes,
            max_matches_per_team_per_day=max_matches_per_team_per_day,
            max_matches_per_modality_per_day=max_matches_per_modality_per_day,
            is_active=True

        )

        db.session.add(modality)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Modalidade cadastrada com sucesso!",
            "modality": {
                "id": modality.id,
                "edition_id": modality.edition_id,
                "name": modality.name,
                "description": modality.description,
                "is_active": modality.is_active
            }
        }), 201

    except Exception:
        db.session.rollback()

        app.logger.exception(
            "Erro ao cadastrar modalidade olímpica"
        )

        return jsonify({
            "success": False,
            "message": "Erro interno ao cadastrar modalidade."
        }), 500


@app.route("/admin/olimpiadas/edicoes/<int:edition_id>/modalidades", methods=["GET"])
@admin_required_page
def admin_list_olympic_modalities(edition_id):
    try:
        # Verifica se a edição existe
        edition = db.session.get(
            OlympicEdition,
            edition_id
        )

        if not edition:
            return jsonify({
                "success": False,
                "message": "Edição das Olimpíadas não encontrada."
            }), 404

        # Busca as modalidades pertencentes à edição
        modalities = OlympicModality.query.filter_by(
            edition_id=edition_id
        ).order_by(
            OlympicModality.name.asc(),
            OlympicModality.id.asc()
        ).all()

        # Organiza os dados para retornar ao JavaScript
        modalities_list = []

        
        for modality in modalities:
            modalities_list.append({
                "id": modality.id,
                "edition_id": modality.edition_id,
                "name": modality.name,                
                "description": modality.description or "",                
                "match_duration_minutes": modality.match_duration_minutes,
                "max_matches_per_team_per_day": modality.max_matches_per_team_per_day,
                "max_matches_per_modality_per_day": modality.max_matches_per_modality_per_day,
                "is_active": modality.is_active


            })


        return jsonify({
            "success": True,
            "edition": {
                "id": edition.id,
                "name": edition.name,
                "year": edition.year
            },
            "modalities": modalities_list
        }), 200

    except Exception:
        app.logger.exception(
            "Erro ao listar modalidades olímpicas"
        )

        return jsonify({
            "success": False,
            "message": "Erro interno ao carregar modalidades."
        }), 500


@app.route("/admin/olimpiadas/modalidades/<int:modality_id>/editar", methods=["PUT"])
@admin_required_page
def admin_edit_olympic_modality(modality_id):
    
    try:
        data = request.get_json(silent=True) or {}

        name = str(data.get("name") or "").strip()
        description = str(
            data.get("description") or ""
        ).strip()

        # Valida a duração do confronto
        try:
            match_duration_minutes = int(
                data.get("match_duration_minutes")
            )

            if match_duration_minutes <= 0:
                raise ValueError()

        except (TypeError, ValueError):
            return jsonify({
                "success": False,
                "message": "Informe uma duração válida, maior que zero."
            }), 400
            
        
        # Valida o limite de confrontos da modalidade por dia
        max_matches_per_modality_per_day = data.get(
            "max_matches_per_modality_per_day"
        )

        if max_matches_per_modality_per_day in (None, ""):
            max_matches_per_modality_per_day = None
        else:
            try:
                max_matches_per_modality_per_day = int(
                    max_matches_per_modality_per_day
                )

                if max_matches_per_modality_per_day <= 0:
                    raise ValueError()

            except (TypeError, ValueError):
                return jsonify({
                    "success": False,
                    "message": "O limite diário da modalidade deve ser maior que zero."
                }), 400

        # Valida o limite diário de confrontos por equipe
        try:
            max_matches_per_team_per_day = int(
                data.get("max_matches_per_team_per_day")
            )

            if max_matches_per_team_per_day <= 0:
                raise ValueError()

        except (TypeError, ValueError):
            return jsonify({
                "success": False,
                "message": "Informe um limite diário válido, maior que zero."
            }), 400
    

        # Localiza a modalidade

        modality = db.session.get(
            OlympicModality,
            modality_id
        )

        if not modality:
            return jsonify({
                "success": False,
                "message": "Modalidade não encontrada."
            }), 404

        # Verifica a edição à qual pertence
        edition = db.session.get(
            OlympicEdition,
            modality.edition_id
        )

        if not edition or not edition.is_active:
            return jsonify({
                "success": False,
                "message": "Não é possível editar modalidades de uma edição inativa."
            }), 400

        # Valida o nome
        if not name or len(name) > 100:
            return jsonify({
                "success": False,
                "message": "Informe um nome válido, com até 100 caracteres."
            }), 400

        # Verifica se já existe outra modalidade com o mesmo nome
        existing_modality = OlympicModality.query.filter(
            OlympicModality.edition_id == modality.edition_id,
            OlympicModality.id != modality.id,
            db.func.lower(OlympicModality.name) == name.lower()
        ).first()

        if existing_modality:
            return jsonify({
                "success": False,
                "message": "Já existe outra modalidade com esse nome nesta edição."
            }), 400

        
        # Atualiza os dados        
        
        modality.name = name
        modality.description = description
        modality.match_duration_minutes = match_duration_minutes
        modality.max_matches_per_team_per_day = max_matches_per_team_per_day
        modality.max_matches_per_modality_per_day = max_matches_per_modality_per_day

        db.session.commit()




        return jsonify({
            "success": True,
            "message": "Modalidade atualizada com sucesso!",
            "modality": {
                "id": modality.id,
                "edition_id": modality.edition_id,
                "name": modality.name,
                "description": modality.description or "",
                "is_active": modality.is_active
            }
        }), 200

    except Exception:
        db.session.rollback()

        app.logger.exception(
            "Erro ao editar modalidade olímpica"
        )

        return jsonify({
            "success": False,
            "message": "Erro interno ao editar modalidade."
        }), 500
        

@app.route(
    "/admin/olimpiadas/modalidades/<int:modality_id>/situacao",
    methods=["PUT"]
)
@admin_required_page
def admin_toggle_olympic_modality(modality_id):
    try:
        # Localiza a modalidade
        modality = db.session.get(
            OlympicModality,
            modality_id
        )

        if not modality:
            return jsonify({
                "success": False,
                "message": "Modalidade não encontrada."
            }), 404

        # Localiza a edição da modalidade
        edition = db.session.get(
            OlympicEdition,
            modality.edition_id
        )

        if not edition or not edition.is_active:
            return jsonify({
                "success": False,
                "message": "Não é possível alterar modalidades de uma edição inativa."
            }), 400

        # Recebe a situação desejada
        data = request.get_json(silent=True) or {}

        is_active = data.get("is_active")

        # Aceita somente valores booleanos
        if not isinstance(is_active, bool):
            return jsonify({
                "success": False,
                "message": "Informe uma situação válida: true ou false."
            }), 400

        # Atualiza a situação da modalidade
        modality.is_active = is_active

        db.session.commit()

        return jsonify({
            "success": True,
            "message": (
                "Modalidade ativada com sucesso!"
                if modality.is_active
                else "Modalidade desativada com sucesso!"
            ),
            "modality": {
                "id": modality.id,
                "edition_id": modality.edition_id,
                "name": modality.name,
                "description": modality.description or "",
                "is_active": modality.is_active
            }
        }), 200

    except Exception:
        db.session.rollback()

        app.logger.exception(
            "Erro ao alterar situação da modalidade olímpica"
        )

        return jsonify({
            "success": False,
            "message": "Erro interno ao alterar a situação da modalidade."
        }), 500
        


@app.route(
    "/admin/olimpiadas/inscricoes/criar",
    methods=["POST"]
)
@admin_required_page
def admin_create_olympic_modality_registration():
    try:
        data = request.get_json(silent=True) or {}

        # Valida os identificadores recebidos
        try:
            edition_id = int(data.get("edition_id"))
            modality_id = int(data.get("modality_id"))
            athlete_id = int(data.get("athlete_id"))

            if min(edition_id, modality_id, athlete_id) <= 0:
                raise ValueError()

        except (TypeError, ValueError):
            return jsonify({
                "success": False,
                "message": "Informe edição, modalidade e atleta válidos."
            }), 400

        # Localiza a edição
        edition = db.session.get(
            OlympicEdition,
            edition_id
        )

        if not edition:
            return jsonify({
                "success": False,
                "message": "Edição não encontrada."
            }), 404

        if not edition.is_active:
            return jsonify({
                "success": False,
                "message": "Não é possível inscrever atletas em uma edição inativa."
            }), 400

        # Localiza a modalidade
        modality = db.session.get(
            OlympicModality,
            modality_id
        )

        if not modality:
            return jsonify({
                "success": False,
                "message": "Modalidade não encontrada."
            }), 404

        if modality.edition_id != edition_id:
            return jsonify({
                "success": False,
                "message": "A modalidade não pertence à edição selecionada."
            }), 400

        if not modality.is_active:
            return jsonify({
                "success": False,
                "message": "Não é possível inscrever atletas em uma modalidade inativa."
            }), 400

        # Localiza o atleta
        athlete = db.session.get(
            OlympicAthlete,
            athlete_id
        )

        if not athlete:
            return jsonify({
                "success": False,
                "message": "Atleta não encontrado."
            }), 404

        
        if athlete.edition_id != edition_id:
            return jsonify({
                "success": False,
                "message": "O atleta não pertence à edição selecionada."
            }), 400

        
        # Impede inscrições duplicadas

        existing_registration = (
            OlympicModalityRegistration.query.filter_by(
                modality_id=modality_id,
                athlete_id=athlete_id
            ).first()
        )

        if existing_registration:
            return jsonify({
                "success": False,
                "message": "Este atleta já está inscrito nesta modalidade."
            }), 400

        # Cria a inscrição
        registration = OlympicModalityRegistration(
            edition_id=edition_id,
            modality_id=modality_id,
            athlete_id=athlete_id
        )

        db.session.add(registration)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Atleta inscrito na modalidade com sucesso!",
            "registration": {
                "id": registration.id,
                "edition_id": registration.edition_id,
                "modality_id": registration.modality_id,
                "athlete_id": registration.athlete_id
            }
        }), 201

    except Exception:
        db.session.rollback()

        app.logger.exception(
            "Erro ao inscrever atleta em modalidade olímpica"
        )

        return jsonify({
            "success": False,
            "message": "Erro interno ao realizar a inscrição."
        }), 500


# ==========================================
# OLIMPÍADAS - CADASTRAR CONFRONTO
# ==========================================

@app.route(
    "/admin/olimpiadas/confrontos/criar",
    methods=["POST"]
)
@admin_required_page
def admin_create_olympic_match():
    try:
        data = request.get_json(silent=True) or {}

        try:
            edition_id = int(data.get("edition_id"))
            modality_id = int(data.get("modality_id"))
            team_a_id = int(data.get("team_a_id"))
            team_b_id = int(data.get("team_b_id"))

            if min(
                edition_id,
                modality_id,
                team_a_id,
                team_b_id
            ) <= 0:
                raise ValueError()

        except (TypeError, ValueError):
            return jsonify({
                "success": False,
                "message": "Informe edição, modalidade e equipes válidas."
            }), 400

        if team_a_id == team_b_id:
            return jsonify({
                "success": False,
                "message": "Uma equipe não pode enfrentar ela mesma."
            }), 400

        edition = db.session.get(OlympicEdition, edition_id)

        if not edition:
            return jsonify({
                "success": False,
                "message": "Edição não encontrada."
            }), 404

        if not edition.is_active:
            return jsonify({
                "success": False,
                "message": "Não é possível cadastrar confrontos em uma edição inativa."
            }), 400

        modality = db.session.get(OlympicModality, modality_id)

        if not modality:
            return jsonify({
                "success": False,
                "message": "Modalidade não encontrada."
            }), 404

        if modality.edition_id != edition_id or not modality.is_active:
            return jsonify({
                "success": False,
                "message": "Modalidade inválida ou inativa para esta edição."
            }), 400

        team_a = db.session.get(OlympicTeam, team_a_id)
        team_b = db.session.get(OlympicTeam, team_b_id)

        if not team_a or not team_b:
            return jsonify({
                "success": False,
                "message": "Uma ou ambas as equipes não foram encontradas."
            }), 404

        if (
            team_a.edition_id != edition_id
            or team_b.edition_id != edition_id
        ):
            return jsonify({
                "success": False,
                "message": "As equipes devem pertencer à edição selecionada."
            }), 400

        phase = str(
            data.get("phase") or "CLASSIFICATORIA"
        ).strip().upper()

        if phase not in {
            "CLASSIFICATORIA",
            "FINAL_ENTRE_TURNOS"
        }:
            return jsonify({
                "success": False,
                "message": "Fase do confronto inválida."
            }), 400

        if phase != "FINAL_ENTRE_TURNOS" and team_a.shift != team_b.shift:
            return jsonify({
                "success": False,
                "message": "Nesta fase, as equipes devem pertencer ao mesmo turno."
            }), 400

        shift = (
            team_a.shift
            if team_a.shift == team_b.shift
            else "INTERTURNOS"
        )
        
        
        # ==========================================
        # VALIDAR CAMPEÃS DA FINAL INTERTURNOS
        # ==========================================

        if phase == "FINAL_ENTRE_TURNOS":

            turnos = {
                (team_a.shift or "").strip().upper(),
                (team_b.shift or "").strip().upper()
            }

            if turnos != {"MATUTINO", "VESPERTINO"}:
                return jsonify({
                    "success": False,
                    "message": (
                        "A final interturnos deve reunir "
                        "uma equipe do matutino e uma do vespertino."
                    )
                }), 400

            campeas = {}

            for turno in ("MATUTINO", "VESPERTINO"):

                partidas = OlympicMatch.query.filter(
                    OlympicMatch.edition_id == edition_id,
                    OlympicMatch.modality_id == modality_id,
                    OlympicMatch.phase == "CLASSIFICATORIA",
                    db.func.upper(OlympicMatch.shift) == turno
                ).all()
                
            
            # Verifica se todos os confrontos previstos
            # entre as cinco equipes foram cadastrados.

            equipes_turno = OlympicTeam.query.filter(
                OlympicTeam.edition_id == edition_id,
                db.func.upper(OlympicTeam.shift) == turno
            ).all()

            quantidade_equipes = len(equipes_turno)

            confrontos_esperados = (
                quantidade_equipes * (quantidade_equipes - 1) // 2
            )

            pares_cadastrados = {
                tuple(sorted((p.team_a_id, p.team_b_id)))
                for p in partidas
            }

            if (
                quantidade_equipes != 5
                or len(partidas) != confrontos_esperados
                or len(pares_cadastrados) != confrontos_esperados
            ):
                return jsonify({
                    "success": False,
                    "message": (
                        f"O calendário do {turno.lower()} "
                        "está incompleto ou contém confrontos duplicados. "
                        f"Esperados: {confrontos_esperados}; "
                        f"cadastrados: {len(partidas)}."
                    )
                }), 400
    

                if not partidas or any(
                    partida.status != "FINALIZADO"
                    or partida.score_a is None
                    or partida.score_b is None
                    for partida in partidas
                ):
                    return jsonify({
                        "success": False,
                        "message": (
                            f"A classificação do {turno.lower()} "
                            "ainda não está encerrada."
                        )
                    }), 400

                classificacao = calculate_olympic_classification(
                    edition_id,
                    modality_id,
                    turno
                )

                if not classificacao:
                    return jsonify({
                        "success": False,
                        "message": (
                            f"Não foi possível identificar "
                            f"a campeã do {turno.lower()}."
                        )
                    }), 400

                primeira = classificacao[0]

                def criterios(equipe):
                    return (
                        equipe["points"],
                        equipe["goal_difference"],
                        -equipe["red_cards"],
                        -equipe["yellow_cards"],
                        -equipe["fouls"]
                    )

                empatadas = [
                    equipe for equipe in classificacao
                    if criterios(equipe) == criterios(primeira)
                ]

                if len(empatadas) > 1:
                    return jsonify({
                        "success": False,
                        "message": (
                            f"Existe empate não resolvido "
                            f"na classificação do {turno.lower()}."
                        )
                    }), 400

                campeas[turno] = primeira["team_id"]

            equipes_permitidas = set(campeas.values())
            equipes_informadas = {team_a_id, team_b_id}

            if equipes_informadas != equipes_permitidas:
                return jsonify({
                    "success": False,
                    "message": (
                        "As equipes selecionadas não são as "
                        "campeãs confirmadas dos respectivos turnos."
                    )
                }), 400

            final_existente = OlympicMatch.query.filter(
                OlympicMatch.edition_id == edition_id,
                OlympicMatch.modality_id == modality_id,
                OlympicMatch.phase == "FINAL_ENTRE_TURNOS"
            ).first()

            if final_existente:
                return jsonify({
                    "success": False,
                    "message": (
                        "Esta modalidade já possui uma "
                        "final interturnos cadastrada."
                    )
                }), 400

        
        # Impede confrontos entre turnos diferentes fora da final interturnos
        if team_a.shift != team_b.shift and phase != "FINAL_ENTRE_TURNOS":
            return jsonify({
                "success": False,
                "message": (
                    "Na fase classificatória e na final do turno, "
                    "as duas equipes devem pertencer ao mesmo turno."
                )
            }), 400
        
                

        try:
            match_date = date.fromisoformat(
                str(data.get("match_date") or "")
            )

            match_time = datetime.strptime(
                str(data.get("match_time") or ""),
                "%H:%M"
            ).time()

        except (TypeError, ValueError):
            return jsonify({
                "success": False,
                "message": "Informe uma data e um horário válidos."
            }), 400

        if (
            (edition.start_date and match_date < edition.start_date)
            or (edition.end_date and match_date > edition.end_date)
        ):
            return jsonify({
                "success": False,
                "message": "A data está fora do período da edição."
            }), 400
            
        # Verifica se o calendário da edição está configurado
        settings = OlympicCalendarSettings.query.filter_by(
            edition_id=edition_id
        ).first()

        if settings is None:
            return jsonify({
                "success": False,
                "message": (
                    "Configure o calendário da edição "
                    "antes de cadastrar confrontos."
                )
            }), 400 

        # Verifica se a data corresponde a um dia permitido
        allowed_weekdays = settings.game_weekdays or []

        if (
            phase != "FINAL_ENTRE_TURNOS"
            and match_date.weekday() not in allowed_weekdays
        ):
            return jsonify({
                "success": False,
                "message": (
                    "A data selecionada não corresponde "
                    "a um dia permitido para os jogos."
                )
            }), 400  

        
        # ==========================================
        # DATA E HORÁRIO DA FINAL INTERTURNOS
        # ==========================================

        if phase == "FINAL_ENTRE_TURNOS":

            if match_date != date(2026, 11, 28):
                return jsonify({
                    "success": False,
                    "message": "A final interturnos deve ocorrer em 28/11/2026."
                }), 400

            duration = get_olympic_match_duration({
                "modality_id": modality_id,
                "duration_minutes": modality.match_duration_minutes
            })

            final_start = datetime.combine(match_date, match_time)
            final_end = final_start + timedelta(minutes=duration)

            allowed_start = datetime.combine(
                match_date,
                datetime.strptime("08:30", "%H:%M").time()
            )

            allowed_end = datetime.combine(
                match_date,
                datetime.strptime("11:30", "%H:%M").time()
            )

            if final_start < allowed_start or final_end > allowed_end:
                return jsonify({
                    "success": False,
                    "message": (
                        "A final deve começar e terminar "
                        "entre 08h30 e 11h30."
                    )
                }), 400


        # Verifica se o confronto cabe no horário do turno
        if shift != "INTERTURNOS":

            try:
                shift_start, shift_end = get_olympic_shift_window(
                    settings,
                    shift
                )

                duration = get_olympic_match_duration({
                    "modality_id": modality_id,
                    "duration_minutes": modality.match_duration_minutes
                })

            except ValueError as error:
                return jsonify({
                    "success": False,
                    "message": str(error)
                }), 400

            match_start = datetime.combine(match_date, match_time)

            match_end = match_start + timedelta(
                minutes=duration
            )

            if (
                match_time < shift_start
                or match_end.time() > shift_end
                or match_end.date() != match_date
            ):
                return jsonify({
                    "success": False,
                    "message": (
                        "O confronto precisa começar e terminar "
                        "dentro do horário permitido para o turno."
                    )
                }), 400   

        # Recupera os confrontos já agendados
        scheduled_matches = get_existing_olympic_scheduled_matches(
            edition_id
        )

        # Verifica conflitos de horário e intervalo entre jogos
        proposed_start = datetime.combine(
            match_date,
            match_time
        )

        proposed_duration = get_olympic_match_duration({
            "modality_id": modality_id,
            "duration_minutes": modality.match_duration_minutes
        })

        if not olympic_time_slot_is_available(
            proposed_start,
            proposed_duration,
            scheduled_matches,
            settings.interval_minutes,
            settings.allow_simultaneous_matches
        ):
            return jsonify({
                "success": False,
                "message": (
                    "Já existe um confronto nesse horário "
                    "ou o intervalo mínimo entre jogos "
                    "não está sendo respeitado."
                )
            }), 400 

        # Verifica o descanso mínimo das duas equipes
        for team_id in (team_a_id, team_b_id):

            if not olympic_team_has_enough_rest(
                team_id,
                proposed_start,
                proposed_duration,
                scheduled_matches,
                settings.rest_minutes
            ):
                return jsonify({
                    "success": False,
                    "message": (
                        "Uma das equipes não terá o descanso "
                        "mínimo obrigatório entre os confrontos."
                    )
                }), 400   

        # Verifica o limite diário de jogos por equipe na modalidade
        for team_id in (team_a_id, team_b_id):

            if not olympic_team_within_daily_limit(
                team_id,
                modality_id,
                match_date,
                scheduled_matches,
                modality.max_matches_per_team_per_day
            ):
                return jsonify({
                    "success": False,
                    "message": (
                        "Uma das equipes já atingiu o limite "
                        "de confrontos desta modalidade no dia."
                    )
                }), 400

        # Verifica o limite total de confrontos da modalidade no dia
        if not olympic_modality_within_daily_limit(
            modality_id,
            match_date,
            scheduled_matches,
            modality.max_matches_per_modality_per_day
        ):
            return jsonify({
                "success": False,
                "message": (
                    "A modalidade já atingiu o limite "
                    "total de confrontos permitido nesta data."
                )
            }), 400

        existing_time = OlympicMatch.query.filter_by(
            edition_id=edition_id,
            match_date=match_date,
            match_time=match_time
        ).filter(
            OlympicMatch.status != "CANCELADO"
        ).first()

        if existing_time:
            return jsonify({
                "success": False,
                "message": "Já existe um confronto agendado neste mesmo horário."
            }), 400

        match = OlympicMatch(
            edition_id=edition_id,
            modality_id=modality_id,
            team_a_id=team_a_id,
            team_b_id=team_b_id,
            match_date=match_date,
            match_time=match_time,
            shift=shift,
            phase=phase,
            status="AGENDADO"
        )

        db.session.add(match)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Confronto cadastrado com sucesso!",
            "match": {
                "id": match.id,
                "edition_id": match.edition_id,
                "modality_id": match.modality_id,
                "team_a_id": match.team_a_id,
                "team_b_id": match.team_b_id,
                "match_date": match.match_date.isoformat(),
                "match_time": match.match_time.strftime("%H:%M"),
                "shift": match.shift,
                "phase": match.phase,
                "status": match.status
            }
        }), 201

    except Exception:
        db.session.rollback()

        app.logger.exception(
            "Erro ao cadastrar confronto olímpico"
        )

        return jsonify({
            "success": False,
            "message": "Erro interno ao cadastrar confronto."
        }), 500



# ==========================================
# OLIMPÍADAS - SALVAR CONFIGURAÇÕES DO CALENDÁRIO
# ==========================================

@app.route(
    "/admin/olimpiadas/calendario/configuracoes/salvar",
    methods=["POST"]
)
@admin_required_page
def admin_save_olympic_calendar_settings():

    data = request.get_json(silent=True) or {}
        
    # Valida os dias da semana permitidos para jogos
    game_weekdays = data.get("game_weekdays", [0, 2])

    if (
        not isinstance(game_weekdays, list)
        or not game_weekdays
        or any(
            type(day) is not int or day < 0 or day > 6
            for day in game_weekdays
        )
        or len(game_weekdays) != len(set(game_weekdays))
    ):
        return jsonify({
            "success": False,
            "message": "Selecione dias da semana válidos, sem repetições."
        }), 400


    try:
        edition_id = int(data.get("edition_id"))
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "message": "Selecione uma edição válida."
        }), 400

    edition = db.session.get(OlympicEdition, edition_id)

    if not edition:
        return jsonify({
            "success": False,
            "message": "Edição não encontrada."
        }), 404

    try:
        interval_minutes = int(data.get("interval_minutes"))
        rest_minutes = int(data.get("rest_minutes"))

        if interval_minutes < 0 or rest_minutes < 0:
            raise ValueError()

        if (
            isinstance(data.get("allow_simultaneous_matches"), bool)
            is False
        ):
            raise ValueError()

        time_fields = {}

        for field in (
            "morning_start",
            "morning_end",
            "afternoon_start",
            "afternoon_end"
        ):
            value = data.get(field)

            if not isinstance(value, str):
                raise ValueError()

            time_fields[field] = datetime.strptime(
                value, "%H:%M"
            ).time()

        if (
            time_fields["morning_start"] >=
            time_fields["morning_end"]
        ):
            raise ValueError()

        if (
            time_fields["afternoon_start"] >=
            time_fields["afternoon_end"]
        ):
            raise ValueError()

    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "message": (
                "Configurações inválidas. Confira os horários, "
                "os intervalos e a opção de jogos simultâneos."
            )
        }), 400

    settings = OlympicCalendarSettings.query.filter_by(
        edition_id=edition.id
    ).first()

    if not settings:
        settings = OlympicCalendarSettings(
            edition_id=edition.id
        )
        db.session.add(settings)

    settings.interval_minutes = interval_minutes
    settings.rest_minutes = rest_minutes
    settings.game_weekdays = game_weekdays
    settings.allow_simultaneous_matches = data[
        "allow_simultaneous_matches"
    ]

    settings.morning_start = time_fields["morning_start"]
    settings.morning_end = time_fields["morning_end"]
    settings.afternoon_start = time_fields["afternoon_start"]
    settings.afternoon_end = time_fields["afternoon_end"]

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception(
            "Erro ao salvar configurações do calendário olímpico."
        )
        return jsonify({
            "success": False,
            "message": "Não foi possível salvar as configurações."
        }), 500

    return jsonify({
        "success": True,
        "message": "Configurações do calendário salvas com sucesso."
    })


# ==========================================
# OLIMPÍADAS - CONSULTAR CONFIGURAÇÕES DO CALENDÁRIO
# ==========================================

@app.route(
    "/admin/olimpiadas/edicoes/<int:edition_id>/calendario/configuracoes",
    methods=["GET"]
)
@admin_required_page
def admin_get_olympic_calendar_settings(edition_id):

    edition = db.session.get(OlympicEdition, edition_id)

    if not edition:
        return jsonify({
            "success": False,
            "message": "Edição não encontrada."
        }), 404

    settings = OlympicCalendarSettings.query.filter_by(
        edition_id=edition_id
    ).first()

    if not settings:
        return jsonify({
            "success": True,
            "configured": False,
            "settings": None
        })

    return jsonify({
        "success": True,
        "configured": True,
        "settings": {
            "edition_id": settings.edition_id,
            "interval_minutes": settings.interval_minutes,
            "rest_minutes": settings.rest_minutes,
            "game_weekdays": settings.game_weekdays,
            "allow_simultaneous_matches": settings.allow_simultaneous_matches,
            "morning_start":
                settings.morning_start.strftime("%H:%M")
                if settings.morning_start else None,
            "morning_end":
                settings.morning_end.strftime("%H:%M")
                if settings.morning_end else None,
            "afternoon_start":
                settings.afternoon_start.strftime("%H:%M")
                if settings.afternoon_start else None,
            "afternoon_end":
                settings.afternoon_end.strftime("%H:%M")
                if settings.afternoon_end else None
        }
    })


# ==========================================
# OLIMPÍADAS - LISTAR CONFRONTOS
# ==========================================

# ==========================================
# OLIMPÍADAS - EDITAR DATA E HORÁRIO
# ==========================================

@app.route(
    "/admin/olimpiadas/confrontos/<int:match_id>/editar",
    methods=["PUT"]
)
@admin_required_page
def admin_update_olympic_match(match_id):

    data = request.get_json(silent=True) or {}

    match = db.session.get(OlympicMatch, match_id)

    if match is None:
        return jsonify({
            "success": False,
            "message": "Confronto não encontrado."
        }), 404
        
    # Busca as configurações do calendário da edição
    settings = OlympicCalendarSettings.query.filter_by(
        edition_id=match.edition_id
    ).first()

    if settings is None:
        return jsonify({
            "success": False,
            "message": (
                "Configure o calendário da edição "
                "antes de editar confrontos."
            )
        }), 400    

    if match.status != "AGENDADO":
        return jsonify({
            "success": False,
            "message": "Somente confrontos agendados podem ser alterados."
        }), 400

    try:
        new_date = date.fromisoformat(data.get("match_date", ""))
        new_time = datetime.strptime(
            data.get("match_time", ""),
            "%H:%M"
        ).time()

    except (ValueError, TypeError):
        return jsonify({
            "success": False,
            "message": "Informe uma data e um horário válidos."
        }), 400
        
    # Verifica se o confronto cabe no horário do turno
    try:
        shift_start, shift_end = get_olympic_shift_window(
            settings,
            match.shift
        )

        duration = get_olympic_match_duration({
            "modality_id": match.modality_id,
            "duration_minutes": match.modality.match_duration_minutes
        })

        proposed_start = datetime.combine(new_date, new_time)
        proposed_end = proposed_start + timedelta(minutes=duration)

        allowed_start = datetime.combine(new_date, shift_start)
        allowed_end = datetime.combine(new_date, shift_end)

        if proposed_start < allowed_start or proposed_end > allowed_end:
            return jsonify({
                "success": False,
                "message": (
                    "O confronto precisa começar e terminar "
                    "dentro do horário permitido para o turno."
                )
            }), 400

    except (ValueError, TypeError) as error:
        return jsonify({
            "success": False,
            "message": str(error)
        }), 400 

    # Carrega os outros confrontos para verificar conflitos
    try:
        existing_matches = get_existing_olympic_scheduled_matches(
            match.edition_id
        )

        # Retira o próprio confronto da comparação
        other_matches = [
            existing
            for existing in existing_matches
            if existing["match_id"] != match.id
        ]

        # Verifica se o novo horário está disponível
        time_available = olympic_time_slot_is_available(
            proposed_start,
            duration,
            other_matches,
            settings.interval_minutes,
            settings.allow_simultaneous_matches
        )

        if not time_available:
            return jsonify({
                "success": False,
                "message": (
                    "O horário escolhido entra em conflito "
                    "com outro confronto cadastrado ou "
                    "não respeita o intervalo entre jogos."
                )
            }), 400

    except (ValueError, TypeError) as error:
        return jsonify({
            "success": False,
            "message": str(error)
        }), 400 

    # Verifica o descanso mínimo das duas equipes
    try:
        for team_id in (match.team_a_id, match.team_b_id):

            enough_rest = olympic_team_has_enough_rest(
                team_id,
                proposed_start,
                duration,
                other_matches,
                settings.rest_minutes
            )

            if not enough_rest:
                return jsonify({
                    "success": False,
                    "message": (
                        "O horário escolhido não respeita "
                        "o descanso mínimo de uma das equipes."
                    )
                }), 400

    except (ValueError, TypeError) as error:
        return jsonify({
            "success": False,
            "message": str(error)
        }), 400   

    # Verifica o limite diário por equipe na modalidade
    try:
        for team_id in (match.team_a_id, match.team_b_id):

            within_limit = olympic_team_within_daily_limit(
                team_id,
                match.modality_id,
                new_date,
                other_matches,
                match.modality.max_matches_per_team_per_day
            )

            if not within_limit:
                return jsonify({
                    "success": False,
                    "message": (
                        "Uma das equipes já atingiu o limite "
                        "de confrontos dessa modalidade "
                        "na data escolhida."
                    )
                }), 400

    except (ValueError, TypeError) as error:
        return jsonify({
            "success": False,
            "message": str(error)
        }), 400

    # Verifica o limite total de confrontos da modalidade no dia
    try:
        modality_within_limit = olympic_modality_within_daily_limit(
            match.modality_id,
            new_date,
            other_matches,
            match.modality.max_matches_per_modality_per_day
        )

        if not modality_within_limit:
            return jsonify({
                "success": False,
                "message": (
                    "A modalidade já atingiu o limite total "
                    "de confrontos permitido para essa data."
                )
            }), 400

    except (ValueError, TypeError) as error:
        return jsonify({
            "success": False,
            "message": str(error)
        }), 400    
        
    # Verifica se a data escolhida é um dia permitido
    allowed_weekdays = settings.game_weekdays or []

    if new_date.weekday() not in allowed_weekdays:
        return jsonify({
            "success": False,
            "message": (
                "A data escolhida não corresponde a um "
                "dia da semana permitido para os jogos."
            )
        }), 400    

    try:
        match.match_date = new_date
        match.match_time = new_time

        db.session.commit()

    except Exception:
        db.session.rollback()
        app.logger.exception(
            "Erro ao atualizar confronto olímpico %s",
            match_id
        )

        return jsonify({
            "success": False,
            "message": "Erro ao salvar as alterações."
        }), 500

    return jsonify({
        "success": True,
        "message": "Confronto atualizado com sucesso."
    })
    

# ==========================================
# OLIMPÍADAS - LIMPAR CALENDÁRIO
# PRESERVANDO JOGOS FINALIZADOS
# ==========================================

@app.route(
    "/admin/olimpiadas/edicoes/<int:edition_id>/calendario/limpar",
    methods=["POST"]
)
@admin_required_page
def admin_clear_olympic_calendar(edition_id):

    edition = db.session.get(OlympicEdition, edition_id)

    if edition is None:
        return jsonify({
            "success": False,
            "message": "Edição não encontrada."
        }), 404

    try:
        # Seleciona apenas jogos NÃO finalizados.
        matches = (
            OlympicMatch.query
            .filter(
                OlympicMatch.edition_id == edition_id,
                OlympicMatch.status != "FINALIZADO"
            )
            .all()
        )

        match_ids = [match.id for match in matches]

        if not match_ids:
            return jsonify({
                "success": True,
                "message": (
                    "Nenhum jogo pendente para excluir. "
                    "Todos os jogos finalizados foram preservados."
                ),
                "deleted": 0
            })

        # Remove registros associados somente
        # aos confrontos que serão excluídos.
        OlympicMatchParticipant.query.filter(
            OlympicMatchParticipant.match_id.in_(match_ids)
        ).delete(synchronize_session=False)

        OlympicMatchGoal.query.filter(
            OlympicMatchGoal.match_id.in_(match_ids)
        ).delete(synchronize_session=False)

        OlympicMatchAttempt.query.filter(
            OlympicMatchAttempt.match_id.in_(match_ids)
        ).delete(synchronize_session=False)

        # Exclui os confrontos não finalizados.
        for match in matches:
            db.session.delete(match)

        db.session.commit()

        return jsonify({
            "success": True,
            "message": (
                f"{len(matches)} confronto(s) excluído(s). "
                "Os jogos finalizados foram preservados."
            ),
            "deleted": len(matches)
        })

    except Exception:
        db.session.rollback()

        app.logger.exception(
            "Erro ao limpar calendário olímpico da edição %s",
            edition_id
        )

        return jsonify({
            "success": False,
            "message": "Não foi possível limpar o calendário."
        }), 500
    
    
# ==========================================
# OLIMPÍADAS - EXCLUIR CONFRONTO
# ==========================================

@app.route(
    "/admin/olimpiadas/confrontos/<int:match_id>/excluir",
    methods=["DELETE"]
)
@admin_required_page
def admin_delete_olympic_match(match_id):

    match = db.session.get(OlympicMatch, match_id)

    if match is None:
        return jsonify({
            "success": False,
            "message": "Confronto não encontrado."
        }), 404

    try:
        db.session.delete(match)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Confronto excluído com sucesso."
        })

    except Exception:
        db.session.rollback()

        app.logger.exception(
            "Erro ao excluir confronto olímpico %s",
            match_id
        )

        return jsonify({
            "success": False,
            "message": "Não foi possível excluir o confronto."
        }), 500 

# ==========================================
# OLIMPÍADAS - PÁGINA INDIVIDUAL DA SÚMULA
# ==========================================

@app.route(
    "/admin/olimpiadas/confrontos/<int:match_id>/sumula",
    methods=["GET"]
)

@admin_required_page
def admin_olympic_scoresheet_page(match_id):
    return render_olympic_scoresheet(
        match_id,
        external_access=False
    )


def render_olympic_scoresheet(
    match_id,
    external_access=False
):

    match = db.session.get(OlympicMatch, match_id)

    if match is None:
        abort(404)

    athletes_team_a = (
        OlympicAthlete.query
        .filter_by(
            edition_id=match.edition_id,
            team_id=match.team_a_id
        )
        .order_by(OlympicAthlete.name)
        .all()
    )

    athletes_team_b = (
        OlympicAthlete.query
        .filter_by(
            edition_id=match.edition_id,
            team_id=match.team_b_id
        )
        .order_by(OlympicAthlete.name)
        .all()
    )
    
    selected_athlete_ids = {
        participant.athlete_id
        for participant in OlympicMatchParticipant.query.filter_by(
            match_id=match.id
        ).all()
    }
    
    saved_goals = {
        record.athlete_id: record.goals
        for record in OlympicMatchGoal.query.filter_by(
            match_id=match.id
        ).all()
    }
    
    # Recupera os arremessos e cobranças individuais já salvos.
    saved_attempts = [
        {
            "athlete_id": record.athlete_id,
            "attempt_number": record.attempt_number,
            "successful": record.successful
        }
        for record in OlympicMatchAttempt.query.filter_by(
            match_id=match.id
        ).order_by(
            OlympicMatchAttempt.athlete_id,
            OlympicMatchAttempt.attempt_number
        ).all()
    ]

    return render_template(
        "admin_olympic_scoresheet.html",
        match_id=match.id,
        match=match,
        athletes_team_a=athletes_team_a,
        athletes_team_b=athletes_team_b,
        selected_athlete_ids=selected_athlete_ids,
        saved_goals=saved_goals,
        saved_attempts=saved_attempts,
        external_access=external_access

    )


# ==========================================
# OLIMPÍADAS - ABRIR SÚMULA PELO ACESSO EXTERNO
# ==========================================

@app.route(
    "/olimpiadas/sumulas/confrontos/<int:match_id>",
    methods=["GET"]
)
@olympic_scoresheet_access_required
def olympic_scoresheet_external_match(match_id):

    return render_olympic_scoresheet(
        match_id,
        external_access=True
    )


# ==========================================
# OLIMPÍADAS - SALVAR RASCUNHO DA SÚMULA
# ==========================================


@app.route(
    "/admin/olimpiadas/confrontos/<int:match_id>/sumula/rascunho",
    methods=["POST"]
)
@admin_required_page
def admin_save_olympic_scoresheet_draft(match_id):
    return save_olympic_scoresheet_draft(match_id)


@app.route(
    "/olimpiadas/sumulas/confrontos/<int:match_id>/rascunho",
    methods=["POST"]
)
@olympic_scoresheet_access_required
def olympic_scoresheet_external_draft(match_id):
    return save_olympic_scoresheet_draft(match_id)


def save_olympic_scoresheet_draft(match_id):


    match = db.session.get(OlympicMatch, match_id)

    if match is None:
        return jsonify({
            "success": False,
            "message": "Confronto não encontrado."
        }), 404

    if match.status in ("FINALIZADO", "CANCELADO"):
        return jsonify({
            "success": False,
            "message": "Este confronto não permite alterações."
        }), 409

    modality_name = match.modality.name.strip().lower()

    supported_modality = (
        modality_name in ("futsal", "golzinho")
        or "basquete" in modality_name
        or "pênalti" in modality_name
        or "penalti" in modality_name
        or "queimada" in modality_name
        or "corrida" in modality_name
        or "revezamento" in modality_name
    )

    if not supported_modality:
        return jsonify({
            "success": False,
            "message": "Esta modalidade ainda não possui formulário de placar."
        }), 400
        
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "success": False,
            "message": "Dados da súmula inválidos."
        }), 400
        
    # Tentativas individuais de Basquete e Pênaltis.
    athlete_attempts_data = data.get("athlete_attempts", [])

    if not isinstance(athlete_attempts_data, list):
        return jsonify({
            "success": False,
            "message": "Formato inválido das tentativas individuais."
        }), 400 

    # Valida a estrutura de cada tentativa individual.
    for attempt in athlete_attempts_data:
        if (
            not isinstance(attempt, dict)
            or type(attempt.get("athlete_id")) is not int
            or attempt["athlete_id"] <= 0
            or type(attempt.get("attempt_number")) is not int
            or not 1 <= attempt["attempt_number"] <= 5
            or type(attempt.get("successful")) is not bool
        ):
            return jsonify({
                "success": False,
                "message": "Existe uma tentativa individual inválida."
            }), 400
            
    # Impede tentativas duplicadas para o mesmo atleta.
    attempt_keys = [
        (attempt["athlete_id"], attempt["attempt_number"])
        for attempt in athlete_attempts_data
    ]

    if len(attempt_keys) != len(set(attempt_keys)):
        return jsonify({
            "success": False,
            "message": (
                "Existem tentativas duplicadas para o mesmo atleta."
            )
        }), 400  

    # Define o limite de tentativas conforme a modalidade.
    if "basquete" in modality_name:
        max_attempts = 5
    elif "pênalti" in modality_name or "penalti" in modality_name:
        max_attempts = 3
    else:
        max_attempts = 0

    if any(
        attempt["attempt_number"] > max_attempts
        for attempt in athlete_attempts_data
    ):
        return jsonify({
            "success": False,
            "message": (
                "As tentativas enviadas não são permitidas "
                "para esta modalidade."
            )
        }), 400
        
    # Permite tentativas somente dos atletas selecionados
    # como participantes deste confronto.
    participant_ids = data.get("participant_ids", [])

    if (
        not isinstance(participant_ids, list)
        or any(
            type(athlete_id) is not int or athlete_id <= 0
            for athlete_id in participant_ids
        )
    ):
        return jsonify({
            "success": False,
            "message": "Lista de participantes inválida."
        }), 400

    participant_id_set = set(participant_ids)
    
    # Confirma que os atletas das tentativas pertencem
    # à edição e a uma das equipes deste confronto.
    attempt_athlete_ids = {
        attempt["athlete_id"]
        for attempt in athlete_attempts_data
    }

    if attempt_athlete_ids:
        valid_attempt_athletes = OlympicAthlete.query.filter(
            OlympicAthlete.id.in_(attempt_athlete_ids),
            OlympicAthlete.edition_id == match.edition_id,
            OlympicAthlete.team_id.in_([
                match.team_a_id,
                match.team_b_id
            ])
        ).count()

        if valid_attempt_athletes != len(attempt_athlete_ids):
            return jsonify({
                "success": False,
                "message": (
                    "Existem tentativas vinculadas a atletas "
                    "que não pertencem às equipes deste confronto."
                )
            }), 400

    if any(
        attempt["athlete_id"] not in participant_id_set
        for attempt in athlete_attempts_data
    ):
        return jsonify({
            "success": False,
            "message": (
                "Existem tentativas registradas para atletas "
                "que não participam deste confronto."
            )
        }), 400

    
    
    # Identifica a modalidade de Pênaltis com segurança.
    is_penalty_modality = (
        "pênalti" in modality_name.lower()
        or "penalti" in modality_name.lower()
    )

    # Aplica as regras específicas somente aos Pênaltis.
    if is_penalty_modality:
        
        # Impede IDs de atletas repetidos na lista de participantes.
        if len(participant_ids) != len(set(participant_ids)):
            return jsonify({
                "success": False,
                "message": (
                    "Não é permitido registrar o mesmo atleta "
                    "mais de uma vez na súmula de Pênaltis."
                )
            }), 400

        penalty_athletes = OlympicAthlete.query.filter(
            OlympicAthlete.id.in_(participant_ids)
        ).all()
        
        # Confere se todos os participantes existem e pertencem
        # a uma das duas equipes deste confronto.
        if (
            len(penalty_athletes) != len(participant_ids)
            or any(
                athlete.team_id not in (
                    match.team_a_id,
                    match.team_b_id
                )
                for athlete in penalty_athletes
            )
        ):
            return jsonify({
                "success": False,
                "message": (
                    "A súmula de Pênaltis contém um atleta inválido "
                    "ou pertencente a outra equipe."
                )
            }), 400

        penalty_count_a = sum(
            1 for athlete in penalty_athletes
            if athlete.team_id == match.team_a_id
        )

        penalty_count_b = sum(
            1 for athlete in penalty_athletes
            if athlete.team_id == match.team_b_id
        )

        if penalty_count_a > 5 or penalty_count_b > 5:
            return jsonify({
                "success": False,
                "message": (
                    "A modalidade de Pênaltis permite "
                    "no máximo cinco atletas por equipe."
                )
            }), 400
            
        # Exige a mesma quantidade de atletas nas duas equipes.
        if penalty_count_a != penalty_count_b:
            return jsonify({
                "success": False,
                "message": (
                    "As duas equipes devem ter a mesma quantidade "
                    "de atletas na modalidade de Pênaltis."
                )
            }), 400 

        # Impede o salvamento sem participantes nos Pênaltis.
        if penalty_count_a == 0 or penalty_count_b == 0:
            return jsonify({
                "success": False,
                "message": (
                    "Para salvar a súmula de Pênaltis, "
                    "selecione pelo menos um atleta de cada equipe."
                )
            }), 400

    if (
        not isinstance(participant_ids, list)
        or any(
            type(athlete_id) is not int or athlete_id <= 0
            for athlete_id in participant_ids
        )
        or len(participant_ids) != len(set(participant_ids))
    ):
        return jsonify({
            "success": False,
            "message": (
                "A lista de participantes é inválida "
                "ou contém atletas duplicados."
            )
        }), 400
        
    # Verificar se todos os participantes pertencem
    # às equipes e à edição deste confronto.
    participants = (
        OlympicAthlete.query
        .filter(OlympicAthlete.id.in_(participant_ids))
        .all()
        if participant_ids else []
    )

    if (
        len(participants) != len(participant_ids)
        or any(
            athlete.edition_id != match.edition_id
            or athlete.team_id not in (
                match.team_a_id,
                match.team_b_id
            )
            for athlete in participants
        )
    ):
        return jsonify({
            "success": False,
            "message": (
                "Um ou mais atletas não pertencem "
                "às equipes deste confronto."
            )
        }), 400  

    # Regra de idade para a modalidade Golzinho
    modality_name = (match.modality.name or "").strip().lower()

    if modality_name == "golzinho":
        for athlete in participants:
            sex = (athlete.sex or "").strip().upper()

            if sex in ("M", "MASCULINO"):
                if athlete.age is None or athlete.age > 11:
                    return jsonify({
                        "success": False,
                        "message": (
                            f"O atleta {athlete.name} não atende "
                            "à regra de idade do Golzinho. "
                            "Meninos devem ter até 11 anos."
                        )
                    }), 400

    score_a = data.get("score_a")
    score_b = data.get("score_b")

    if (
        type(score_a) is not int
        or type(score_b) is not int
        or score_a < 0
        or score_b < 0
    ):
        return jsonify({
            "ok": False,
            "error": "O placar deve conter números inteiros maiores ou iguais a zero."
        }), 400
    
    # QUEIMADA E CORRIDA/REVEZAMENTO: resultados permitidos
    modality_name = match.modality.name.strip().lower()

    if (
        "queimada" in modality_name
        or "corrida" in modality_name
        or "revezamento" in modality_name
    ):
        valid_scores = (
            (1, 0),
            (0, 1),
            (0, 0)
        )

        if (score_a, score_b) not in valid_scores:
            return jsonify({
                "success": False,
                "message": (
                    "Nesta modalidade, informe somente "
                    "1 x 0, 0 x 1 ou 0 x 0."
                )
            }), 400
    
    disciplinary_fields = (
        "red_cards_a",
        "red_cards_b",
        "yellow_cards_a",
        "yellow_cards_b",
        "fouls_a",
        "fouls_b"
    )

    disciplinary_values = {}

    for field in disciplinary_fields:
        value = data.get(field)

        if type(value) is not int or value < 0:
            return jsonify({
                "success": False,
                "message": f"Valor inválido para {field}."
            }), 400

        disciplinary_values[field] = value
    

    athlete_goals = data.get("athlete_goals", [])
    
    modality_name = match.modality.name.strip().lower()

    if modality_name not in ("futsal", "golzinho"):
        if athlete_goals:
            return jsonify({
                "success": False,
                "message": "Esta modalidade não registra gols por atleta."
            }), 400

        if any(
            OlympicMatchGoal.query.filter_by(match_id=match.id).all()
        ):
            return jsonify({
                "success": False,
                "message": "Existem gols individuais vinculados a este confronto."
            }), 409

    if not isinstance(athlete_goals, list):
        return jsonify({
            "success": False,
            "message": "A lista de gols dos atletas é inválida."
        }), 400
        
    valid_athletes = OlympicAthlete.query.filter(
        OlympicAthlete.edition_id == match.edition_id,
        OlympicAthlete.team_id.in_([
            match.team_a_id,
            match.team_b_id
        ])
    ).all()

    valid_athlete_teams = {
        athlete.id: athlete.team_id
        for athlete in valid_athletes
    }
    
    total_goals_a = 0
    total_goals_b = 0
    
    seen_athlete_ids = set()

    for item in athlete_goals:
        if not isinstance(item, dict):
            return jsonify({
                "success": False,
                "message": "Registro de gols inválido."
            }), 400

        athlete_id = item.get("athlete_id")
        team_id = item.get("team_id")
        goals = item.get("goals")
        
        if athlete_id in seen_athlete_ids:
            return jsonify({
                "success": False,
                "message": "O mesmo atleta foi informado mais de uma vez."
            }), 400

        seen_athlete_ids.add(athlete_id)

        # Somente participantes selecionados podem marcar gols.
        # Atletas não selecionados podem aparecer com zero gols.
        if (
            type(athlete_id) is int
            and type(goals) is int
            and goals > 0
            and athlete_id not in participant_ids
        ):
            return jsonify({
                "success": False,
                "message": (
                    "Não é permitido registrar gols para "
                    "atletas que não foram selecionados "
                    "como participantes do confronto."
                )
            }), 400

        if (
            type(athlete_id) is not int
            or type(team_id) is not int
            or type(goals) is not int
            or goals < 0
            or valid_athlete_teams.get(athlete_id) != team_id
        ):
            return jsonify({
                "success": False,
                "message": "Atleta, equipe ou quantidade de gols inválida."
            }), 400 

        if team_id == match.team_a_id:
            total_goals_a += goals

        elif team_id == match.team_b_id:
            total_goals_b += goals  

       
        
    # Impede participantes duplicados
    # na mesma súmula.
    if len(participant_ids) != len(set(participant_ids)):
        return jsonify({
            "success": False,
            "message": (
                "Um mesmo atleta não pode ser registrado "
                "mais de uma vez como participante do confronto."
            )
        }), 400
        
    # Aceita somente registros com gols positivos.
    # Atletas sem gols permanecem apenas como participantes.
    if any(item["goals"] <= 0 for item in athlete_goals):
        return jsonify({
            "success": False,
            "message": (
                "A lista de artilheiros deve conter "
                "somente atletas que marcaram gols."
            )
        }), 400

    # Impede registros duplicados de gols
    # para o mesmo atleta no confronto.
    scorer_ids = [
        item["athlete_id"]
        for item in athlete_goals
    ]

    if len(scorer_ids) != len(set(scorer_ids)):
        return jsonify({
            "success": False,
            "message": (
                "Um mesmo atleta não pode aparecer "
                "mais de uma vez na lista de artilheiros."
            )
        }), 400

    # Garante que somente participantes selecionados
    # possam ter gols registrados neste confronto.
    selected_participant_ids = set(participant_ids)

    for item in athlete_goals:
        if item["athlete_id"] not in selected_participant_ids:
            return jsonify({
                "success": False,
                "message": (
                    "Não é permitido registrar gols para "
                    "atletas que não participam do confronto."
                )
            }), 400

    try:
        # Atualiza as tentativas individuais do confronto.
        OlympicMatchAttempt.query.filter_by(
            match_id=match.id
        ).delete(synchronize_session=False)

        for attempt in athlete_attempts_data:
            db.session.add(
                OlympicMatchAttempt(
                    match_id=match.id,
                    athlete_id=attempt["athlete_id"],
                    attempt_number=attempt["attempt_number"],
                    successful=attempt["successful"]
                )
            )

        # Em Futsal e Golzinho, o placar é determinado
        # automaticamente pelos gols individuais.
        if modality_name in ("futsal", "golzinho"):
            match.score_a = total_goals_a
            match.score_b = total_goals_b
        else:
            match.score_a = score_a
            match.score_b = score_b

        for field, value in disciplinary_values.items():
            setattr(match, field, value)

        match.status = "RASCUNHO"

        
        # Atualiza os gols individuais do confronto.
        existing_goals = {
            record.athlete_id: record
            for record in OlympicMatchGoal.query.filter_by(
                match_id=match.id
            ).all()
        }
        # Remove registros de gols que não constam
        # mais na lista atualizada enviada pelo formulário.
        submitted_scorer_ids = {
            item["athlete_id"]
            for item in athlete_goals
        }

        for athlete_id, record in existing_goals.items():
            if athlete_id not in submitted_scorer_ids:
                db.session.delete(record)

        for item in athlete_goals:
            athlete_id = item["athlete_id"]
            goals = item["goals"]

            if athlete_id in existing_goals:
                if goals == 0:
                    db.session.delete(existing_goals[athlete_id])
                else:
                    existing_goals[athlete_id].goals = goals

            elif goals > 0:
                db.session.add(
                    OlympicMatchGoal(
                        match_id=match.id,
                        athlete_id=athlete_id,
                        goals=goals
                    )
                )

        # Atualiza os participantes deste confronto.
        existing_participants = {
            record.athlete_id: record
            for record in OlympicMatchParticipant.query.filter_by(
                match_id=match.id
            ).all()
        }

        selected_ids = set(participant_ids)

        # Remove atletas retirados da súmula.
        for athlete_id, record in existing_participants.items():
            if athlete_id not in selected_ids:
                db.session.delete(record)

        # Adiciona atletas ainda não registrados.
        for athlete_id in selected_ids:
            if athlete_id not in existing_participants:
                db.session.add(
                    OlympicMatchParticipant(
                        match_id=match.id,
                        athlete_id=athlete_id
                    )
                )

        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Rascunho salvo com sucesso.",
            "match_id": match.id,
            "status": match.status,
            "score_a": match.score_a,
            "score_b": match.score_b
        })

    except ValueError as error:
        return jsonify({
            "success": False,
            "message": str(error)
        }), 400

    except Exception:
        db.session.rollback()
        app.logger.exception(
            "Erro ao salvar rascunho da súmula %s",
            match_id
        )

        return jsonify({
            "success": False,
            "message": "Não foi possível salvar o rascunho."
        }), 500


@app.route(
    "/admin/olimpiadas/confrontos/<int:match_id>/sumula/finalizar",
    methods=["POST"]
)
@admin_required_page
def admin_finalize_olympic_scoresheet(match_id):
    return finalize_olympic_scoresheet(match_id)


@app.route(
    "/olimpiadas/sumulas/confrontos/<int:match_id>/finalizar",
    methods=["POST"]
)
@olympic_scoresheet_access_required
def olympic_scoresheet_external_finalize(match_id):
    return finalize_olympic_scoresheet(match_id)


def finalize_olympic_scoresheet(match_id):

    match = db.session.get(OlympicMatch, match_id)


    if match is None:
        return jsonify({
            "success": False,
            "message": "Confronto não encontrado."
        }), 404

    if match.status == "FINALIZADO":
        return jsonify({
            "success": False,
            "message": "Esta súmula já foi finalizada."
        }), 400

    if match.status == "CANCELADO":
        return jsonify({
            "success": False,
            "message": "Não é possível finalizar um confronto cancelado."
        }), 400
        
    # Exige os cinco arremessos de cada participante no Basquete.
    modality_name = match.modality.name.strip().lower()
    
    # Exige três cobranças por participante na modalidade de Pênaltis.
    if "pênalti" in modality_name or "penalti" in modality_name:

        # Confere a quantidade de participantes de cada equipe.
        penalty_participants = OlympicMatchParticipant.query.filter_by(
            match_id=match.id
        ).all()

        penalty_athlete_ids = [
            participant.athlete_id
            for participant in penalty_participants
        ]

        penalty_athletes = OlympicAthlete.query.filter(
            OlympicAthlete.id.in_(penalty_athlete_ids)
        ).all()

        penalty_count_a = sum(
            1 for athlete in penalty_athletes
            if athlete.team_id == match.team_a_id
        )

        penalty_count_b = sum(
            1 for athlete in penalty_athletes
            if athlete.team_id == match.team_b_id
        )

        if (
            penalty_count_a == 0
            or penalty_count_b == 0
            or penalty_count_a > 5
            or penalty_count_b > 5
            or penalty_count_a != penalty_count_b
        ):
            return jsonify({
                "success": False,
                "message": (
                    "Não é possível finalizar a súmula de Pênaltis. "
                    "As equipes devem possuir a mesma quantidade "
                    "de atletas, entre 1 e 5 por equipe."
                )
            }), 400    

        penalty_participant_ids = {
            participant.athlete_id
            for participant in OlympicMatchParticipant.query.filter_by(
                match_id=match.id
            ).all()
        }

        penalty_attempts = OlympicMatchAttempt.query.filter_by(
            match_id=match.id
        ).all()

        penalty_attempts_by_athlete = {
            athlete_id: set()
            for athlete_id in penalty_participant_ids
        }

        for attempt in penalty_attempts:
            if attempt.athlete_id in penalty_attempts_by_athlete:
                penalty_attempts_by_athlete[
                    attempt.athlete_id
                ].add(attempt.attempt_number)

        if any(
            penalty_attempts_by_athlete[athlete_id] != {1, 2, 3}
            for athlete_id in penalty_participant_ids
        ):
            return jsonify({
                "success": False,
                "message": (
                    "Não é possível finalizar a súmula de Pênaltis. "
                    "Todos os participantes precisam ter "
                    "as três cobranças registradas."
                )
            }), 400
            
        # Identifica a equipe de cada atleta participante.
        penalty_athlete_teams = {
            athlete.id: athlete.team_id
            for athlete in OlympicAthlete.query.filter(
                OlympicAthlete.id.in_(penalty_participant_ids)
            ).all()
        }

        # Conta as cobranças convertidas por cada equipe.
        penalty_hits_a = sum(
            1 for attempt in penalty_attempts
            if attempt.successful
            and attempt.athlete_id in penalty_participant_ids
            and penalty_athlete_teams.get(
                attempt.athlete_id
            ) == match.team_a_id
        )

        penalty_hits_b = sum(
            1 for attempt in penalty_attempts
            if attempt.successful
            and attempt.athlete_id in penalty_participant_ids
            and penalty_athlete_teams.get(
                attempt.athlete_id
            ) == match.team_b_id
        )

        expected_penalty_score_a = 1 if penalty_hits_a > penalty_hits_b else 0
        expected_penalty_score_b = 1 if penalty_hits_b > penalty_hits_a else 0

        if (
            match.score_a != expected_penalty_score_a
            or match.score_b != expected_penalty_score_b
        ):
            return jsonify({
                "success": False,
                "message": (
                    "O placar de Pênaltis não corresponde às "
                    "cobranças individuais registradas. "
                    "Salve novamente o rascunho antes de finalizar."
                )
            }), 400

    if "basquete" in modality_name:
        saved_participant_ids = {
            participant.athlete_id
            for participant in OlympicMatchParticipant.query.filter_by(
                match_id=match.id
            ).all()
        }

        saved_attempts = OlympicMatchAttempt.query.filter_by(
            match_id=match.id
        ).all()

        attempts_by_athlete = {
            athlete_id: set()
            for athlete_id in saved_participant_ids
        }

        for attempt in saved_attempts:
            if attempt.athlete_id in attempts_by_athlete:
                attempts_by_athlete[attempt.athlete_id].add(
                    attempt.attempt_number
                )

        if any(
            attempts_by_athlete[athlete_id] != set(range(1, 6))
            for athlete_id in saved_participant_ids
        ):
            return jsonify({
                "success": False,
                "message": (
                    "Não é possível finalizar o Basquete. "
                    "Todos os participantes precisam ter "
                    "os cinco arremessos registrados."
                )
            }), 400  
            
        # Calcula os acertos de cada equipe.
        athlete_teams = {
            athlete.id: athlete.team_id
            for athlete in OlympicAthlete.query.filter(
                OlympicAthlete.id.in_(saved_participant_ids)
            ).all()
        }

        hits_a = sum(
            1 for attempt in saved_attempts
            if attempt.successful
            and attempt.athlete_id in saved_participant_ids
            and athlete_teams.get(attempt.athlete_id) == match.team_a_id
        )

        hits_b = sum(
            1 for attempt in saved_attempts
            if attempt.successful
            and attempt.athlete_id in saved_participant_ids
            and athlete_teams.get(attempt.athlete_id) == match.team_b_id
        )

        expected_score_a = 1 if hits_a > hits_b else 0
        expected_score_b = 1 if hits_b > hits_a else 0

        if (
            match.score_a != expected_score_a
            or match.score_b != expected_score_b
        ):
            return jsonify({
                "success": False,
                "message": (
                    "O placar do Basquete não corresponde "
                    "aos arremessos individuais registrados. "
                    "Salve novamente o rascunho antes de finalizar."
                )
            }), 400
        
    if match.status != "RASCUNHO":
        return jsonify({
            "success": False,
            "message": "Salve a súmula como rascunho antes de finalizá-la."
        }), 400 

    # Verifica se as duas equipes possuem participantes.
    selected_participants = OlympicMatchParticipant.query.filter_by(
        match_id=match.id
    ).all()

    team_a_has_participants = False
    team_b_has_participants = False

    for participant in selected_participants:

        # Confirma que o atleta pertence à edição e
        # a uma das equipes deste confronto.
        if (
            participant.athlete.edition_id != match.edition_id
            or participant.athlete.team_id not in (
                match.team_a_id,
                match.team_b_id
            )
        ):
            return jsonify({
                "success": False,
                "message": (
                    "Não é possível finalizar a súmula. "
                    "Existe um participante que não pertence "
                    "à edição ou às equipes deste confronto."
                )
            }), 400
            
        # Golzinho: modalidade mista, permitida de 7 a 11 anos.
        if match.modality.name.strip().lower() == "golzinho":
            athlete_age = participant.athlete.age

            if (
                type(athlete_age) is not int
                or athlete_age < 7
                or athlete_age > 11
            ):
                return jsonify({
                    "success": False,
                    "message": (
                        "Não é possível finalizar a súmula. "
                        "O Golzinho permite participantes "
                        "de 7 a 11 anos, independentemente do sexo."
                    )
                }), 400

        if participant.athlete.team_id == match.team_a_id:
            team_a_has_participants = True

        elif participant.athlete.team_id == match.team_b_id:
            team_b_has_participants = True

    if not team_a_has_participants or not team_b_has_participants:
        return jsonify({
            "success": False,
            "message": (
                "Não é possível finalizar a súmula. "
                "Selecione pelo menos um atleta de cada equipe "
                "e salve o rascunho antes de finalizar."
            )
        }), 400

    # Valida o placar antes de finalizar.
    if (
        type(match.score_a) is not int
        or type(match.score_b) is not int
        or match.score_a < 0
        or match.score_b < 0
    ):
        return jsonify({
            "success": False,
            "message": "A súmula precisa ter um placar válido antes da finalização."
        }), 400
        
    total_goals_a = 0
    total_goals_b = 0

    saved_goals = OlympicMatchGoal.query.filter_by(
        match_id=match.id
    ).all()
    
    # Somente Futsal e Golzinho possuem artilharia individual.
    modality_name = match.modality.name.strip().lower()

    if modality_name not in ("futsal", "golzinho") and saved_goals:
        return jsonify({
            "success": False,
            "message": (
                "Não é possível finalizar a súmula. "
                "Esta modalidade não permite registros "
                "individuais de gols."
            )
        }), 400

    # Identifica os participantes registrados no confronto.
    participant_athlete_ids = {
        participant.athlete_id
        for participant in OlympicMatchParticipant.query.filter_by(
            match_id=match.id
        ).all()
    }

    for record in saved_goals:

        # Valida a quantidade de gols registrada.
        if type(record.goals) is not int or record.goals <= 0:
            return jsonify({
                "success": False,
                "message": (
                    "Não é possível finalizar a súmula. "
                    "Existe um registro individual de gols inválido. "
                    "Verifique os gols dos atletas antes de finalizar."
                )
            }), 400

        # Um atleta só pode ter gols registrados se participou.
        if record.athlete_id not in participant_athlete_ids:
            return jsonify({
                "success": False,
                "message": (
                    "Não é possível finalizar a súmula. "
                    "Existem gols registrados para atletas "
                    "que não estão na lista de participantes."
                )
            }), 400

        if record.athlete.team_id == match.team_a_id:
            total_goals_a += record.goals

        elif record.athlete.team_id == match.team_b_id:
            total_goals_b += record.goals

        else:
            return jsonify({
                "success": False,
                "message": "Existe um gol registrado para um atleta que não pertence às equipes deste confronto."
            }), 400

    # Em Futsal e Golzinho, o placar deve corresponder
    # exatamente à soma dos gols individuais.
    if modality_name in ("futsal", "golzinho"):
        if (
            total_goals_a != match.score_a
            or total_goals_b != match.score_b
        ):
            return jsonify({
                "success": False,
                "message": (
                    "Não é possível finalizar a súmula. "
                    "O placar deve corresponder exatamente "
                    "à soma dos gols registrados pelos atletas. "
                    "Salve novamente o rascunho antes de finalizar."
                )
            }), 400

    try:
        # Recupera os atletas selecionados neste confronto.
        match_participants = OlympicMatchParticipant.query.filter_by(
            match_id=match.id
        ).all()

        # Identifica atletas já inscritos na modalidade.
        registered_athlete_ids = {
            registration.athlete_id
            for registration in OlympicModalityRegistration.query.filter_by(
                edition_id=match.edition_id,
                modality_id=match.modality_id
            ).all()
        }

        # Inscreve apenas quem ainda não está registrado.
        for participant in match_participants:
            if participant.athlete_id not in registered_athlete_ids:
                db.session.add(
                    OlympicModalityRegistration(
                        edition_id=match.edition_id,
                        modality_id=match.modality_id,
                        athlete_id=participant.athlete_id
                    )
                )

                registered_athlete_ids.add(participant.athlete_id)

        match.status = "FINALIZADO"

        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Súmula finalizada com sucesso!"
        }), 200

    except Exception as error:
        db.session.rollback()

        print(
            "ERRO AO FINALIZAR SÚMULA:",
            repr(error),
            flush=True
        )

        return jsonify({
            "success": False,
            "message": "Não foi possível finalizar a súmula."
        }), 500       

@app.route(
    "/admin/olimpiadas/edicoes/<int:edition_id>/confrontos",
    methods=["GET"]
)
@admin_required_page
def admin_list_olympic_matches(edition_id):
    try:
        edition = db.session.get(
            OlympicEdition,
            edition_id
        )

        if not edition:
            return jsonify({
                "success": False,
                "message": "Edição não encontrada."
            }), 404

        matches = (
            OlympicMatch.query
            .filter_by(edition_id=edition_id)
            .order_by(
                OlympicMatch.match_date,
                OlympicMatch.match_time,
                OlympicMatch.id
            )
            .all()
        )

        match_list = []

        for match in matches:
            modality = match.modality
            team_a = match.team_a
            team_b = match.team_b

            match_list.append({
                "id": match.id,
                "edition_id": match.edition_id,
                "modality_id": match.modality_id,
                "modality_name": modality.name,
                "team_a_id": match.team_a_id,
                "team_a_name": team_a.name,
                "team_a_color": team_a.color,
                "team_a_coach": team_a.coach,
                "team_b_id": match.team_b_id,
                "team_b_name": team_b.name,
                "team_b_color": team_b.color,
                "team_b_coach": team_b.coach,
                "match_date": match.match_date.isoformat(),
                "match_time": match.match_time.strftime("%H:%M"),
                "shift": match.shift,
                "phase": match.phase,
                "status": match.status,
                "score_a": match.score_a,
                "score_b": match.score_b,
                "notes": match.notes
            })

        return jsonify({
            "success": True,
            "edition": {
                "id": edition.id,
                "name": edition.name,
                "year": edition.year
            },
            "matches": match_list
        }), 200

    except Exception:
        app.logger.exception(
            "Erro ao listar confrontos olímpicos"
        )

        return jsonify({
            "success": False,
            "message": "Erro interno ao consultar confrontos."
        }), 500





@app.route(
    "/admin/olimpiadas/edicoes/<int:edition_id>/inscricoes",
    methods=["GET"]
)
@admin_required_page
def admin_list_olympic_modality_registrations(edition_id):
    try:
        # Verifica se a edição existe
        edition = db.session.get(
            OlympicEdition,
            edition_id
        )

        if not edition:
            return jsonify({
                "success": False,
                "message": "Edição não encontrada."
            }), 404

        # Busca as inscrições da edição
        registrations = (
            OlympicModalityRegistration.query
            .filter_by(edition_id=edition_id)
            .order_by(OlympicModalityRegistration.id)
            .all()
        )

        registration_list = []

        for registration in registrations:

            modality = registration.modality
            athlete = registration.athlete

            # Recupera a equipe do atleta
            team = db.session.get(
                OlympicTeam,
                athlete.team_id
            )

            registration_list.append({
                "id": registration.id,
                "edition_id": registration.edition_id,
                "modality_id": registration.modality_id,
                "modality_name": modality.name,
                "modality_is_active": modality.is_active,
                "athlete_id": registration.athlete_id,
                "athlete_name": athlete.name,
                "team_id": athlete.team_id,
                "team_name": team.name if team else "",
                "team_color": team.color if team else "",
                "team_coach": team.coach if team else "",
                "team_shift": team.shift if team else ""
            })

        return jsonify({
            "success": True,
            "edition": {
                "id": edition.id,
                "name": edition.name,
                "year": edition.year
            },
            "registrations": registration_list
        }), 200

    except Exception:
        app.logger.exception(
            "Erro ao listar inscrições olímpicas"
        )

        return jsonify({
            "success": False,
            "message": "Erro interno ao consultar inscrições."
        }), 500


@app.route(
    "/admin/olimpiadas/inscricoes/<int:registration_id>/excluir",
    methods=["DELETE"]
)
@admin_required_page
def admin_delete_olympic_modality_registration(registration_id):
    try:
        # Localiza a inscrição
        registration = db.session.get(
            OlympicModalityRegistration,
            registration_id
        )

        if not registration:
            return jsonify({
                "success": False,
                "message": "Inscrição não encontrada."
            }), 404

        # Verifica a edição da inscrição
        edition = db.session.get(
            OlympicEdition,
            registration.edition_id
        )

        if not edition or not edition.is_active:
            return jsonify({
                "success": False,
                "message": "Não é possível cancelar inscrições de uma edição inativa."
            }), 400

        # Guarda os dados para a resposta
        athlete_name = registration.athlete.name
        modality_name = registration.modality.name

        # Exclui somente o vínculo de inscrição
        db.session.delete(registration)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": (
                f"Inscrição de {athlete_name} na modalidade "
                f"{modality_name} cancelada com sucesso!"
            )
        }), 200

    except Exception:
        db.session.rollback()

        app.logger.exception(
            "Erro ao cancelar inscrição olímpica"
        )

        return jsonify({
            "success": False,
            "message": "Erro interno ao cancelar inscrição."
        }), 500


# ==========================================
# OLIMPÍADAS - LISTAR ATLETAS POR EDIÇÃO
# ==========================================

@app.route(
    "/admin/olimpiadas/edicoes/<int:edition_id>/atletas",
    methods=["GET"]
)
@admin_required_page
def admin_list_olympic_athletes(edition_id):

    edition = db.session.get(
        OlympicEdition,
        edition_id
    )

    if not edition:
        return jsonify({
            "message": "Edição não encontrada."
        }), 404

    athletes = (
        db.session.query(OlympicAthlete, OlympicTeam)
        .join(
            OlympicTeam,
            OlympicAthlete.team_id == OlympicTeam.id
        )
        .filter(
            OlympicAthlete.edition_id == edition_id,
            OlympicTeam.edition_id == edition_id
        )
        .order_by(
            OlympicTeam.shift.asc(),
            OlympicTeam.color.asc(),
            OlympicAthlete.name.asc()
        )
        .all()
    )

    return jsonify({
        "edition": {
            "id": edition.id,
            "name": edition.name,
            "year": edition.year
        },
        "athletes": [
            {
                "id": athlete.id,
                "edition_id": athlete.edition_id,
                "team_id": athlete.team_id,
                "name": athlete.name,
                "age": athlete.age,
                "sex": athlete.sex,
                "team": {
                    "id": team.id,
                    "name": team.name,
                    "color": team.color,
                    "coach": team.coach,
                    "shift": team.shift
                }
            }
            for athlete, team in athletes
        ]
    }), 200


@app.route("/admin/passeios")
@admin_required_page
def admin_trips_page():
    trips = (
        TripEvent.query
        .order_by(
            TripEvent.event_date.desc(),
            TripEvent.created_at.desc()
        )
        .all()
    )

    return render_template(
        "admin_trips.html",
        trips=trips,
        active_page="trips"
    )

@app.route(
    "/admin/passeios",
    methods=["POST"]
)
@admin_required_page
def admin_create_trip():
    title = (
        request.form.get("title")
        or ""
    ).strip()

    description = (
        request.form.get("description")
        or ""
    ).strip()

    destination = (
        request.form.get("destination")
        or ""
    ).strip()

    event_date_raw = (
        request.form.get("event_date")
        or ""
    ).strip()

    departure_time_raw = (
        request.form.get("departure_time")
        or ""
    ).strip()

    return_time_raw = (
        request.form.get("return_time")
        or ""
    ).strip()

    price_raw = (
        request.form.get("price")
        or "0"
    ).strip()

    
    registration_deadline_raw = (
        request.form.get(
            "registration_deadline"
        )
        or ""
    ).strip()

    payment_instructions = (
        request.form.get(
            "payment_instructions"
        )
        or ""
    ).strip()
    
    pix_key = (
        request.form.get("pix_key")
        or ""
    ).strip()

    pix_key_type = (
        request.form.get("pix_key_type")
        or ""
    ).strip().upper()

    pix_receiver_name = (
        request.form.get("pix_receiver_name")
        or ""
    ).strip()

    pix_receiver_city = (
        request.form.get("pix_receiver_city")
        or ""
    ).strip()
    
    allowed_required_fields = {
        "student_name",
        "guardian_name",
        "age",
        "platoon",
        "shift",
        "transport_route",
        "guardian_whatsapp",
        "payment_receipt"
    }

    required_fields = [
        field
        for field in request.form.getlist("required_fields")
        if field in allowed_required_fields
    ]

    if not title:
        return jsonify({
            "message": "Informe o nome do passeio."
        }), 400

    if not event_date_raw:
        return jsonify({
            "message": "Informe a data do passeio."
        }), 400

    try:
        event_date = datetime.strptime(
            event_date_raw,
            "%Y-%m-%d"
        ).date()
    except ValueError:
        return jsonify({
            "message": "Data inválida."
        }), 400

    departure_time = None

    if departure_time_raw:
        try:
            departure_time = datetime.strptime(
                departure_time_raw,
                "%H:%M"
            ).time()
        except ValueError:
            return jsonify({
                "message": "Horário de saída inválido."
            }), 400

    return_time = None

    if return_time_raw:
        try:
            return_time = datetime.strptime(
                return_time_raw,
                "%H:%M"
            ).time()
        except ValueError:
            return jsonify({
                "message": "Horário de retorno inválido."
            }), 400

    try:
        price = float(
            price_raw.replace(",", ".")
        )
    except ValueError:
        return jsonify({
            "message": "Valor inválido."
        }), 400

    
    registration_deadline = None

    if registration_deadline_raw:
        try:
            registration_deadline = (
                datetime.fromisoformat(
                    registration_deadline_raw
                )
            )
        except ValueError:
            return jsonify({
                "message": "Prazo de inscrição inválido."
            }), 400

    base_slug = generate_slug(
        title
    )

    if not base_slug:
        base_slug = "passeio"

    slug = base_slug
    suffix = 2

    while TripEvent.query.filter_by(
        slug=slug
    ).first():
        slug = f"{base_slug}-{suffix}"
        suffix += 1

    trip = TripEvent(
        title=title,
        slug=slug,
        description=description or None,
        destination=destination or None,
        event_date=event_date,
        departure_time=departure_time,
        return_time=return_time,
        price=price,
        required_fields=required_fields,
        registration_deadline=(
            registration_deadline
        ),
        payment_instructions=(
            payment_instructions or None
        ),
        
        pix_key=(
            pix_key or None
        ),

        pix_key_type=(
            pix_key_type or None
        ),

        pix_receiver_name=(
            pix_receiver_name or None
        ),

        pix_receiver_city=(
            pix_receiver_city or None
        ),
        is_active=True
    )

    db.session.add(trip)
    db.session.commit()

    return jsonify({
        "message": "Passeio criado com sucesso.",
        "trip_id": trip.id,
        "slug": trip.slug,
        "public_url": (
            f"/passeios/{trip.slug}"
        )
    }), 201 
    
@app.route(
    "/admin/passeios/<int:trip_id>/excluir",
    methods=["DELETE"]
)
@admin_required_page
def admin_delete_trip(trip_id):

    trip = db.session.get(
        TripEvent,
        trip_id
    )

    if not trip:
        return jsonify({
            "message":
                "Passeio não encontrado."
        }), 404

    try:

        title = trip.title

        db.session.delete(
            trip
        )

        db.session.commit()

        return jsonify({
            "message":
                f'Passeio "{title}" excluído com sucesso.'
        })

    except Exception as error:

        db.session.rollback()

        print(
            "ERRO EXCLUIR PASSEIO:",
            repr(error),
            flush=True
        )

        return jsonify({
            "message":
                "Não foi possível excluir o passeio."
        }), 500   

@app.route(
    "/admin/passeios/<int:trip_id>/editar",
    methods=["POST"]
)
@admin_required_page
def admin_edit_trip(trip_id):

    trip = db.session.get(
        TripEvent,
        trip_id
    )

    if not trip:
        return jsonify({
            "message":
                "Passeio não encontrado."
        }), 404

    title = (
        request.form.get("title")
        or ""
    ).strip()

    description = (
        request.form.get("description")
        or ""
    ).strip()

    destination = (
        request.form.get("destination")
        or ""
    ).strip()

    event_date_raw = (
        request.form.get("event_date")
        or ""
    ).strip()

    departure_time_raw = (
        request.form.get("departure_time")
        or ""
    ).strip()

    return_time_raw = (
        request.form.get("return_time")
        or ""
    ).strip()

    price_raw = (
        request.form.get("price")
        or "0"
    ).strip()

    registration_deadline_raw = (
        request.form.get(
            "registration_deadline"
        )
        or ""
    ).strip()

    payment_instructions = (
        request.form.get(
            "payment_instructions"
        )
        or ""
    ).strip()

    pix_key = (
        request.form.get("pix_key")
        or ""
    ).strip()

    pix_key_type = (
        request.form.get("pix_key_type")
        or ""
    ).strip().upper()

    pix_receiver_name = (
        request.form.get(
            "pix_receiver_name"
        )
        or ""
    ).strip()

    pix_receiver_city = (
        request.form.get(
            "pix_receiver_city"
        )
        or ""
    ).strip()

    allowed_required_fields = {
        "student_name",
        "guardian_name",
        "age",
        "platoon",
        "shift",
        "transport_route",
        "guardian_whatsapp",
        "payment_receipt"
    }

    required_fields = [
        field
        for field in request.form.getlist("required_fields")
        if field in allowed_required_fields
    ]

    if not title:
        return jsonify({
            "message":
                "Informe o nome do passeio."
        }), 400

    if not event_date_raw:
        return jsonify({
            "message":
                "Informe a data do passeio."
        }), 400

    try:
        event_date = datetime.strptime(
            event_date_raw,
            "%Y-%m-%d"
        ).date()

    except ValueError:
        return jsonify({
            "message":
                "Data inválida."
        }), 400

    departure_time = None

    if departure_time_raw:

        try:
            departure_time = datetime.strptime(
                departure_time_raw,
                "%H:%M"
            ).time()

        except ValueError:
            return jsonify({
                "message":
                    "Horário de saída inválido."
            }), 400

    return_time = None

    if return_time_raw:

        try:
            return_time = datetime.strptime(
                return_time_raw,
                "%H:%M"
            ).time()

        except ValueError:
            return jsonify({
                "message":
                    "Horário de retorno inválido."
            }), 400

    try:
        price = float(
            price_raw.replace(",", ".")
        )

    except ValueError:
        return jsonify({
            "message":
                "Valor inválido."
        }), 400

    registration_deadline = None

    if registration_deadline_raw:

        try:
            registration_deadline = (
                datetime.fromisoformat(
                    registration_deadline_raw
                )
            )

        except ValueError:
            return jsonify({
                "message":
                    "Prazo de inscrição inválido."
            }), 400

    try:

        trip.title = title
        trip.description = (
            description or None
        )
        trip.destination = (
            destination or None
        )
        trip.event_date = event_date
        trip.departure_time = departure_time
        trip.return_time = return_time
        trip.price = price

        trip.registration_deadline = (
            registration_deadline
        )

        trip.payment_instructions = (
            payment_instructions or None
        )

        trip.pix_key = (
            pix_key or None
        )

        trip.pix_key_type = (
            pix_key_type or None
        )

        trip.pix_receiver_name = (
            pix_receiver_name or None
        )

        trip.pix_receiver_city = (
            pix_receiver_city or None
        )

        trip.required_fields = required_fields

        db.session.commit()

        return jsonify({
            "message":
                "Passeio atualizado com sucesso."
        })

    except Exception as error:

        db.session.rollback()

        print(
            "ERRO EDITAR PASSEIO:",
            repr(error),
            flush=True
        )

        return jsonify({
            "message":
                "Não foi possível atualizar o passeio."
        }), 500        
    
@app.route("/admin/ofertas")
@admin_required_page
def admin_offers_page():
    
    selected_store = (
        request.args.get("store")
        or ""
    ).strip()

    query = AffiliateProduct.query

    if selected_store:
        query = query.filter(
            AffiliateProduct.store == selected_store
        )

    offers = (
        query
        .order_by(
            AffiliateProduct.created_at.desc()
        )
        .all()
    )

    total_offers = (
        AffiliateProduct.query
        .count()
    )

    active_offers = (
        AffiliateProduct.query
        .filter(
            AffiliateProduct.is_active.is_(True)
        )
        .count()
    )

    featured_offers = (
        AffiliateProduct.query
        .filter(
            AffiliateProduct.is_featured.is_(True)
        )
        .count()
    )

    expired_offers = (
        AffiliateProduct.query
        .filter(
            AffiliateProduct.expires_at.isnot(None),
            AffiliateProduct.expires_at < utc_now()
        )
        .count()
    )

    total_clicks = (
        db.session.query(
            func.coalesce(
                func.sum(
                    AffiliateProduct.click_count
                ),
                0
            )
        )
        .scalar()
    )
    
    affiliate_stores = (
        AffiliateStore.query
        .order_by(
            AffiliateStore.display_order.asc(),
            AffiliateStore.name.asc()
        )
        .all()
    )

    return render_template(
        "admin_offers.html",
        offers=offers,
        affiliate_stores=affiliate_stores,
        total_offers=total_offers,
        active_offers=active_offers,
        featured_offers=featured_offers,
        expired_offers=expired_offers,
        total_clicks=total_clicks,
        selected_store=selected_store,
        active_page="offers"
    )
    
@app.route(
    "/admin/ofertas/<int:offer_id>/toggle-status",
    methods=["POST"]
)
@admin_required_page
def admin_offer_toggle_status(offer_id):

    offer = db.session.get(
        AffiliateProduct,
        offer_id
    )

    if not offer:
        return jsonify({
            "message": "Oferta não encontrada."
        }), 404

    try:

        offer.is_active = not bool(
            offer.is_active
        )

        db.session.commit()

        return jsonify({
            "message": (
                "Oferta ativada com sucesso."
                if offer.is_active
                else "Oferta desativada com sucesso."
            ),
            "is_active": offer.is_active
        })

    except Exception as error:

        db.session.rollback()

        print(
            "ERRO ALTERAR STATUS OFERTA:",
            repr(error),
            flush=True
        )

        return jsonify({
            "message":
                "Não foi possível alterar o status."
        }), 500



@app.route(
    "/admin/ofertas/<int:offer_id>/toggle-featured",
    methods=["POST"]
)
@admin_required_page
def admin_offer_toggle_featured(offer_id):

    offer = db.session.get(
        AffiliateProduct,
        offer_id
    )

    if not offer:
        return jsonify({
            "message": "Oferta não encontrada."
        }), 404

    try:

        offer.is_featured = not bool(
            offer.is_featured
        )

        db.session.commit()

        return jsonify({
            "message": (
                "Oferta destacada com sucesso."
                if offer.is_featured
                else "Destaque removido com sucesso."
            ),
            "is_featured":
                offer.is_featured
        })

    except Exception as error:

        db.session.rollback()

        print(
            "ERRO ALTERAR DESTAQUE OFERTA:",
            repr(error),
            flush=True
        )

        return jsonify({
            "message":
                "Não foi possível alterar o destaque."
        }), 500

@app.route(
    "/admin/ofertas/<int:offer_id>/excluir",
    methods=["DELETE"]
)
@admin_required_page
def admin_offer_delete(offer_id):

    offer = db.session.get(
        AffiliateProduct,
        offer_id
    )

    if not offer:
        return jsonify({
            "message": "Oferta não encontrada."
        }), 404

    try:

        title = offer.title

        db.session.delete(
            offer
        )

        db.session.commit()

        return jsonify({
            "message":
                f'Oferta "{title}" excluída com sucesso.'
        })

    except Exception as error:

        db.session.rollback()

        print(
            "ERRO EXCLUIR OFERTA:",
            repr(error),
            flush=True
        )

        return jsonify({
            "message":
                "Não foi possível excluir a oferta."
        }), 500

@app.route(
    "/admin/ofertas/<int:offer_id>/editar"
)
@admin_required_page
def admin_edit_offer_page(offer_id):

    offer = db.session.get(
        AffiliateProduct,
        offer_id
    )

    if not offer:
        abort(404)

    return render_template(
        "admin_offer_form.html",
        offer=offer,
        active_page="offers"
    )     

@app.route(
    "/admin/ofertas/<int:offer_id>",
    methods=["PUT"]
)
@admin_required_page
def admin_update_offer(offer_id):

    offer = db.session.get(
        AffiliateProduct,
        offer_id
    )

    if not offer:

        return jsonify({
            "message":
                "Oferta não encontrada."
        }), 404

    try:

        data = (
            request.get_json(
                silent=True
            )
            or {}
        )

        title = str(
            data.get("title")
            or ""
        ).strip()

        affiliate_url = str(
            data.get("affiliate_url")
            or ""
        ).strip()
        
        store_code = str(
            data.get("store_code")
            or ""
        ).strip().upper()

        external_product_id = str(
            data.get("external_product_id")
            or ""
        ).strip().upper()
        
        if store_code == "MERCADO_LIVRE":

            if not external_product_id:

                return jsonify({
                    "message":
                        "Informe o código MLB do produto do Mercado Livre."
                }), 400

            if not re.fullmatch(
                r"MLB\d+",
                external_product_id
            ):

                return jsonify({
                    "message":
                        "Código Mercado Livre inválido. Use o formato MLB1234567890."
                }), 400

        if not title:

            return jsonify({
                "message":
                    "Informe o nome do produto."
            }), 400

        if not affiliate_url:

            return jsonify({
                "message":
                    "Informe o link de afiliado."
            }), 400

        def parse_price(value):

            value = str(
                value or ""
            ).strip()

            if not value:
                return None

            value = (
                value
                .replace("R$", "")
                .replace(" ", "")
                .strip()
            )

            if "." in value and "," in value:

                if value.rfind(",") > value.rfind("."):
                    # 1.990,90 -> 1990.90
                    value = (
                        value
                        .replace(".", "")
                        .replace(",", ".")
                    )
                else:
                    # 1,990.90 -> 1990.90
                    value = value.replace(",", "")

            elif "," in value:
                # 19,90 -> 19.90
                value = value.replace(",", ".")

            # Se houver somente ponto, mantém.
            # 19.90 -> 19.90

            try:

                return Decimal(
                    value
                )

            except InvalidOperation:

                return None

        expires_at = None

        expires_raw = str(
            data.get("expires_at")
            or ""
        ).strip()

        if expires_raw:

            try:

                expires_at = datetime.strptime(
                    expires_raw,
                    "%Y-%m-%d"
                )

            except ValueError:

                return jsonify({
                    "message":
                        "Data de validade inválida."
                }), 400

        offer.title = title

        offer.store = (
            str(
                data.get("store")
                or ""
            ).strip()
            or None
        )

        offer.category = (
            str(
                data.get("category")
                or ""
            ).strip()
            or None
        )

        offer.description = (
            str(
                data.get("description")
                or ""
            ).strip()
            or None
        )

        offer.image_url = (
            str(
                data.get("image_url")
                or ""
            ).strip()
            or None
        )

        offer.affiliate_url = (
            affiliate_url
        )

        offer.old_price = parse_price(
            data.get("old_price")
        )

        offer.price = parse_price(
            data.get("price")
        )

        offer.expires_at = (
            expires_at
        )
        
        offer.store_code = (
            store_code or None
        )

        offer.external_product_id = (
            external_product_id or None
        )

        db.session.commit()

        return jsonify({
            "message":
                "Oferta atualizada com sucesso."
        })

    except Exception as error:

        db.session.rollback()

        print(
            "ERRO ATUALIZAR OFERTA:",
            repr(error),
            flush=True
        )

        return jsonify({
            "message":
                "Não foi possível atualizar a oferta."
        }), 500    

@app.route(
    "/admin/ofertas/detectar-mercado-livre",
    methods=["POST"]
)
@admin_required_page
def admin_detect_mercado_livre_product():

    try:

        data = (
            request.get_json(
                silent=True
            )
            or {}
        )

        affiliate_url = str(
            data.get("url")
            or ""
        ).strip()

        if not affiliate_url:

            return jsonify({
                "message":
                    "Informe o link do Mercado Livre."
            }), 400

        # ========================================
        # SEGURANÇA: aceita somente Mercado Livre
        # ========================================

        parsed_url = urlparse(
            affiliate_url
        )

        hostname = (
            parsed_url.hostname
            or ""
        ).lower()

        allowed_hosts = (
            "meli.la",
            "mercadolivre.com.br",
            "www.mercadolivre.com.br"
        )

        if hostname not in allowed_hosts:

            return jsonify({
                "message":
                    "O link informado não pertence ao Mercado Livre."
            }), 400

        # ========================================
        # SEGUE O REDIRECIONAMENTO DO LINK CURTO
        # ========================================

        response = requests.get(
            affiliate_url,
            allow_redirects=True,
            timeout=(5, 12),
            headers={
                "User-Agent":
                    "Mozilla/5.0 CataLogin/1.0"
            }
        )

        response.raise_for_status()

        final_url = (
            response.url
            or affiliate_url
        )

        decoded_url = unquote(
            final_url
        )
        
        
        for index, history_item in enumerate(
            response.history
        ):

            print(
                f"ML REDIRECT {index}:",
                history_item.status_code,
                history_item.headers.get(
                    "Location"
                ),
                flush=True
            )

        # ========================================
        # PROCURA O ID REAL DO ANÚNCIO
        #
        # Exemplos:
        # item_id:MLB6713010960
        # item_id=MLB6713010960
        # wid=MLB6713010960
        # ========================================

        external_product_id = None


        # ========================================
        # 1. PROCURA NA URL FINAL
        # ========================================

        url_patterns = [
            r"item_id[:=%3A]+(MLB\d+)",
            r"[?&#]wid=(MLB\d+)",
            r"item_id(?:=|:)(MLB\d+)"
        ]

        for pattern in url_patterns:

            match = re.search(
                pattern,
                decoded_url,
                flags=re.IGNORECASE
            )

            if match:

                external_product_id = (
                    match
                    .group(1)
                    .upper()
                )

                break


        # ========================================
        # 2. PROCURA NOS REDIRECIONAMENTOS
        # ========================================

        if not external_product_id:

            for history_item in response.history:

                location = (
                    history_item.headers.get(
                        "Location"
                    )
                    or ""
                )

                location = unquote(
                    location
                )

                for pattern in url_patterns:

                    match = re.search(
                        pattern,
                        location,
                        flags=re.IGNORECASE
                    )

                    if match:

                        external_product_id = (
                            match
                            .group(1)
                            .upper()
                        )

                        break

                if external_product_id:
                    break


        # ========================================
        # 3. PROCURA NO HTML RETORNADO
        # ========================================

        if not external_product_id:

            html = (
                response.text
                or ""
            )

            html_patterns = [
                r'"item_id"\s*:\s*"?(MLB\d+)"?',
                r'"itemId"\s*:\s*"?(MLB\d+)"?',
                r'"id"\s*:\s*"(MLB\d{8,})"',
                r'wid=(MLB\d+)',
                r'item_id(?:%3A|:|=)(MLB\d+)'
            ]

            for pattern in html_patterns:

                match = re.search(
                    pattern,
                    html,
                    flags=re.IGNORECASE
                )

                if match:

                    external_product_id = (
                        match
                        .group(1)
                        .upper()
                    )

                    break

        if not external_product_id:

            return jsonify({
                "message": (
                    "O Mercado Livre abriu o produto, "
                    "mas não foi possível identificar "
                    "o código MLB do anúncio."
                ),
                "final_url":
                    final_url
            }), 422

        return jsonify({
            "success": True,
            "external_product_id":
                external_product_id,
            "final_url":
                final_url
        })

    except requests.RequestException as error:

        print(
            "ERRO RESOLVER LINK MERCADO LIVRE:",
            repr(error),
            flush=True
        )

        return jsonify({
            "message":
                "Não foi possível consultar o link do Mercado Livre."
        }), 502

    except Exception as error:

        print(
            "ERRO DETECTAR PRODUTO MERCADO LIVRE:",
            repr(error),
            flush=True
        )

        return jsonify({
            "message":
                "Erro ao identificar o produto do Mercado Livre."
        }), 500
        
@app.route(
    "/admin/ofertas/lojas",
    methods=["POST"]
)
@admin_required_page
def admin_create_affiliate_store():

    try:

        data = (
            request.get_json(
                silent=True
            )
            or {}
        )

        name = str(
            data.get("name")
            or ""
        ).strip()

        logo_url = str(
            data.get("logo_url")
            or ""
        ).strip()

        affiliate_url = str(
            data.get("affiliate_url")
            or ""
        ).strip()

        display_order_raw = (
            data.get("display_order")
            or 0
        )

        if not name:

            return jsonify({
                "message":
                    "Informe o nome da loja."
            }), 400

        if not affiliate_url:

            return jsonify({
                "message":
                    "Informe o link de afiliado da loja."
            }), 400

        try:
            display_order = int(
                display_order_raw
            )

        except (
            TypeError,
            ValueError
        ):

            display_order = 0

        affiliate_store = AffiliateStore(
            name=name,
            logo_url=logo_url or None,
            affiliate_url=affiliate_url,
            is_active=True,
            display_order=display_order,
            click_count=0
        )

        db.session.add(
            affiliate_store
        )

        db.session.commit()

        return jsonify({
            "message":
                "Loja de afiliado cadastrada com sucesso.",

            "store_id":
                affiliate_store.id
        }), 201

    except Exception as error:

        db.session.rollback()

        print(
            "ERRO CADASTRAR LOJA DE AFILIADO:",
            repr(error),
            flush=True
        )

        return jsonify({
            "message":
                "Não foi possível cadastrar a loja."
        }), 500    

@app.route(
    "/admin/ofertas/lojas/<int:store_id>",
    methods=["PUT"]
)
@admin_required_page
def admin_update_affiliate_store(store_id):

    affiliate_store = db.session.get(
        AffiliateStore,
        store_id
    )

    if not affiliate_store:
        return jsonify({
            "message": "Loja de afiliado não encontrada."
        }), 404

    try:

        data = (
            request.get_json(
                silent=True
            )
            or {}
        )

        name = str(
            data.get("name")
            or ""
        ).strip()

        logo_url = str(
            data.get("logo_url")
            or ""
        ).strip()

        affiliate_url = str(
            data.get("affiliate_url")
            or ""
        ).strip()

        display_order_raw = (
            data.get("display_order")
            or 0
        )

        if not name:

            return jsonify({
                "message":
                    "Informe o nome da loja."
            }), 400

        if not affiliate_url:

            return jsonify({
                "message":
                    "Informe o link de afiliado da loja."
            }), 400

        try:

            display_order = int(
                display_order_raw
            )

        except (
            TypeError,
            ValueError
        ):

            display_order = 0

        affiliate_store.name = name
        affiliate_store.logo_url = (
            logo_url or None
        )
        affiliate_store.affiliate_url = (
            affiliate_url
        )
        affiliate_store.display_order = (
            display_order
        )

        db.session.commit()

        return jsonify({
            "message":
                "Loja atualizada com sucesso."
        })

    except Exception as error:

        db.session.rollback()

        print(
            "ERRO ATUALIZAR LOJA DE AFILIADO:",
            repr(error),
            flush=True
        )

        return jsonify({
            "message":
                "Não foi possível atualizar a loja."
        }), 500


@app.route(
    "/admin/ofertas/lojas/<int:store_id>/toggle-status",
    methods=["POST"]
)
@admin_required_page
def admin_toggle_affiliate_store_status(store_id):

    affiliate_store = db.session.get(
        AffiliateStore,
        store_id
    )

    if not affiliate_store:

        return jsonify({
            "message":
                "Loja de afiliado não encontrada."
        }), 404

    try:

        affiliate_store.is_active = not bool(
            affiliate_store.is_active
        )

        db.session.commit()

        return jsonify({
            "message": (
                "Loja ativada com sucesso."
                if affiliate_store.is_active
                else "Loja desativada com sucesso."
            ),
            "is_active":
                affiliate_store.is_active
        })

    except Exception as error:

        db.session.rollback()

        print(
            "ERRO ALTERAR STATUS DA LOJA:",
            repr(error),
            flush=True
        )

        return jsonify({
            "message":
                "Não foi possível alterar o status da loja."
        }), 500


@app.route(
    "/admin/ofertas/lojas/<int:store_id>",
    methods=["DELETE"]
)
@admin_required_page
def admin_delete_affiliate_store(store_id):

    affiliate_store = db.session.get(
        AffiliateStore,
        store_id
    )

    if not affiliate_store:

        return jsonify({
            "message":
                "Loja de afiliado não encontrada."
        }), 404

    try:

        db.session.delete(
            affiliate_store
        )

        db.session.commit()

        return jsonify({
            "message":
                "Loja excluída com sucesso."
        })

    except Exception as error:

        db.session.rollback()

        print(
            "ERRO EXCLUIR LOJA DE AFILIADO:",
            repr(error),
            flush=True
        )

        return jsonify({
            "message":
                "Não foi possível excluir a loja."
        }), 500        

@app.route("/admin/ofertas/nova")
@admin_required_page
def admin_new_offer_page():

    return render_template(
        "admin_offer_form.html",
        active_page="offers"
    )   

@app.route(
    "/admin/ofertas",
    methods=["POST"]
)
@admin_required_page
def admin_create_offer():

    try:

        data = (
            request.get_json(
                silent=True
            )
            or {}
        )

        title = str(
            data.get("title")
            or ""
        ).strip()

        store = str(
            data.get("store")
            or ""
        ).strip()

        category = str(
            data.get("category")
            or ""
        ).strip()

        description = str(
            data.get("description")
            or ""
        ).strip()

        image_url = str(
            data.get("image_url")
            or ""
        ).strip()

        affiliate_url = str(
            data.get("affiliate_url")
            or ""
        ).strip()
        
        store_code = str(
            data.get("store_code")
            or ""
        ).strip().upper()

        external_product_id = str(
            data.get("external_product_id")
            or ""
        ).strip().upper()

        old_price_raw = str(
            data.get("old_price")
            or ""
        ).strip()

        price_raw = str(
            data.get("price")
            or ""
        ).strip()

        expires_at_raw = str(
            data.get("expires_at")
            or ""
        ).strip()

        # -------------------------
        # VALIDAÇÕES
        # -------------------------

        if not title:

            return jsonify({
                "message":
                    "Informe o nome do produto."
            }), 400

        if not affiliate_url:

            return jsonify({
                "message":
                    "Informe o link de afiliado."
            }), 400
            
        if store_code == "MERCADO_LIVRE":

            if not external_product_id:

                return jsonify({
                    "message":
                        "Informe o código MLB do produto do Mercado Livre."
                }), 400

            if not re.fullmatch(
                r"MLB\d+",
                external_product_id
            ):

                return jsonify({
                    "message":
                        "Código Mercado Livre inválido. Use o formato MLB1234567890."
                }), 400    

        # -------------------------
        # CONVERSÃO DE PREÇO
        # -------------------------

        def parse_price(value):

            if not value:
                return None

            value = (
                value
                .replace("R$", "")
                .replace(" ", "")
                .strip()
            )

            if "." in value and "," in value:

                if value.rfind(",") > value.rfind("."):
                    # 1.990,90 -> 1990.90
                    value = (
                        value
                        .replace(".", "")
                        .replace(",", ".")
                    )
                else:
                    # 1,990.90 -> 1990.90
                    value = value.replace(",", "")

            elif "," in value:
                # 19,90 -> 19.90
                value = value.replace(",", ".")

            # Se houver somente ponto, mantém.
            # 19.90 -> 19.90

            try:
                return Decimal(value)

            except InvalidOperation:
                return None

        old_price = parse_price(
            old_price_raw
        )

        price = parse_price(
            price_raw
        )

        # -------------------------
        # VALIDADE
        # -------------------------

        expires_at = None

        if expires_at_raw:

            try:
                expires_at = datetime.strptime(
                    expires_at_raw,
                    "%Y-%m-%d"
                )

            except ValueError:

                return jsonify({
                    "message":
                        "Data de validade inválida."
                }), 400

        # -------------------------
        # CRIA OFERTA
        # -------------------------

        offer = AffiliateProduct(
            title=title,
            store=store or None,
            store_code=store_code or None,
            external_product_id=external_product_id or None,
            category=category or None,
            description=description or None,
            image_url=image_url or None,
            affiliate_url=affiliate_url,
            old_price=old_price,
            price=price,
            expires_at=expires_at,
            is_active=True,
            is_featured=False,
            click_count=0
        )

        db.session.add(
            offer
        )

        db.session.commit()

        return jsonify({
            "message":
                "Oferta cadastrada com sucesso.",

            "offer_id":
                offer.id
        }), 201

    except Exception as error:

        db.session.rollback()

        print(
            "ERRO CADASTRAR OFERTA:",
            repr(error),
            flush=True
        )

        return jsonify({
            "message":
                "Não foi possível cadastrar a oferta."
        }), 500    

@app.route("/passeios/<slug>")
def public_trip_page(slug):
    trip = TripEvent.query.filter_by(
        slug=slug,
        is_active=True
    ).first_or_404()

    registrations_open = True

    if (
        trip.registration_deadline
        and trip.registration_deadline < brasilia_now()
    ):
        registrations_open = False

    pix_payload = None
    pix_qr_base64 = None

    if (
        trip.pix_key
        and trip.pix_receiver_name
        and trip.pix_receiver_city
    ):
        try:
            pix_payload = build_pix_payload(
                pix_key=trip.pix_key,
                receiver_name=(
                    trip.pix_receiver_name
                ),
                receiver_city=(
                    trip.pix_receiver_city
                ),
                amount=trip.price
            )

            pix_qr_base64 = (
                generate_pix_qr_base64(
                    pix_payload
                )
            )

        except Exception as error:
            print(
                "Erro ao gerar PIX do passeio:",
                error,
                flush=True
            )

    return render_template(
        "trip_public.html",
        trip=trip,
        registrations_open=registrations_open,
        pix_payload=pix_payload,
        pix_qr_base64=pix_qr_base64
    )

@app.route(
    "/passeios/<slug>/inscrever",
    methods=["POST"]
)
def register_trip_student(slug):
    trip = TripEvent.query.filter_by(
        slug=slug,
        is_active=True
    ).first_or_404()

    if (
        trip.registration_deadline
        and trip.registration_deadline < brasilia_now()
    ):
        return jsonify({
            "message": "As inscrições para este passeio foram encerradas."
        }), 400

    default_required_fields = [
        "student_name",
        "guardian_name",
        "age",
        "platoon",
        "shift",
        "transport_route",
        "guardian_whatsapp"
    ]

    required_fields = (
        trip.required_fields
        if trip.required_fields is not None
        else default_required_fields
    )

    student_name = (
        request.form.get("student_name")
        or ""
    ).strip()

    guardian_name = (
        request.form.get("guardian_name")
        or ""
    ).strip()

    age_raw = (
        request.form.get("age")
        or ""
    ).strip()

    shift = (
        request.form.get("shift")
        or ""
    ).strip()
    
    transport_route = (
        request.form.get("transport_route")
        or ""
    ).strip()

    valid_transport_routes = {
        "P_SUL_POR_DO_SOL",
        "P_NORTE_SOL_NASCENTE",
        "SETOR_O_EXPANSAO",
        "MEIOS_PROPRIOS"
    }

    if "transport_route" in required_fields and not transport_route:
        return jsonify({
            "message": "Selecione uma rota de transporte."
        }), 400

    if transport_route and transport_route not in valid_transport_routes:
        return jsonify({
            "message": "Selecione uma rota de transporte válida."
        }), 400

    guardian_whatsapp = (
        request.form.get("guardian_whatsapp")
        or ""
    ).strip()

    receipt_file = request.files.get(
        "payment_receipt"
    )

    if "student_name" in required_fields and not student_name:
        return jsonify({
            "message": "Informe o nome do aluno."
        }), 400

    if "guardian_name" in required_fields and not guardian_name:
        return jsonify({
            "message": "Informe o nome do responsável."
        }), 400

    age = None
    platoon = None

    if age_raw:
        try:
            age = int(age_raw)
        except (TypeError, ValueError):
            return jsonify({
                "message": "Informe uma idade válida."
            }), 400

        platoon = get_platoon_by_age(age)

        if not platoon:
            return jsonify({
                "message": "A idade permitida é de 7 a 15 anos."
            }), 400

    elif (
        "age" in required_fields
        or "platoon" in required_fields
    ):
        return jsonify({
            "message": "Informe a idade do aluno para definir o pelotão."
        }), 400

    if "shift" in required_fields and not shift:
        return jsonify({
            "message": "Selecione o turno."
        }), 400

    if shift and shift not in ("MATUTINO", "VESPERTINO"):
        return jsonify({
            "message": "Selecione um turno válido."
        }), 400

    if "guardian_whatsapp" in required_fields and not guardian_whatsapp:
        return jsonify({
            "message": "Informe o WhatsApp do responsável."
        }), 400

    if (
        "payment_receipt" in required_fields
        and (
            not receipt_file
            or not receipt_file.filename
        )
    ):
        return jsonify({
            "message": "Envie o comprovante de pagamento."
        }), 400

    receipt_path = None

    if receipt_file and receipt_file.filename:

        (
            receipt_path,
            receipt_error,
            receipt_status
        ) = save_trip_receipt(
            receipt_file,
            trip.id
        )

        if receipt_error:

            return jsonify({
                "message": receipt_error
            }), receipt_status

    registration = TripRegistration(
        trip_id=trip.id,
        student_name=student_name or None,
        guardian_name=guardian_name or None,
        age=age,
        platoon=platoon,
        shift=shift or None,
        transport_route=transport_route or None,
        guardian_whatsapp=guardian_whatsapp or None,
        payment_receipt=receipt_path,
        payment_status="PENDENTE",
        registration_status="AGUARDANDO_PAGAMENTO"
    )

    db.session.add(registration)
    db.session.commit()

    return jsonify({
        "message": "Inscrição realizada com sucesso.",
        "registration_id": registration.id,
        "platoon": registration.platoon
    }), 201

@app.route(
    "/media/trip-receipts/<path:filename>"
)
@admin_required_page
def serve_trip_receipt(filename):
    receipt_folder = os.path.join(
        UPLOAD_BASE,
        "trip_receipts"
    )

    return send_from_directory(
        receipt_folder,
        filename,
        conditional=True
    )    
    
@app.route("/admin/passeios/<int:trip_id>")
@admin_required_page
def admin_trip_details(trip_id):
    trip = TripEvent.query.get_or_404(trip_id)

    platoon = (
        request.args.get("platoon")
        or ""
    ).strip()

    shift = (
        request.args.get("shift")
        or ""
    ).strip()

    payment_status = (
        request.args.get("payment_status")
        or ""
    ).strip()

    query = (
        TripRegistration.query
        .filter_by(
            trip_id=trip.id
        )
    )

    if platoon:
        query = query.filter(
            TripRegistration.platoon == platoon
        )

    if shift:
        query = query.filter(
            TripRegistration.shift == shift
        )

    if payment_status:
        query = query.filter(
            TripRegistration.payment_status == payment_status
        )

    registrations = (
        query
        .order_by(
            TripRegistration.created_at.desc()
        )
        .all()
    )

    all_registrations = (
        TripRegistration.query
        .filter_by(
            trip_id=trip.id
        )
        .all()
    )

    total = len(all_registrations)

    cancelled = sum(
        1
        for item in all_registrations
        if item.registration_status == "CANCELADA"
    )

    active = sum(
        1
        for item in all_registrations
        if item.registration_status != "CANCELADA"
    )

    paid = sum(
        1
        for item in all_registrations
        if (
            item.registration_status != "CANCELADA"
            and item.payment_status == "PAGO"
        )
    )

    pending = sum(
        1
        for item in all_registrations
        if (
            item.registration_status != "CANCELADA"
            and item.payment_status == "PENDENTE"
        )
    )

    trip_price = float(
        trip.price or 0
    )

    total_received = (
        paid * trip_price
    )

    total_pending = (
        pending * trip_price
    )

    return render_template(
        "admin_trip_details.html",
        trip=trip,
        registrations=registrations,
        total=total,
        active=active,
        paid=paid,
        pending=pending,
        cancelled=cancelled,
        total_received=total_received,
        total_pending=total_pending,
        selected_platoon=platoon,
        selected_shift=shift,
        selected_payment_status=payment_status
    )
    
@app.route("/admin/passeios/<int:trip_id>/exportar-excel")
@admin_required_page
def admin_export_trip_excel(trip_id):
    trip = TripEvent.query.get_or_404(trip_id)

    platoon = (
        request.args.get("platoon")
        or ""
    ).strip()

    shift = (
        request.args.get("shift")
        or ""
    ).strip()

    payment_status = (
        request.args.get("payment_status")
        or ""
    ).strip()

    query = (
        TripRegistration.query
        .filter_by(
            trip_id=trip.id
        )
    )

    if platoon:
        query = query.filter(
            TripRegistration.platoon == platoon
        )

    if shift:
        query = query.filter(
            TripRegistration.shift == shift
        )

    if payment_status:
        query = query.filter(
            TripRegistration.payment_status
            == payment_status
        )

    registrations = (
        query
        .order_by(
            TripRegistration.platoon.asc(),
            TripRegistration.shift.asc(),
            TripRegistration.student_name.asc()
        )
        .all()
    )

    workbook = Workbook()

    worksheet = workbook.active
    worksheet.title = "Inscritos"

    headers = [
        "Aluno",
        "Responsável",
        "Idade",
        "Pelotão",
        "Turno",
        "Rota de transporte",
        "WhatsApp",
        "Pagamento",
        "Situação da Inscrição",
        "Data da Inscrição"
    ]

    worksheet.append(headers)

    for cell in worksheet[1]:
        cell.font = Font(
            bold=True,
            color="FFFFFF"
        )

        cell.fill = PatternFill(
            fill_type="solid",
            fgColor="1D4ED8"
        )

        cell.alignment = Alignment(
            horizontal="center",
            vertical="center"
        )

    for item in registrations:
        if item.shift == "MATUTINO":
            shift_label = "Matutino"
        else:
            shift_label = "Vespertino"
            
        transport_route_labels = {
            "P_SUL_POR_DO_SOL": "P Sul / Pôr do Sol",
            "P_NORTE_SOL_NASCENTE": "P Norte / Sol Nascente",
            "SETOR_O_EXPANSAO": "Setor O / Expansão",
            "MEIOS_PROPRIOS": "Meios Próprios"
        }

        transport_route_label = transport_route_labels.get(
            item.transport_route,
            "Não informada"
        )    

        if item.payment_status == "PAGO":
            payment_label = "Pago"
        else:
            payment_label = "Pendente"

        if item.registration_status == "CANCELADA":
            registration_label = "Cancelada"

        elif item.registration_status == "CONFIRMADA":
            registration_label = "Confirmada"

        else:
            registration_label = "Aguardando pagamento"

        created_at = ""

        if item.created_at:
            created_at = (
                item.created_at.strftime(
                    "%d/%m/%Y %H:%M"
                )
            )

        worksheet.append([
            item.student_name,
            item.guardian_name,
            item.age,
            item.platoon,
            shift_label,
            transport_route_label,
            item.guardian_whatsapp,
            payment_label,
            registration_label,
            created_at
        ])

    column_widths = {
        "A": 28,
        "B": 28,
        "C": 10,
        "D": 18,
        "E": 15,
        "F": 28,
        "G": 20,
        "H": 15,
        "I": 24,
        "J": 20
    }

    for column, width in column_widths.items():
        worksheet.column_dimensions[
            column
        ].width = width

    worksheet.freeze_panes = "A2"

    output = io.BytesIO()

    workbook.save(output)

    output.seek(0)

    safe_title = generate_slug(
        trip.title
    )

    filename = (
        f"inscritos-{safe_title}.xlsx"
    )

    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype=(
            "application/vnd.openxmlformats-"
            "officedocument.spreadsheetml.sheet"
        )
    )    

@app.route(
    "/admin/passeios/inscricoes/<int:registration_id>/pagamento",
    methods=["PATCH"]
)
@admin_required_page
def admin_update_trip_payment(registration_id):
    registration = (
        TripRegistration.query
        .get_or_404(registration_id)
    )

    data = request.get_json(
        silent=True
    ) or {}

    status = (
        data.get("status")
        or ""
    ).strip().upper()

    if status not in (
        "PAGO",
        "PENDENTE"
    ):
        return jsonify({
            "message": "Status de pagamento inválido."
        }), 400

    registration.payment_status = status

    if status == "PAGO":
        registration.registration_status = (
            "CONFIRMADA"
        )
    else:
        registration.registration_status = (
            "AGUARDANDO_PAGAMENTO"
        )

    db.session.commit()

    return jsonify({
        "message": "Pagamento atualizado com sucesso.",
        "payment_status": (
            registration.payment_status
        ),
        "registration_status": (
            registration.registration_status
        )
    }) 
    
@app.route(
    "/admin/passeios/inscricoes/<int:registration_id>/excluir",
    methods=["DELETE"]
)
@admin_required_page
def admin_delete_trip_registration(registration_id):

    registration = (
        TripRegistration.query
        .get_or_404(registration_id)
    )

    student_name = registration.student_name

    db.session.delete(registration)
    db.session.commit()

    return jsonify({
        "message": (
            f"Inscrição de {student_name} "
            "excluída definitivamente."
        )
    }), 200    

@app.route(
    "/admin/passeios/inscricoes/<int:registration_id>/cancelar",
    methods=["PATCH"]
)
@admin_required_page
def admin_cancel_trip_registration(registration_id):
    registration = (
        TripRegistration.query
        .get_or_404(registration_id)
    )

    registration.registration_status = "CANCELADA"

    db.session.commit()

    return jsonify({
        "message": "Inscrição cancelada com sucesso."
    })  

@app.route(
    "/admin/passeios/inscricoes/<int:registration_id>/descancelar",
    methods=["PATCH"]
)
@admin_required_page
def admin_uncancel_trip_registration(registration_id):
    registration = (
        TripRegistration.query
        .get_or_404(registration_id)
    )

    if registration.payment_status == "PAGO":
        registration.registration_status = "CONFIRMADA"
    else:
        registration.registration_status = "AGUARDANDO_PAGAMENTO"

    db.session.commit()

    return jsonify({
        "message": "Inscrição reativada com sucesso.",
        "registration_status": registration.registration_status
    })   

@app.route(
    "/admin/passeios/inscricoes/<int:registration_id>/editar",
    methods=["PATCH"]
)
@admin_required_page
def admin_edit_trip_registration(registration_id):
    registration = (
        TripRegistration.query
        .get_or_404(registration_id)
    )

    data = request.get_json(
        silent=True
    ) or {}

    student_name = (
        data.get("student_name")
        or ""
    ).strip()

    guardian_name = (
        data.get("guardian_name")
        or ""
    ).strip()

    guardian_whatsapp = (
        data.get("guardian_whatsapp")
        or ""
    ).strip()

    shift = (
        data.get("shift")
        or ""
    ).strip().upper()

    try:
        age = int(
            data.get("age")
        )
    except (TypeError, ValueError):
        return jsonify({
            "message": "Informe uma idade válida."
        }), 400

    if not student_name:
        return jsonify({
            "message": "Informe o nome do aluno."
        }), 400

    if not guardian_name:
        return jsonify({
            "message": "Informe o nome do responsável."
        }), 400

    if not guardian_whatsapp:
        return jsonify({
            "message": "Informe o WhatsApp do responsável."
        }), 400

    if shift not in (
        "MATUTINO",
        "VESPERTINO"
    ):
        return jsonify({
            "message": "Turno inválido."
        }), 400

    platoon = get_platoon_by_age(
        age
    )

    if not platoon:
        return jsonify({
            "message": (
                "A idade permitida é de "
                "7 a 15 anos."
            )
        }), 400

    registration.student_name = (
        student_name
    )

    registration.guardian_name = (
        guardian_name
    )

    registration.age = age

    registration.platoon = platoon

    registration.shift = shift

    registration.guardian_whatsapp = (
        guardian_whatsapp
    )

    db.session.commit()

    return jsonify({
        "message": "Inscrição atualizada com sucesso.",
        "platoon": platoon
    })  

@app.route(
    "/admin/passeios/inscricoes/"
    "<int:registration_id>/comprovante",
    methods=["POST"]
)
@admin_required_page
def admin_upload_trip_receipt(
    registration_id
):

    registration = (
        TripRegistration.query
        .get_or_404(registration_id)
    )

    receipt_file = request.files.get(
        "payment_receipt"
    )


    # =========================
    # VALIDAR / SALVAR
    # =========================

    (
        receipt_path,
        receipt_error,
        receipt_status
    ) = save_trip_receipt(
        receipt_file,
        registration.trip_id
    )


    if receipt_error:

        return jsonify({
            "message": receipt_error
        }), receipt_status


    # =========================
    # ATUALIZAR INSCRIÇÃO
    # =========================

    registration.payment_receipt = (
        receipt_path
    )


    try:

        db.session.commit()

    except Exception as error:

        db.session.rollback()

        print(
            "ERRO AO ATUALIZAR "
            "COMPROVANTE DA INSCRIÇÃO:",
            repr(error),
            flush=True
        )

        return jsonify({
            "message": (
                "O comprovante foi enviado, "
                "mas não foi possível atualizar "
                "a inscrição."
            )
        }), 500


    return jsonify({
        "message": (
            "Comprovante salvo com sucesso."
        ),
        "payment_receipt": receipt_path
    }), 200    

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


def build_item_response(item_id):
    item = Ad.query.get(item_id)

    if not item or not item.is_active:
        return jsonify({
            "message": "Conteúdo não encontrado"
        }), 404

    current_user = None

    if session.get("user_id"):
        current_user = User.query.get(
            session["user_id"]
        )

    if not get_plan_rules(
        item.plan
    )["can_show_full_details"]:
        if not current_user or not current_user.is_admin:
            return jsonify({
                "message": (
                    "Detalhes disponíveis apenas para "
                    "planos compatíveis"
                )
            }), 403

    return jsonify(serialize_ad(item))


@app.route("/item/<int:item_id>", methods=["GET"])
def get_item(item_id):
    return build_item_response(item_id)


@app.route("/anuncio/<path:slug>")
def public_ad_page(slug):
    item = Ad.query.filter_by(
        slug=slug
    ).first()

    if not item or not item.is_active:
        return "Conteúdo não encontrado", 404

    current_user = None

    if session.get("user_id"):
        current_user = User.query.get(
            session["user_id"]
        )

    if not get_plan_rules(
        item.plan
    )["can_show_full_details"]:
        if (
            not current_user
            or not current_user.is_admin
        ):
            return (
                "Detalhes disponíveis apenas para "
                "planos compatíveis"
            ), 403

    origin = request.args.get(
        "from",
        "search"
    )

    canonical_url = url_for(
        "public_ad_page",
        slug=item.slug,
        _external=True
    )

    seo_title = f"{item.title} em {item.city} | CataLogin"

    description_text = (
        item.description or
        f"Encontre {item.title} em {item.city}. "
        f"Veja contato, localização e mais informações no CataLogin."
    )

    description_text = " ".join(description_text.split())

    if len(description_text) > 155:
        description_text = description_text[:152].rstrip() + "..."

    seo_image = None

    if item.main_image:
        if item.main_image.startswith(
            ("http://", "https://")
        ):
            seo_image = item.main_image
        else:
            seo_image = (
                f"{BASE_URL.rstrip('/')}/"
                f"{item.main_image.lstrip('/')}"
            )


    return render_template(
        "ad_details.html",
        ad_id=item.id,
        origin=origin,
        ad=serialize_ad(item),

        seo_title=seo_title,
        seo_description=description_text,
        canonical_url=canonical_url,
        seo_image=seo_image,

        schema_name=item.title,
        schema_phone=item.phone,
        schema_country=item.country or "Brasil",
        schema_state=item.state,
        schema_city=item.city,
        schema_neighborhood=item.neighborhood,
        schema_street=item.street,
        schema_number=item.number,
        schema_zipcode=item.zipcode,
        schema_latitude=item.latitude,
        schema_longitude=item.longitude
    )

@app.route("/item/<int:item_id>/view")
def item_details_page(item_id):
    item = Ad.query.get(item_id)

    if not item or not item.is_active:
        return "Conteúdo não encontrado", 404

    if not item.slug:
        return "URL do anúncio não disponível", 404

    origin = request.args.get(
        "from",
        "search"
    )

    return redirect(
        url_for(
            "public_ad_page",
            slug=item.slug,
            **{
                "from": origin
            }
        ),
        code=301
    )
    
    
@app.route("/ads/<int:ad_id>", methods=["GET"])
def get_ad(ad_id):
    return build_item_response(ad_id)


@app.route("/anuncios/<int:ad_id>", methods=["GET"])
def get_anuncio(ad_id):
    return build_item_response(ad_id)


@app.route("/ads/<int:ad_id>/page")
def ad_details_page(ad_id):
    return redirect(
        url_for(
            "item_details_page",
            item_id=ad_id,
            **request.args
        ),
        code=302
    )


@app.route("/anuncios/<int:ad_id>/page")
def anuncio_details_page(ad_id):
    return redirect(
        url_for(
            "item_details_page",
            item_id=ad_id,
            **request.args
        ),
        code=302
    )
    
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
    latitude_raw = request.form.get("latitude", "").strip()
    longitude_raw = request.form.get("longitude", "").strip()
    show_on_home_requested = (
        request.form.get(
            "show_on_home",
            ""
        ).strip().lower()
        in ("1", "true", "yes", "on")
    )
    latitude = None
    longitude = None

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
        
    show_on_home = bool(
        user.is_admin
        and show_on_home_requested
    )    
    
    enforce_user_plan(user)

    if user.is_admin:
        plan_rules = {
            "ads_limit": 999999,
            "keywords_limit": 999999,
            "can_use_images": True,
            "can_use_videos": True,
            "can_appear_in_vip_list": False,
            "can_show_full_details": True,
            "can_use_vitrine": True,
            "can_use_location": True
        }
    else:
        plan_rules = get_plan_rules(user.plan)
    
    if plan_rules.get("can_use_location"):
        try:
            if latitude_raw and longitude_raw:
                latitude = float(latitude_raw)
                longitude = float(longitude_raw)
        except ValueError:
            return jsonify({"message": "Localização inválida."}), 400

    if (main_image_file and not plan_rules["can_use_images"]) or (main_video_file and not plan_rules["can_use_videos"]):
        return jsonify({
            "message": "Seu plano atual não permite usar imagem e/ou vídeo neste anúncio.",
            "upgrade": True
        }), 403

    if not user.is_admin:
        max_ads = plan_rules["ads_limit"]
        current_ads_count = Ad.query.filter_by(user_id=user.id).count()

        if current_ads_count >= max_ads:
            if user.plan == "FREE":
                return jsonify({
                    "message": "Torne-se VIP para anunciar mais produtos ou serviços",
                    "upgrade": True
                }), 400

            return jsonify({
                "message": f"Você atingiu o limite de {max_ads} anúncios do seu plano"
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
        image_path = f"/media/images/{image_filename}"

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

        video_path = f"/media/videos/{video_filename}"    

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
        latitude=latitude,
        longitude=longitude,
        plan="ADMIN" if user.is_admin else user.plan,
        main_image=image_path if plan_rules["can_use_images"] else None,
        main_video=video_path if plan_rules["can_use_videos"] else None,
        is_active=True,
        show_on_home=show_on_home
    )

    db.session.add(ad)
    db.session.flush()

    ad.slug = build_ad_slug(ad)

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
    
@app.route(
    "/vitrine-ads",
    methods=["GET"]
)
def vitrine_ads():
    state = request.args.get(
        "state",
        ""
    ).strip()

    city = request.args.get(
        "city",
        ""
    ).strip()

    neighborhood = request.args.get(
        "neighborhood",
        ""
    ).strip()

    try:
        page = max(
            int(
                request.args.get(
                    "page",
                    1
                )
            ),
            1
        )
    except (TypeError, ValueError):
        page = 1

    per_page = 24

    allowed_plans = [
        plan
        for plan in [
            "ADMIN",
            "FREE",
            "VIP_BRONZE",
            "VIP_PRATA",
            "VIP_OURO",
            "VIP_PREMIUM"
        ]
        if get_plan_rules(
            plan
        )["can_use_vitrine"]
    ]

    query = (
        db.session.query(
            Ad.id,
            Ad.title,
            Ad.phone,
            Ad.city,
            Ad.neighborhood,
            Ad.street,
            Ad.main_image,
            Ad.plan,
            Ad.created_at
        )
        .join(
            User,
            Ad.user_id == User.id
        )
        .filter(
            Ad.is_active.is_(True),
            Ad.main_image.isnot(None),
            Ad.plan.in_(allowed_plans),
            or_(
                Ad.blocked_until.is_(None),
                Ad.blocked_until
                <= utc_now()
            ),
            or_(
                User.blocked_until.is_(None),
                User.blocked_until
                <= utc_now()
            )
        )
    )

    if state:
        query = query.filter(
            Ad.state == state
        )

    if city:
        query = query.filter(
            Ad.city == city
        )

    if neighborhood:
        query = query.filter(
            Ad.neighborhood
            == neighborhood
        )

    rows = (
        query
        .order_by(
            plan_priority_case(),
            Ad.created_at.desc()
        )
        .offset(
            (page - 1) * per_page
        )
        .limit(
            per_page + 1
        )
        .all()
    )

    has_more = len(rows) > per_page

    rows = rows[:per_page]

    items = []

    for row in rows:
        thumbnail_url = (
            get_vitrine_thumbnail_url(
                row.main_image
            )
        )

        items.append({
            "id": row.id,
            "title": row.title,
            "phone": row.phone,
            "city": row.city,
            "neighborhood": (
                row.neighborhood
            ),
            "street": row.street,
            "plan": row.plan,
            "main_image": (
                row.main_image
            ),
            "vitrine_image": (
                thumbnail_url
            )
        })

    response = jsonify({
        "items": items,
        "page": page,
        "has_more": has_more
    })

    response.headers["Cache-Control"] = (
        "public, max-age=60"
    )

    return response

@app.route("/my-ads/<int:user_id>", methods=["GET"])
def get_my_ads(user_id):
    if not session.get("user_id"):
        return jsonify({
            "message": "Faça login para ver seus anúncios."
        }), 401

    if int(user_id) != int(session["user_id"]):
        return jsonify({
            "message": "Acesso negado."
        }), 403

    user = db.session.get(User, user_id)

    if not user:
        return jsonify({
            "message": "Usuário não encontrado."
        }), 404

    ads = (
        Ad.query
        .filter_by(user_id=user_id)
        .order_by(Ad.created_at.desc())
        .all()
    )

    return jsonify([
        serialize_ad(ad)
        for ad in ads
    ])


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
        "support_whatsapp": (
            settings.support_whatsapp or ""
        ),
        "instagram_url": (
            settings.instagram_url or ""
        )
    }), 200
    
@app.route("/manifest.webmanifest")
def manifest():
    return send_from_directory("static", "manifest.webmanifest", mimetype="application/manifest+json")

@app.route("/service-worker.js")
def service_worker():
    service_worker_path = os.path.join(
        app.static_folder,
        "service-worker.js"
    )

    with open(service_worker_path, "r", encoding="utf-8") as file:
        service_worker_code = file.read()

    version_code = (
        f'self.APP_VERSION = '
        f'{json.dumps(app.config["APP_VERSION"])};\n'
    )

    response = Response(
        version_code + service_worker_code,
        mimetype="application/javascript"
    )

    response.headers["Cache-Control"] = (
        "no-cache, no-store, must-revalidate"
    )
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Service-Worker-Allowed"] = "/"

    return response  
    
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
        "instagram_url": settings.instagram_url or "",

        "promotions": {
            "new_user_vip_enabled": (
                settings.new_user_vip_promotion_enabled
            ),
            "new_user_vip_plan": (
                settings.new_user_vip_promotion_plan
            ),
            "new_user_vip_days": (
                settings.new_user_vip_promotion_days
            )
        },
        
        "free": {
            "ads_limit": settings.free_ads_limit,
            "keywords_limit": settings.free_keywords_limit,
            "can_use_images": settings.free_can_use_images,
            "can_use_videos": settings.free_can_use_videos,
            "can_appear_in_vip_list": settings.free_can_appear_in_vip_list,
            "can_show_full_details": settings.free_can_show_full_details,
            "can_use_vitrine": settings.free_can_use_vitrine,
            "can_use_location": settings.free_can_use_location
        },
        "bronze": {
            "ads_limit": settings.bronze_ads_limit,
            "keywords_limit": settings.bronze_keywords_limit,
            "price": settings.bronze_price,
            "can_use_images": settings.bronze_can_use_images,
            "can_use_videos": settings.bronze_can_use_videos,
            "can_appear_in_vip_list": settings.bronze_can_appear_in_vip_list,
            "can_show_full_details": settings.bronze_can_show_full_details,
            "can_use_vitrine": settings.free_can_use_vitrine,
            "can_use_location": settings.free_can_use_location
        },
        "prata": {
            "ads_limit": settings.prata_ads_limit,
            "keywords_limit": settings.prata_keywords_limit,
            "price": settings.prata_price,
            "can_use_images": settings.prata_can_use_images,
            "can_use_videos": settings.prata_can_use_videos,
            "can_appear_in_vip_list": settings.prata_can_appear_in_vip_list,
            "can_show_full_details": settings.prata_can_show_full_details,
            "can_use_vitrine": settings.free_can_use_vitrine,
            "can_use_location": settings.free_can_use_location
        },
        "ouro": {
            "ads_limit": settings.ouro_ads_limit,
            "keywords_limit": settings.ouro_keywords_limit,
            "price": settings.ouro_price,
            "can_use_images": settings.ouro_can_use_images,
            "can_use_videos": settings.ouro_can_use_videos,
            "can_appear_in_vip_list": settings.ouro_can_appear_in_vip_list,
            "can_show_full_details": settings.ouro_can_show_full_details,
            "can_use_vitrine": settings.free_can_use_vitrine,
            "can_use_location": settings.free_can_use_location
        },
        "premium": {
            "ads_limit": settings.premium_ads_limit,
            "keywords_limit": settings.premium_keywords_limit,
            "price": settings.premium_price,
            "can_use_images": settings.premium_can_use_images,
            "can_use_videos": settings.premium_can_use_videos,
            "can_appear_in_vip_list": settings.premium_can_appear_in_vip_list,
            "can_show_full_details": settings.premium_can_show_full_details,
            "can_use_vitrine": settings.free_can_use_vitrine,
            "can_use_location": settings.free_can_use_location
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
        settings.support_whatsapp = (
            data.get("support_whatsapp") or ""
        ).strip()

        settings.instagram_url = (
            data.get("instagram_url") or ""
        ).strip()

        settings.free_ads_limit = int(
            data["free"]["ads_limit"]
        )
        settings.free_keywords_limit = int(data["free"]["keywords_limit"])
        settings.free_can_use_images = bool(data["free"]["can_use_images"])
        settings.free_can_use_videos = bool(data["free"]["can_use_videos"])
        settings.free_can_appear_in_vip_list = bool(data["free"]["can_appear_in_vip_list"])
        settings.free_can_show_full_details = bool(data["free"]["can_show_full_details"])
        settings.free_can_use_vitrine = bool(data["free"]["can_use_vitrine"])
        settings.free_can_use_location = bool(data["free"]["can_use_location"])

        settings.bronze_ads_limit = int(data["bronze"]["ads_limit"])
        settings.bronze_keywords_limit = int(data["bronze"]["keywords_limit"])
        settings.bronze_can_use_images = bool(data["bronze"]["can_use_images"])
        settings.bronze_can_use_videos = bool(data["bronze"]["can_use_videos"])
        settings.bronze_can_appear_in_vip_list = bool(data["bronze"]["can_appear_in_vip_list"])
        settings.bronze_can_show_full_details = bool(data["bronze"]["can_show_full_details"])
        settings.bronze_price = float(data["bronze"]["price"])
        settings.bronze_can_use_vitrine = bool(data["bronze"]["can_use_vitrine"])
        settings.bronze_can_use_location = bool(data["bronze"]["can_use_location"])

        settings.prata_ads_limit = int(data["prata"]["ads_limit"])
        settings.prata_keywords_limit = int(data["prata"]["keywords_limit"])
        settings.prata_can_use_images = bool(data["prata"]["can_use_images"])
        settings.prata_can_use_videos = bool(data["prata"]["can_use_videos"])
        settings.prata_can_appear_in_vip_list = bool(data["prata"]["can_appear_in_vip_list"])
        settings.prata_can_show_full_details = bool(data["prata"]["can_show_full_details"])
        settings.prata_price = float(data["prata"]["price"])
        settings.prata_can_use_vitrine = bool(data["prata"]["can_use_vitrine"])
        settings.prata_can_use_location = bool(data["prata"]["can_use_location"])

        settings.ouro_ads_limit = int(data["ouro"]["ads_limit"])
        settings.ouro_keywords_limit = int(data["ouro"]["keywords_limit"])
        settings.ouro_can_use_images = bool(data["ouro"]["can_use_images"])
        settings.ouro_can_use_videos = bool(data["ouro"]["can_use_videos"])
        settings.ouro_can_appear_in_vip_list = bool(data["ouro"]["can_appear_in_vip_list"])
        settings.ouro_can_show_full_details = bool(data["ouro"]["can_show_full_details"])
        settings.ouro_price = float(data["ouro"]["price"])
        settings.ouro_can_use_vitrine = bool(data["ouro"]["can_use_vitrine"])
        settings.ouro_can_use_location = bool(data["ouro"]["can_use_location"])

        settings.premium_ads_limit = int(data["premium"]["ads_limit"])
        settings.premium_keywords_limit = int(data["premium"]["keywords_limit"])
        settings.premium_can_use_images = bool(data["premium"]["can_use_images"])
        settings.premium_can_use_videos = bool(data["premium"]["can_use_videos"])
        settings.premium_can_appear_in_vip_list = bool(data["premium"]["can_appear_in_vip_list"])
        settings.premium_can_show_full_details = bool(data["premium"]["can_show_full_details"])
        settings.premium_price = float(data["premium"]["price"])
        settings.premium_can_use_vitrine = bool(data["premium"]["can_use_vitrine"])
        settings.premium_can_use_location = bool(data["premium"]["can_use_location"])
        
        promotions = data.get("promotions") or {}

        promotion_enabled = bool(
            promotions.get(
                "new_user_vip_enabled",
                False
            )
        )

        promotion_plan = (
            promotions.get(
                "new_user_vip_plan",
                "VIP_BRONZE"
            )
            or "VIP_BRONZE"
        ).strip().upper()

        promotion_days = int(
            promotions.get(
                "new_user_vip_days",
                30
            )
        )

        allowed_promotion_plans = [
            "VIP_BRONZE",
            "VIP_PRATA",
            "VIP_OURO",
            "VIP_PREMIUM"
        ]

        if promotion_plan not in allowed_promotion_plans:
            return jsonify({
                "message": "Plano da promoção inválido"
            }), 400

        if promotion_days < 1 or promotion_days > 365:
            return jsonify({
                "message": (
                    "A duração da promoção deve estar "
                    "entre 1 e 365 dias"
                )
            }), 400

        settings.new_user_vip_promotion_enabled = (
            promotion_enabled
        )

        settings.new_user_vip_promotion_plan = (
            promotion_plan
        )

        settings.new_user_vip_promotion_days = (
            promotion_days
        )
        
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
    
@app.route(
    "/admin/promotions/grant-vip-all",
    methods=["POST"]
)
def grant_vip_to_all_users():
    data = request.get_json() or {}

    admin_user_id = data.get("admin_user_id")
    plan = (
        data.get("plan")
        or "VIP_BRONZE"
    ).strip().upper()

    try:
        days = int(data.get("days") or 30)
    except (TypeError, ValueError):
        return jsonify({
            "message": "Quantidade de dias inválida"
        }), 400

    if not admin_user_id:
        return jsonify({
            "message": "Administrador não informado"
        }), 400

    admin_user = User.query.get(admin_user_id)

    if not admin_user or not admin_user.is_admin:
        return jsonify({
            "message": "Acesso negado"
        }), 403

    allowed_plans = [
        "VIP_BRONZE",
        "VIP_PRATA",
        "VIP_OURO",
        "VIP_PREMIUM"
    ]

    if plan not in allowed_plans:
        return jsonify({
            "message": "Plano VIP inválido"
        }), 400

    if days < 1 or days > 365:
        return jsonify({
            "message": (
                "A duração deve estar entre "
                "1 e 365 dias"
            )
        }), 400

    users = User.query.filter(
        User.is_admin.is_(False),
        User.plan != "ADMIN"
    ).all()

    updated_count = 0

    try:
        for user in users:
            granted = grant_promotional_vip(
                user=user,
                plan=plan,
                days=days
            )

            if granted:
                updated_count += 1

        db.session.commit()

        return jsonify({
            "message": (
                f"VIP concedido a "
                f"{updated_count} usuário(s)"
            ),
            "updated_users": updated_count,
            "plan": plan,
            "days": days
        })

    except Exception as error:
        db.session.rollback()

        print(
            "ERRO AO APLICAR PROMOÇÃO GERAL:",
            error
        )

        return jsonify({
            "message": (
                "Não foi possível aplicar "
                "a promoção"
            ),
            "error": str(error)
        }), 500    
    
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


@app.route(
    "/feed",
    methods=["GET"]
)
def get_feed():
    state = request.args.get(
        "state",
        ""
    ).strip()

    city = request.args.get(
        "city",
        ""
    ).strip()

    neighborhood = request.args.get(
        "neighborhood",
        ""
    ).strip()

    try:
        page = max(
            int(
                request.args.get(
                    "page",
                    1
                )
            ),
            1
        )
    except (TypeError, ValueError):
        page = 1

    per_page = 8

    query = (
        db.session.query(
            Ad.id,
            Ad.slug,
            Ad.title,
            Ad.main_image,
            Ad.main_video,
            Ad.plan,
            Ad.created_at
        )
        .join(
            User,
            Ad.user_id == User.id
        )
        .filter(
            Ad.is_active.is_(True),
            or_(
                Ad.main_image.isnot(None),
                Ad.main_video.isnot(None)
            ),
            or_(
                Ad.blocked_until.is_(None),
                Ad.blocked_until <= utc_now()
            ),
            or_(
                User.blocked_until.is_(None),
                User.blocked_until <= utc_now()
            )
        )
    )

    if state:
        query = query.filter(
            Ad.state == state
        )

    if city:
        query = query.filter(
            Ad.city == city
        )

    if neighborhood:
        query = query.filter(
            Ad.neighborhood == neighborhood
        )

    rows = (
        query
        .order_by(
            plan_priority_case(),
            Ad.created_at.desc()
        )
        .offset(
            (page - 1) * per_page
        )
        .limit(
            per_page + 1
        )
        .all()
    )

    has_more = len(rows) > per_page

    rows = rows[:per_page]

    feed_items = []

    for row in rows:
        plan_rules = get_plan_rules(
            row.plan
        )

        if not plan_rules.get(
            "can_use_vitrine",
            False
        ):
            continue

        if (
            plan_rules.get(
                "can_use_images",
                False
            )
            and row.main_image
        ):
            feed_items.append({
                "ad_id": row.id,
                "slug": row.slug,
                "title": row.title,
                "type": "image",
                "url": (
                    get_vitrine_thumbnail_url(
                        row.main_image
                    )
                ),
                "original_url": (
                    row.main_image
                ),
                "plan": row.plan,
                "created_at": (
                    row.created_at.isoformat()
                    if row.created_at
                    else None
                )
            })

        if (
            plan_rules.get(
                "can_use_videos",
                False
            )
            and row.main_video
        ):
            feed_items.append({
                "ad_id": row.id,
                "slug": row.slug,
                "title": row.title,
                "type": "video",
                "url": row.main_video,
                "plan": row.plan,
                "created_at": (
                    row.created_at.isoformat()
                    if row.created_at
                    else None
                )
            })

    response = jsonify({
        "items": feed_items,
        "page": page,
        "has_more": has_more
    })

    response.headers["Cache-Control"] = (
        "public, max-age=60"
    )

    return response


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

@app.route("/anuncios", methods=["GET"])
def list_anuncios():
    return get_ads()
    
@app.route("/ads/<int:ad_id>", methods=["DELETE"])
def delete_ad(ad_id):
    try:
        print(f"=== DELETE_AD INICIO | ad_id={ad_id} ===", flush=True)
        print("SESSION USER ID:", session.get("user_id"), flush=True)

        if not session.get("user_id"):
            return jsonify({"message": "Faça login para excluir o anúncio"}), 401

        user = User.query.get(session["user_id"])
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

    except Exception as e:
        import traceback
        db.session.rollback()
        print(f"=== EXCEPTION DELETE_AD | ad_id={ad_id} ===", flush=True)
        traceback.print_exc()
        return jsonify({
            "message": "Erro interno ao excluir anúncio",
            "error": str(e)
        }), 500


@app.route("/ads/<int:ad_id>", methods=["PUT"])
def update_ad(ad_id):
    try:
        print(f"=== UPDATE_AD INICIO | ad_id={ad_id} ===", flush=True)
        print("SESSION USER ID:", session.get("user_id"), flush=True)
        print("FORM UPDATE:", dict(request.form), flush=True)
        print("FILES UPDATE:", list(request.files.keys()), flush=True)

        if not session.get("user_id"):
            return jsonify({"message": "Faça login para editar o anúncio"}), 401

        user = User.query.get(session["user_id"])
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
        latitude_raw = request.form.get("latitude", "").strip()
        longitude_raw = request.form.get("longitude", "").strip()
        show_on_home_requested = (
            request.form.get(
                "show_on_home",
                ""
            ).strip().lower()
            in ("1", "true", "yes", "on")
        )
        latitude = None
        longitude = None
        keywords = request.form.getlist("keywords")

        main_image_file = request.files.get("main_image")
        main_video_file = request.files.get("main_video")

        enforce_user_plan(user)
        plan_rules = get_plan_rules(user.plan)
        
        if plan_rules.get("can_use_location"):
            try:
                if latitude_raw and longitude_raw:
                    latitude = float(latitude_raw)
                    longitude = float(longitude_raw)
            except ValueError:
                return jsonify({"message": "Localização inválida."}), 400

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
                        print(f"Erro ao remover imagem antiga: {e}", flush=True)

            image_ext = main_image_file.filename.rsplit(".", 1)[1].lower()
            image_filename = f"{uuid.uuid4().hex}.{image_ext}"
            image_full_path = os.path.join(UPLOAD_IMAGE_FOLDER, image_filename)
            main_image_file.save(image_full_path)

            ad.main_image = f"/media/images/{image_filename}"

        elif not plan_rules["can_use_images"]:
            ad.main_image = None

        if main_video_file and main_video_file.filename:
            if not allowed_file(main_video_file.filename, ALLOWED_VIDEO_EXTENSIONS):
                return jsonify({"message": "Formato de vídeo inválido."}), 400

            if ad.main_video:
                old_video_path = resolve_media_file_path(ad.main_video)
                if old_video_path and os.path.exists(old_video_path):
                    try:
                        os.remove(old_video_path)
                    except Exception as e:
                        print(f"Erro ao remover vídeo antigo: {e}", flush=True)

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

            ad.main_video = f"/media/videos/{video_filename}"

        elif not plan_rules["can_use_videos"]:
            ad.main_video = None

        ad.title = title
        ad.description = description
        ad.phone = phone
        ad.country = country
        ad.state = state
        ad.city = city
        ad.slug = build_ad_slug(ad)
        ad.municipality = city if state.upper() == "DF" else request.form.get("municipality", "").strip()
        ad.neighborhood = neighborhood
        ad.street = street
        ad.number = number
        ad.complement = complement
        ad.zipcode = zipcode
        if plan_rules.get("can_use_location"):
            ad.latitude = latitude
            ad.longitude = longitude
        else:
            ad.latitude = None
            ad.longitude = None
        ad.plan = user.plan
        if user.is_admin:
            ad.show_on_home = (
                show_on_home_requested
            )
        else:
            ad.show_on_home = False

        Keyword.query.filter_by(ad_id=ad.id).delete()

        for keyword in cleaned_keywords:
            db.session.add(Keyword(ad_id=ad.id, keyword=keyword))

        db.session.commit()

        return jsonify({
            "message": "Anúncio atualizado com sucesso",
            "ad": serialize_ad(ad)
        })

    except Exception as e:
        import traceback
        db.session.rollback()
        print(f"=== EXCEPTION UPDATE_AD | ad_id={ad_id} ===", flush=True)
        traceback.print_exc()
        return jsonify({
            "message": "Erro interno ao atualizar anúncio",
            "error": str(e)
        }), 500
        
@app.route("/anuncios/<int:ad_id>", methods=["PUT"])
def update_anuncio(ad_id):
    return update_ad(ad_id)

@app.route("/anuncios/<int:ad_id>", methods=["DELETE"])
def delete_anuncio(ad_id):
    return delete_ad(ad_id)        
    
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
    vip_expires_at_raw = (
        data.get("vip_expires_at") or ""
    ).strip()

    if not admin_user_id:
        return jsonify({
            "message": "Administrador não informado"
        }), 400

    admin_user = User.query.get(admin_user_id)

    if not admin_user or not admin_user.is_admin:
        return jsonify({
            "message": "Acesso negado"
        }), 403

    allowed_plans = [
        "FREE",
        "VIP_BRONZE",
        "VIP_PRATA",
        "VIP_OURO",
        "VIP_PREMIUM",
        "ADMIN"
    ]

    if new_plan not in allowed_plans:
        return jsonify({
            "message": "Tipo de usuário inválido"
        }), 400

    target_user = User.query.get(target_user_id)

    if not target_user:
        return jsonify({
            "message": "Usuário não encontrado"
        }), 404

    # Impede o administrador logado de retirar
    # acidentalmente a própria permissão.
    if (
        int(target_user.id) == int(admin_user.id)
        and new_plan != "ADMIN"
    ):
        return jsonify({
            "message": (
                "Você não pode retirar sua própria "
                "permissão de administrador"
            )
        }), 400

    vip_plans = [
        "VIP_BRONZE",
        "VIP_PRATA",
        "VIP_OURO",
        "VIP_PREMIUM"
    ]

    if new_plan == "ADMIN":
        target_user.is_admin = True
        target_user.plan = "ADMIN"
        target_user.vip_expires_at = None

        # Atualiza os anúncios desse usuário para ADMIN.
        for ad in target_user.ads:
            ad.plan = "ADMIN"
            ad.is_active = True

    else:
        target_user.is_admin = False
        target_user.plan = new_plan

        if new_plan == "FREE":
            target_user.vip_expires_at = None

        elif new_plan in vip_plans:
            if vip_expires_at_raw:
                try:
                    target_user.vip_expires_at = datetime.strptime(
                        vip_expires_at_raw,
                        "%Y-%m-%d"
                    )
                except ValueError:
                    return jsonify({
                        "message": (
                            "Data de vencimento VIP inválida"
                        )
                    }), 400
            else:
                target_user.vip_expires_at = (
                    utc_now() + timedelta(days=30)
                )

        sync_user_ads_with_plan(
            target_user,
            new_plan
        )

    db.session.commit()

    return jsonify({
        "message": (
            "Usuário alterado para Administrador com sucesso"
            if new_plan == "ADMIN"
            else (
                f"Usuário alterado para "
                f"{get_plan_label(new_plan)} com sucesso"
            )
        ),
        "user": serialize_user(target_user)
    }), 200

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
    
    
@app.route(
    "/admin/ads/<int:ad_id>/delete",
    methods=["DELETE"]
)
@admin_required_page
def admin_delete_ad(ad_id):

    try:
        ad = db.session.get(
            Ad,
            ad_id
        )

        if not ad:
            return jsonify({
                "message": "Anúncio não encontrado"
            }), 404

        # Remove imagem física
        if ad.main_image:
            image_path = resolve_media_file_path(
                ad.main_image
            )

            if (
                image_path
                and os.path.exists(image_path)
            ):
                try:
                    os.remove(image_path)
                except Exception as error:
                    print(
                        "Erro ao excluir imagem:",
                        error,
                        flush=True
                    )

        # Remove vídeo físico
        if ad.main_video:
            video_path = resolve_media_file_path(
                ad.main_video
            )

            if (
                video_path
                and os.path.exists(video_path)
            ):
                try:
                    os.remove(video_path)
                except Exception as error:
                    print(
                        "Erro ao excluir vídeo:",
                        error,
                        flush=True
                    )

        db.session.delete(ad)
        db.session.commit()

        return jsonify({
            "message":
                "Anúncio excluído com sucesso"
        }), 200

    except Exception as error:

        db.session.rollback()

        print(
            "ERRO AO EXCLUIR ANÚNCIO:",
            repr(error),
            flush=True
        )

        return jsonify({
            "message":
                "Erro ao excluir anúncio",
            "error": str(error)
        }), 500
    
@app.route("/users/<int:user_id>", methods=["GET"])
def get_user(user_id):
    if not session.get("user_id"):
        return jsonify({
            "message": "Faça login para acessar os dados do usuário."
        }), 401

    if int(user_id) != int(session["user_id"]):
        return jsonify({
            "message": "Acesso negado."
        }), 403

    user = db.session.get(User, user_id)

    if not user:
        return jsonify({
            "message": "Usuário não encontrado."
        }), 404

    old_plan = user.plan
    old_expiration = user.vip_expires_at

    enforce_user_plan(user)

    if (
        user.plan != old_plan
        or user.vip_expires_at != old_expiration
    ):
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
    selected_plan = (data.get("plan") or "FREE").strip().upper()
    vip_expires_at_raw = (data.get("vip_expires_at") or "").strip()

    allowed_plans = [
        "FREE",
        "VIP_BRONZE",
        "VIP_PRATA",
        "VIP_OURO",
        "VIP_PREMIUM",
        "ADMIN"
    ]

    if selected_plan not in allowed_plans:
        return jsonify({"message": "Tipo de usuário inválido"}), 400

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

    is_admin_user = selected_plan == "ADMIN"

    vip_plans = ["VIP_BRONZE", "VIP_PRATA", "VIP_OURO", "VIP_PREMIUM"]
    vip_expires_at = None

    if selected_plan in vip_plans:
        if vip_expires_at_raw:
            try:
                vip_expires_at = datetime.strptime(vip_expires_at_raw, "%Y-%m-%d")
            except ValueError:
                return jsonify({"message": "Data de vencimento VIP inválida"}), 400
        else:
            vip_expires_at = utc_now() + timedelta(days=30)

    if selected_plan == "FREE":
        vip_expires_at = None

    if selected_plan == "ADMIN":
        vip_expires_at = None

    user = User(
        name=name,
        cpf=cpf,
        email=email,
        phone=phone,
        password_hash=generate_password_hash(password),
        plan=selected_plan,
        vip_expires_at=vip_expires_at,
        is_admin=is_admin_user
    )

    db.session.add(user)
    
    settings = get_app_settings()

    if settings.new_user_vip_promotion_enabled:
        grant_promotional_vip(
            user=user,
            plan=settings.new_user_vip_promotion_plan,
            days=settings.new_user_vip_promotion_days
        )
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

    admin_users = User.query.filter(
        User.is_admin.is_(True)
    ).count()

    vip_users = User.query.filter(
        User.is_admin.is_(False),
        User.plan.in_([
            "VIP_BRONZE",
            "VIP_PRATA",
            "VIP_OURO",
            "VIP_PREMIUM"
        ])
    ).count()

    blocked_users = User.query.filter(
        User.blocked_until.isnot(None)
    ).count()

    vip_bronze = User.query.filter(
        User.is_admin.is_(False),
        User.plan == "VIP_BRONZE"
    ).count()

    vip_prata = User.query.filter(
        User.is_admin.is_(False),
        User.plan == "VIP_PRATA"
    ).count()

    vip_ouro = User.query.filter(
        User.is_admin.is_(False),
        User.plan == "VIP_OURO"
    ).count()

    vip_premium = User.query.filter(
        User.is_admin.is_(False),
        User.plan == "VIP_PREMIUM"
    ).count()

    total_ads = Ad.query.count()
    active_ads = Ad.query.filter_by(is_active=True).count()

    total_reports = Report.query.count()
    pending_reports = Report.query.filter_by(status="OPEN").count()

    total_locations = ManagedLocation.query.count()
    blocked_locations = BlockedLocation.query.count()
    
    today_start = utc_now().replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    thirty_days_ago = utc_now() - timedelta(
        days=30
    )

    total_visitors = SiteVisitor.query.count()

    visitors_today = SiteVisitor.query.filter(
        SiteVisitor.last_visit_at >= today_start
    ).count()

    total_searches = SearchMetric.query.count()

    searches_today = SearchMetric.query.filter(
        SearchMetric.searched_at >= today_start
    ).count()

    top_search_terms_rows = (
        db.session.query(
            SearchMetric.search_term,
            db.func.count(
                SearchMetric.id
            ).label("total")
        )
        .filter(
            SearchMetric.searched_at >= thirty_days_ago,
            SearchMetric.search_term.isnot(None),
            SearchMetric.search_term != ""
        )
        .group_by(
            SearchMetric.search_term
        )
        .order_by(
            db.desc("total")
        )
        .limit(10)
        .all()
    )

    top_search_terms = [
        {
            "term": row[0],
            "total": row[1]
        }
        for row in top_search_terms_rows
    ]

    # Usuários comuns agrupados por plano.
    users_by_plan_rows = (
        db.session.query(
            User.plan,
            db.func.count(User.id)
        )
        .filter(
            User.is_admin.is_(False)
        )
        .group_by(
            User.plan
        )
        .all()
    )

    plan_labels = {
        "FREE": "FREE",
        "VIP_BRONZE": "VIP Bronze",
        "VIP_PRATA": "VIP Prata",
        "VIP_OURO": "VIP Ouro",
        "VIP_PREMIUM": "VIP Premium"
    }

    users_by_plan = [
        {
            "plan": plan_labels.get(
                row[0] or "FREE",
                row[0] or "FREE"
            ),
            "total": row[1]
        }
        for row in users_by_plan_rows
    ]

    # Administradores aparecem separadamente no gráfico.
    if admin_users > 0:
        users_by_plan.append({
            "plan": "Administradores",
            "total": admin_users
        })

    return jsonify({
        "summary": {
        "total_users": total_users,
        "admin_users": admin_users,
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
        "blocked_locations": blocked_locations,
        
        "total_visitors": total_visitors,
        "visitors_today": visitors_today,
        "total_searches": total_searches,
        "searches_today": searches_today,
    },
        "users_by_plan": users_by_plan,
        "top_search_terms": top_search_terms
    }) 
    
@app.route(
    "/media/images/<path:filename>"
)
def serve_uploaded_image(filename):
    response = send_from_directory(
        UPLOAD_IMAGE_FOLDER,
        filename,
        conditional=True
    )

    response.headers["Cache-Control"] = (
        "public, max-age=2592000, immutable"
    )

    return response


@app.route(
    "/media/thumbnails/<path:filename>"
)
def serve_vitrine_thumbnail(filename):
    safe_filename = os.path.basename(
        filename
    )

    thumbnail_path = os.path.join(
        UPLOAD_THUMBNAIL_FOLDER,
        safe_filename
    )

    if not os.path.isfile(thumbnail_path):
        abort(404)

    response = send_from_directory(
        UPLOAD_THUMBNAIL_FOLDER,
        safe_filename,
        conditional=True
    )

    response.headers["Cache-Control"] = (
        "public, max-age=2592000, immutable"
    )

    return response


@app.route(
    "/media/videos/<path:filename>"
)
def serve_uploaded_video(filename):
    return send_from_directory(
        UPLOAD_VIDEO_FOLDER,
        filename,
        conditional=True
    )
    
@app.route("/empregos")
def jobs_page():
    keyword = (
        request.args.get("q")
        or ""
    ).strip()

    state = (
        request.args.get("state")
        or ""
    ).strip()

    city = (
        request.args.get("city")
        or ""
    ).strip()

    job_type = (
        request.args.get("job_type")
        or ""
    ).strip().upper()

    work_model = (
        request.args.get("work_model")
        or ""
    ).strip().upper()
    
    sort = (
        request.args.get("sort")
        or "recentes"
    ).strip().lower()

    query = (
        JobVacancy.query
        .filter(
            JobVacancy.is_active.is_(True)
        )
    )

    if keyword:
        normalized_keyword = (
            normalize_job_search_text(
                keyword
            )
        )

        search_term = (
            f"%{normalized_keyword}%"
        )

        query = query.filter(
            or_(
                normalized_job_column(
                    JobVacancy.title
                ).like(search_term),

                normalized_job_column(
                    JobVacancy.company
                ).like(search_term),

                normalized_job_column(
                    JobVacancy.description
                ).like(search_term)
            )
        )

    if state:
        brazil_states = {
            "AC": "Acre",
            "AL": "Alagoas",
            "AP": "Amapá",
            "AM": "Amazonas",
            "BA": "Bahia",
            "CE": "Ceará",
            "DF": "Distrito Federal",
            "ES": "Espírito Santo",
            "GO": "Goiás",
            "MA": "Maranhão",
            "MT": "Mato Grosso",
            "MS": "Mato Grosso do Sul",
            "MG": "Minas Gerais",
            "PA": "Pará",
            "PB": "Paraíba",
            "PR": "Paraná",
            "PE": "Pernambuco",
            "PI": "Piauí",
            "RJ": "Rio de Janeiro",
            "RN": "Rio Grande do Norte",
            "RS": "Rio Grande do Sul",
            "RO": "Rondônia",
            "RR": "Roraima",
            "SC": "Santa Catarina",
            "SP": "São Paulo",
            "SE": "Sergipe",
            "TO": "Tocantins"
        }

        state_upper = (
            state.strip().upper()
        )

        state_name = brazil_states.get(
            state_upper,
            state
        )

        normalized_state = (
            normalize_job_search_text(
                state_name
            )
        )

        query = query.filter(
            or_(
                normalized_job_column(
                    JobVacancy.state
                ) == normalized_state,

                normalized_job_column(
                    JobVacancy.state
                ) == normalize_job_search_text(
                    state_upper
                )
            )
        )

    if city:
        normalized_city = (
            normalize_job_search_text(
                city
            )
        )

        query = query.filter(
            normalized_job_column(
                JobVacancy.city
            ) == normalized_city
        )

    if job_type:
        query = query.filter(
            JobVacancy.job_type == job_type
        )

    if work_model:
        query = query.filter(
            JobVacancy.work_model == work_model
        )

    if sort == "antigas":

        query = query.order_by(
            JobVacancy.is_featured.desc(),
            JobVacancy.published_at.asc().nullslast(),
            JobVacancy.created_at.asc()
        )

    else:

        # Padrão: vagas mais recentes primeiro
        sort = "recentes"

        query = query.order_by(
            JobVacancy.is_featured.desc(),
            JobVacancy.published_at.desc().nullslast(),
            JobVacancy.created_at.desc()
        )

    vacancies = (
        query
        .limit(100)
        .all()
    )

    return render_template(
        "jobs.html",
        vacancies=vacancies,
        keyword=keyword,
        selected_state=state,
        selected_city=city,
        selected_job_type=job_type,
        selected_work_model=work_model,
        selected_sort=sort
    )
    
@app.route(
    "/empregos/<int:job_id>"
)
def public_job_detail(job_id):

    vacancy = (
        JobVacancy.query
        .filter(
            JobVacancy.id == job_id,
            JobVacancy.is_active.is_(True)
        )
        .first_or_404()
    )

    return render_template(
        "job_detail.html",
        vacancy=vacancy
    )    

@app.route("/publicar-vaga")
def publish_job_page():
    return render_template(
        "publish_job.html"
    )

@app.route(
    "/publicar-vaga",
    methods=["POST"]
)
def publish_job():
    data = request.get_json(
        silent=True
    ) or {}

    title = (
        data.get("title")
        or ""
    ).strip()

    company = (
        data.get("company")
        or ""
    ).strip()

    description = (
        data.get("description")
        or ""
    ).strip()

    state = (
        data.get("state")
        or ""
    ).strip()

    city = (
        data.get("city")
        or ""
    ).strip()

    job_type = (
        data.get("job_type")
        or ""
    ).strip().upper()

    work_model = (
        data.get("work_model")
        or ""
    ).strip().upper()

    salary = (
        data.get("salary")
        or ""
    ).strip()

    contact_email = (
        data.get("contact_email")
        or ""
    ).strip()

    contact_whatsapp = (
        data.get("contact_whatsapp")
        or ""
    ).strip()

    if not title:
        return jsonify({
            "message": "Informe o título da vaga."
        }), 400

    if not company:
        return jsonify({
            "message": "Informe o nome da empresa."
        }), 400

    if not description:
        return jsonify({
            "message": "Informe a descrição da vaga."
        }), 400

    if not state:
        return jsonify({
            "message": "Informe o estado."
        }), 400

    if not city:
        return jsonify({
            "message": "Informe a cidade."
        }), 400

    allowed_job_types = {
        "EMPREGO",
        "ESTAGIO",
        "JOVEM_APRENDIZ",
        "TEMPORARIO",
        "FREELANCER"
    }

    if job_type not in allowed_job_types:
        return jsonify({
            "message": "Tipo de vaga inválido."
        }), 400

    allowed_work_models = {
        "PRESENCIAL",
        "HIBRIDO",
        "REMOTO"
    }

    if work_model not in allowed_work_models:
        return jsonify({
            "message": "Modelo de trabalho inválido."
        }), 400

    if (
        not contact_email
        and not contact_whatsapp
    ):
        return jsonify({
            "message": (
                "Informe pelo menos um contato: "
                "e-mail ou WhatsApp."
            )
        }), 400

    vacancy = JobVacancy(
        source="CATLOGIN",
        title=title,
        company=company,
        description=description,
        country="Brasil",
        state=state,
        city=city,
        location_text=f"{city} - {state}",
        job_type=job_type,
        work_model=work_model,
        salary=salary or None,
        contact_email=(
            contact_email or None
        ),
        contact_whatsapp=(
            contact_whatsapp or None
        ),
        is_active=True,
        is_featured=False,
        published_at=utc_now()
    )

    db.session.add(vacancy)
    db.session.commit()

    return jsonify({
        "message": "Vaga publicada com sucesso.",
        "job_id": vacancy.id
    }), 201

def adzuna_request(
    keywords,
    location,
    page=1,
    results_per_page=50
):
    if not ADZUNA_APP_ID:
        raise RuntimeError(
            "ADZUNA_APP_ID não configurado."
        )

    if not ADZUNA_APP_KEY:
        raise RuntimeError(
            "ADZUNA_APP_KEY não configurada."
        )

    url = (
        f"https://api.adzuna.com/v1/api/jobs/"
        f"{ADZUNA_COUNTRY}/search/{page}"
    )

    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "results_per_page": results_per_page,
        "what": keywords,
        "where": location,
        "content-type": "application/json"
    }

    try:
        response = requests.get(
            url,
            params=params,
            timeout=40
        )

    except requests.RequestException as error:
        raise RuntimeError(
            "Não foi possível conectar à Adzuna."
        ) from error

    print(
        "ADZUNA HTTP STATUS:",
        response.status_code,
        flush=True
    )

    if response.status_code != 200:
        print(
            "ADZUNA RESPOSTA:",
            response.text[:500],
            flush=True
        )

        raise RuntimeError(
            f"A Adzuna retornou HTTP "
            f"{response.status_code}."
        )

    try:
        data = response.json()

    except ValueError as error:
        print(
            "RESPOSTA ADZUNA INVÁLIDA:",
            response.text[:500],
            flush=True
        )

        raise RuntimeError(
            "A Adzuna retornou uma resposta inválida."
        ) from error

    if not isinstance(data, dict):
        raise RuntimeError(
            "Formato inesperado da resposta da Adzuna."
        )

    return data
    
def format_adzuna_salary(
    salary_min,
    salary_max
):
    def format_brl(value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None

        formatted = (
            f"{value:,.2f}"
            .replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
        )

        return f"R$ {formatted}"

    minimum = format_brl(salary_min)
    maximum = format_brl(salary_max)

    if minimum and maximum:
        if minimum == maximum:
            return minimum

        return (
            f"{minimum} a {maximum}"
        )

    if minimum:
        return minimum

    if maximum:
        return maximum

    return None

def import_adzuna_search(
    keywords,
    location,
    page=1,
    results_per_page=50
):
    result = adzuna_request(
        keywords=keywords,
        location=location,
        page=page,
        results_per_page=results_per_page
    )

    jobs = result.get("results") or []

    created = 0
    updated = 0
    ignored = 0

    for item in jobs:

        external_id = str(
            item.get("id") or ""
        ).strip()

        if not external_id:
            ignored += 1
            continue

        title = (
            item.get("title") or ""
        ).strip()

        if not title:
            ignored += 1
            continue

        # -------------------------
        # EMPRESA
        # -------------------------

        company_data = (
            item.get("company") or {}
        )

        company = (
            company_data.get(
                "display_name"
            )
            or ""
        ).strip()

        # -------------------------
        # LOCALIZAÇÃO
        # -------------------------

        location_data = (
            item.get("location") or {}
        )

        location_text = (
            location_data.get(
                "display_name"
            )
            or ""
        ).strip()

        city = None
        state = None

        if location_text:
            parts = [
                part.strip()
                for part
                in location_text.split(",")
                if part.strip()
            ]

            if parts:
                city = parts[0]

            if len(parts) > 1:
                state = parts[-1]

        # -------------------------
        # DESCRIÇÃO
        # -------------------------

        description = (
            item.get("description")
            or ""
        ).strip()

        description = (
            clean_job_description(
                description
            )
        )

        # -------------------------
        # SALÁRIO
        # -------------------------

        salary = format_adzuna_salary(
            item.get("salary_min"),
            item.get("salary_max")
        )

        # -------------------------
        # LINK
        # -------------------------

        external_url = (
            item.get("redirect_url")
            or ""
        ).strip()

        # -------------------------
        # TIPO DA VAGA
        # -------------------------

        contract_type = (
            item.get("contract_type")
            or ""
        ).strip()

        job_type = classify_job_type(
            title,
            contract_type
        )

        # -------------------------
        # DATA ORIGINAL
        # -------------------------

        published_at = None

        created_raw = (
            item.get("created")
            or ""
        ).strip()

        if created_raw:
            try:
                published_at = (
                    datetime.fromisoformat(
                        created_raw.replace(
                            "Z",
                            "+00:00"
                        )
                    )
                )

                if (
                    published_at.tzinfo
                    is not None
                ):
                    published_at = (
                        published_at.replace(
                            tzinfo=None
                        )
                    )

            except Exception:
                published_at = utc_now()

        # -------------------------
        # JÁ EXISTE?
        # -------------------------

        existing = (
            JobVacancy.query
            .filter_by(
                source="ADZUNA",
                external_id=external_id
            )
            .first()
        )

        if existing:

            existing.title = title

            existing.company = (
                company or None
            )

            existing.description = (
                description or None
            )

            existing.country = "Brasil"
            existing.state = state
            existing.city = city

            existing.location_text = (
                location_text or None
            )

            existing.job_type = job_type

            existing.salary = salary

            existing.external_url = (
                external_url or None
            )

            existing.published_at = (
                published_at
            )

            existing.is_active = True

            updated += 1
            continue
            
        cross_duplicate = (
            find_cross_source_job_duplicate(
                source="ADZUNA",
                title=title,
                company=company,
                city=city
            )
        )

        if cross_duplicate:

            print(
                "DUPLICATA ENTRE APIS IGNORADA:",
                "ADZUNA",
                "->",
                cross_duplicate.source,
                "|",
                title,
                "|",
                company,
                "|",
                city,
                flush=True
            )

            ignored += 1
            continue    

        # -------------------------
        # NOVA VAGA
        # -------------------------

        vacancy = JobVacancy(
            source="ADZUNA",
            external_id=external_id,
            title=title,
            company=company or None,
            description=description or None,
            country="Brasil",
            state=state,
            city=city,
            location_text=(
                location_text or None
            ),
            job_type=job_type,
            work_model=None,
            salary=salary,
            external_url=(
                external_url or None
            ),
            is_active=True,
            is_featured=False,
            published_at=published_at
        )

        db.session.add(vacancy)

        created += 1

    db.session.commit()

    return {
        "received": len(jobs),
        "created": created,
        "updated": updated,
        "ignored": ignored,
        "total_available": (
            result.get("count") or 0
        )
    }  
    
def fetch_jsearch_jobs(
    query="auxiliar administrativo em Brasilia DF Brazil",
    num_pages=1,
    country="br",
    language="pt",
    location="Brasilia, Distrito Federal, Brazil",
    date_posted="all",
):
    api_key = os.getenv("JSEARCH_API_KEY")

    if not api_key:
        raise RuntimeError("JSEARCH_API_KEY não configurada.")

    url = "https://jsearch.p.rapidapi.com/search-v2"

    headers = {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": "jsearch.p.rapidapi.com",
    }

    params = {
        "query": query,
        "num_pages": num_pages,
        "country": country,
        "language": language,
        "location": location,
        "date_posted": date_posted,
    }

    last_error = None

    for attempt in range(1, 3):

        try:

            print(
                f"JSEARCH tentativa {attempt}/2",
                flush=True
            )

            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=(5, 15)
            )

            break

        except requests.Timeout as exc:

            last_error = exc

            print(
                f"JSEARCH timeout na tentativa {attempt}/2:",
                repr(exc),
                flush=True
            )

            if attempt < 2:
                time.sleep(1)

        except requests.RequestException as exc:

            raise RuntimeError(
                f"Erro de conexão com a JSearch: {exc}"
            ) from exc

    else:

        raise RuntimeError(
            "JSearch não respondeu dentro do tempo limite."
        ) from last_error

    print("JSEARCH HTTP STATUS:", response.status_code)

    if response.status_code != 200:
        raise RuntimeError(
            f"A JSearch retornou HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "A JSearch retornou uma resposta inválida."
        ) from exc

    jobs = data.get("data", {}).get("jobs", [])

    return {
        "jobs": jobs,
        "cursor": data.get("data", {}).get("cursor"),
        "request_id": data.get("request_id"),
    }   

def import_jsearch_search(
    query,
    num_pages=1,
    country="br",
    language="pt",
    location="Brasilia, Distrito Federal, Brazil",
    date_posted="all",
):
    result = fetch_jsearch_jobs(
        query=query,
        num_pages=num_pages,
        country=country,
        language=language,
        location=location,
        date_posted=date_posted,
    )

    jobs = result.get("jobs") or []

    created = 0
    updated = 0
    ignored = 0

    for item in jobs:

        # -------------------------
        # ID EXTERNO
        # -------------------------

        raw_external_id = str(
            item.get("job_id")
            or ""
        ).strip()

        if not raw_external_id:
            ignored += 1
            continue

        # O job_id da JSearch pode ultrapassar
        # os 255 caracteres permitidos no banco.
        # Criamos um identificador curto e estável.
        external_id = hashlib.sha256(
            raw_external_id.encode("utf-8")
        ).hexdigest()

        # -------------------------
        # TÍTULO
        # -------------------------

        title = (
            item.get("job_title")
            or ""
        ).strip()

        if not title:
            ignored += 1
            continue

        # -------------------------
        # EMPRESA
        # -------------------------

        company = (
            item.get("employer_name")
            or ""
        ).strip()

        # -------------------------
        # DESCRIÇÃO
        # -------------------------

        description = (
            clean_job_description(
                item.get("job_description")
            )
        )

        # -------------------------
        # LOCALIZAÇÃO
        # -------------------------

        city = (
            item.get("job_city")
            or ""
        ).strip() or None

        state = (
            item.get("job_state")
            or ""
        ).strip() or None

        country_name = (
            item.get("job_country")
            or "Brasil"
        ).strip()

        location_parts = [
            part
            for part in (
                city,
                state,
                country_name
            )
            if part
        ]

        location_text = ", ".join(
            location_parts
        )

        # -------------------------
        # TIPO DE EMPREGO
        # -------------------------

        employment_type = (
            item.get("job_employment_type")
            or ""
        ).strip()

        job_type = classify_job_type(
            title,
            employment_type
        )

        # -------------------------
        # MODELO DE TRABALHO
        # -------------------------

        work_model = None

        if item.get("job_is_remote"):
            work_model = "REMOTE"

        # -------------------------
        # SALÁRIO
        # -------------------------

        salary_min = item.get(
            "job_min_salary"
        )

        salary_max = item.get(
            "job_max_salary"
        )

        salary_currency = (
            item.get("job_salary_currency")
            or ""
        ).strip()

        salary = None

        if (
            salary_min is not None
            or salary_max is not None
        ):
            salary_parts = []

            if salary_min is not None:
                salary_parts.append(
                    str(salary_min)
                )

            if salary_max is not None:
                salary_parts.append(
                    str(salary_max)
                )

            salary = " - ".join(
                salary_parts
            )

            if salary_currency:
                salary = (
                    f"{salary_currency} "
                    f"{salary}"
                )

        # -------------------------
        # LINK
        # -------------------------

        external_url = (
            item.get("job_apply_link")
            or item.get("job_google_link")
            or ""
        ).strip()

        # -------------------------
        # DATA DE PUBLICAÇÃO
        # -------------------------

        published_at = None

        published_raw = (
            item.get(
                "job_posted_at_datetime_utc"
            )
            or ""
        ).strip()

        if published_raw:
            try:
                published_at = (
                    datetime.fromisoformat(
                        published_raw.replace(
                            "Z",
                            "+00:00"
                        )
                    )
                )

                if (
                    published_at.tzinfo
                    is not None
                ):
                    published_at = (
                        published_at.replace(
                            tzinfo=None
                        )
                    )

            except Exception:
                published_at = utc_now()

        # -------------------------
        # JÁ EXISTE NA JSEARCH?
        # -------------------------

        existing = (
            JobVacancy.query
            .filter_by(
                source="JSEARCH",
                external_id=external_id
            )
            .first()
        )

        if existing:

            existing.title = title
            existing.company = (
                company or None
            )
            existing.description = (
                description or None
            )
            existing.country = "Brasil"
            existing.state = state
            existing.city = city
            existing.location_text = (
                location_text or None
            )
            existing.job_type = job_type
            existing.work_model = (
                work_model
            )
            existing.salary = salary
            existing.external_url = (
                external_url or None
            )
            existing.published_at = (
                published_at
            )
            existing.is_active = True

            updated += 1
            continue

        # -------------------------
        # DUPLICATA ENTRE APIS
        # -------------------------

        cross_duplicate = (
            find_cross_source_job_duplicate(
                source="JSEARCH",
                title=title,
                company=company,
                city=city
            )
        )

        if cross_duplicate:

            print(
                "DUPLICATA ENTRE APIS IGNORADA:",
                "JSEARCH",
                "->",
                cross_duplicate.source,
                "|",
                title,
                "|",
                company,
                "|",
                city,
                flush=True
            )

            ignored += 1
            continue

        # -------------------------
        # NOVA VAGA
        # -------------------------

        vacancy = JobVacancy(
            source="JSEARCH",
            external_id=external_id,
            title=title,
            company=company or None,
            description=description or None,
            country="Brasil",
            state=state,
            city=city,
            location_text=(
                location_text or None
            ),
            job_type=job_type,
            work_model=work_model,
            salary=salary,
            external_url=(
                external_url or None
            ),
            is_active=True,
            is_featured=False,
            published_at=published_at
        )

        db.session.add(vacancy)

        created += 1

    db.session.commit()

    return {
        "received": len(jobs),
        "created": created,
        "updated": updated,
        "ignored": ignored
    }    

@app.route(
    "/admin/empregos/importar-adzuna",
    methods=["POST"]
)
@admin_required_page
def admin_import_adzuna_jobs():

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    keywords = (
        data.get("keywords")
        or "emprego"
    ).strip()

    location = (
        data.get("location")
        or "Brasilia"
    ).strip()

    try:
        result = import_adzuna_search(
            keywords=keywords,
            location=location,
            page=1,
            results_per_page=50
        )

        return jsonify({
            "message":
                "Importação da Adzuna concluída com sucesso.",
            "keywords": keywords,
            "location": location,
            "vagas_recebidas":
                result["received"],
            "novas":
                result["created"],
            "atualizadas":
                result["updated"],
            "ignoradas":
                result["ignored"],
            "total_disponivel":
                result["total_available"]
        })

    except Exception as error:

        db.session.rollback()

        print(
            "ERRO IMPORTAÇÃO ADZUNA:",
            repr(error),
            flush=True
        )

        return jsonify({
            "message": str(error)
        }), 500

@app.route(
    "/admin/importar-adzuna-teste",
    methods=["GET"]
)
@admin_required_page
def admin_import_adzuna_test():
    try:

        result = import_adzuna_search(
            keywords="auxiliar administrativo",
            location="Brasilia",
            page=1,
            results_per_page=5
        )

        return jsonify({
            "ok": True,
            **result
        })

    except Exception as error:

        db.session.rollback()

        print(
            "ERRO IMPORTAÇÃO ADZUNA:",
            repr(error),
            flush=True
        )

        return jsonify({
            "ok": False,
            "erro": str(error)
        }), 500    
    
@app.route(
    "/admin/testar-adzuna",
    methods=["GET"]
)
@admin_required_page
def admin_test_adzuna():
    try:
        result = adzuna_request(
            keywords="auxiliar administrativo",
            location="Brasilia",
            page=1,
            results_per_page=5
        )

        jobs = result.get("results") or []

        return jsonify({
            "ok": True,
            "total_encontrado": result.get("count"),
            "recebidas": len(jobs),
            "vagas": [
                {
                    "id": job.get("id"),
                    "titulo": job.get("title"),
                    "empresa": (
                        job.get("company") or {}
                    ).get("display_name"),
                    "local": (
                        job.get("location") or {}
                    ).get("display_name"),
                    "publicada_em": job.get("created"),
                    "url": job.get("redirect_url")
                }
                for job in jobs
            ]
        })

    except Exception as error:
        print(
            "ERRO TESTE ADZUNA:",
            repr(error),
            flush=True
        )

        return jsonify({
            "ok": False,
            "erro": str(error)
        }), 500    
    
def jooble_request(payload):
    api_key = (
        os.getenv("JOOBLE_API_KEY")
        or ""
    ).strip()

    if not api_key:
        raise RuntimeError(
            "JOOBLE_API_KEY não configurada."
        )

    # A chave da Jooble tem formato UUID.
    # Isso evita fazer chamadas com chave incorreta
    # ou valor errado vindo do .env.
    if not re.fullmatch(
        r"[0-9a-fA-F]{8}-"
        r"[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{12}",
        api_key
    ):
        raise RuntimeError(
            "JOOBLE_API_KEY possui formato inválido."
        )

    url = (
        f"https://br.jooble.org/api/{api_key}"
    )

    # Fazemos uma cópia para não alterar
    # o payload original recebido pela rota.
    jooble_payload = dict(
        payload
    )

    # Normaliza localização para ASCII.
    # No teste realizado diretamente no CMD,
    # 'Brasilia' funcionou corretamente.
    location = str(
        jooble_payload.get(
            "location",
            ""
        )
    ).strip()

    if location:
        location = unicodedata.normalize(
            "NFKD",
            location
        )

        location = "".join(
            char
            for char in location
            if not unicodedata.combining(
                char
            )
        )

        jooble_payload[
            "location"
        ] = location

    request_body = json.dumps(
        jooble_payload,
        ensure_ascii=True,
        separators=(",", ":")
    )

    # No Windows usamos explicitamente
    # o curl.exe nativo que já testamos
    # manualmente e sabemos que funciona.
    curl_command = (
        "curl.exe"
        if os.name == "nt"
        else "curl"
    )

    command = [
        curl_command,

        "-sS",

        "--http1.1",

        "-X",
        "POST",

        url,

        "-H",
        "Content-Type: application/json",

        "-H",
        "Accept: application/json",

        "-d",
        request_body,

        "-w",
        "\n__HTTP_STATUS__:%{http_code}"
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=40,
            check=False
        )

    except FileNotFoundError as error:
        raise RuntimeError(
            "O executável curl não foi encontrado."
        ) from error

    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            "A consulta à Jooble excedeu "
            "o tempo limite."
        ) from error

    if result.returncode != 0:
        raise RuntimeError(
            "Erro ao executar curl: "
            + (
                result.stderr.strip()
                or "erro desconhecido"
            )
        )

    raw_output = (
        result.stdout
        or ""
    ).strip()

    marker = (
        "\n__HTTP_STATUS__:"
    )

    if marker not in raw_output:
        raise RuntimeError(
            "Não foi possível identificar "
            "o status HTTP da Jooble."
        )

    response_text, status_text = (
        raw_output.rsplit(
            marker,
            1
        )
    )

    response_text = (
        response_text.strip()
    )

    status_text = (
        status_text.strip()
    )

    try:
        status_code = int(
            status_text
        )

    except ValueError:
        status_code = 0

    print(
        "JOOBLE HTTP STATUS:",
        status_code,
        flush=True
    )

    print(
        "JOOBLE KEY OK:",
        len(api_key) == 36,
        flush=True
    )

    print(
        "JOOBLE LOCATION:",
        jooble_payload.get(
            "location"
        ),
        flush=True
    )

    if status_code != 200:
        print(
            "JOOBLE RESPOSTA:",
            response_text[:300],
            flush=True
        )

        raise RuntimeError(
            f"A Jooble retornou HTTP "
            f"{status_code}."
        )

    if not response_text:
        raise RuntimeError(
            "A Jooble retornou resposta vazia."
        )

    if (
        response_text.lstrip()
        .lower()
        .startswith("<!doctype")
        or
        response_text.lstrip()
        .lower()
        .startswith("<html")
    ):
        raise RuntimeError(
            "A Jooble retornou HTML "
            "em vez de JSON."
        )

    try:
        data = json.loads(
            response_text
        )

    except json.JSONDecodeError as error:
        print(
            "RESPOSTA JOOBLE INVÁLIDA:",
            response_text[:500],
            flush=True
        )

        raise RuntimeError(
            "Resposta inválida da Jooble."
        ) from error

    if not isinstance(
        data,
        dict
    ):
        raise RuntimeError(
            "Formato inesperado da "
            "resposta da Jooble."
        )

    return data
    
@app.route(
    "/admin/empregos/importar-jsearch",
    methods=["POST"]
)
@admin_required_page
def admin_import_jsearch():

    try:
        data = request.get_json(
            silent=True
        ) or {}

        keywords = str(
            data.get("keywords")
            or ""
        ).strip()

        location = str(
            data.get("location")
            or ""
        ).strip()

        if not keywords:
            return jsonify({
                "message":
                    "Informe uma palavra-chave."
            }), 400

        if not location:
            return jsonify({
                "message":
                    "Informe uma localização."
            }), 400

        query = (
            f"{keywords} em {location}"
        )

        result = import_jsearch_search(
            query=query,
            num_pages=1,
            country="br",
            language="pt",
            location=location,
            date_posted="all"
        )

        return jsonify({
            "message":
                "Importação da JSearch concluída.",

            "keywords":
                keywords,

            "location":
                location,

            "vagas_recebidas":
                result["received"],

            "novas":
                result["created"],

            "atualizadas":
                result["updated"],

            "ignoradas":
                result["ignored"]
        })

    except Exception as error:

        db.session.rollback()

        print(
            "ERRO IMPORTAÇÃO JSEARCH:",
            repr(error),
            flush=True
        )

        return jsonify({
            "message": str(error)
        }), 500    
    
@app.route("/admin/testar-jsearch")
def admin_testar_jsearch():
    try:
        resultado = fetch_jsearch_jobs()

        jobs = resultado["jobs"]

        vagas = []

        for job in jobs[:10]:
            vagas.append({
                "id": job.get("job_id"),
                "titulo": job.get("job_title"),
                "empresa": job.get("employer_name"),
                "publicador": job.get("job_publisher"),
                "cidade": job.get("job_city"),
                "estado": job.get("job_state"),
                "pais": job.get("job_country"),
                "tipo": job.get("job_employment_type"),
                "publicada_em": job.get("job_posted_at_datetime_utc"),
                "link": (
                    job.get("job_apply_link")
                    or job.get("job_google_link")
                ),
            })

        return jsonify({
            "ok": True,
            "recebidas": len(jobs),
            "request_id": resultado.get("request_id"),
            "vagas": vagas,
        })

    except Exception as exc:
        print("ERRO TESTE JSEARCH:", repr(exc))

        return jsonify({
            "ok": False,
            "erro": str(exc),
        }), 500    
        
@app.route(
    "/admin/empregos/importar-jooble",
    methods=["POST"]
)

@app.route(
    "/admin/empregos/importar-automatico",
    methods=["POST"]
)
@admin_required_page
def admin_run_automatic_job_import():

    try:
        summary = (
            run_automatic_job_import()
        )

        return jsonify({
            "message":
                "Importação automática concluída.",

            "pesquisas":
                summary["searches"],

            "recebidas":
                summary["received"],

            "novas":
                summary["created"],

            "atualizadas":
                summary["updated"],

            "ignoradas":
                summary["ignored"],

            "jooble":
                summary["jooble"],

            "adzuna":
                summary["adzuna"],
                
            "jsearch":
                summary["jsearch"],    
                
            "desativadas": summary.get(
                "deactivated",
                0
            ),    
        })

    except Exception as error:

        db.session.rollback()

        print(
            "ERRO IMPORTAÇÃO AUTOMÁTICA:",
            repr(error),
            flush=True
        )

        return jsonify({
            "message": str(error)
        }), 500

@admin_required_page
def admin_import_jooble_jobs():
    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    keywords = (
        data.get("keywords")
        or "emprego"
    ).strip()

    location = (
        data.get("location")
        or "Brasília"
    ).strip()

    payload = {
        "keywords": keywords,
        "location": location,
        "page": "1"
    }

    try:
        result = jooble_request(
            payload
        )

        jobs = (
            result.get("jobs")
            or []
        )

        created = 0
        updated = 0
        ignored = 0

        for item in jobs:
            external_id = str(
                item.get("id")
                or ""
            ).strip()

            if not external_id:
                ignored += 1
                continue

            title = (
                item.get("title")
                or ""
            ).strip()

            if not title:
                ignored += 1
                continue

            company = (
                item.get("company")
                or ""
            ).strip()

            location_text = (
                item.get("location")
                or ""
            ).strip()

            city = None
            state = None

            if location_text:
                parts = [
                    part.strip()
                    for part in location_text.split(",")
                    if part.strip()
                ]

                if parts:
                    city = parts[0]

                if len(parts) > 1:
                    state = parts[-1]

            description = (
                clean_job_description(
                    item.get("snippet")
                )
            )

            salary = (
                item.get("salary")
                or ""
            ).strip()

            external_url = (
                item.get("link")
                or ""
            ).strip()

            jooble_type = (
                item.get("type")
                or ""
            ).strip()

            job_type = classify_job_type(
                title,
                jooble_type
            )

            published_at = None

            updated_raw = (
                item.get("updated")
                or ""
            ).strip()

            if updated_raw:
                try:
                    published_at = (
                        datetime.fromisoformat(
                            updated_raw.replace(
                                "Z",
                                "+00:00"
                            )
                        )
                    )

                    if published_at.tzinfo is not None:
                        published_at = (
                            published_at.replace(
                                tzinfo=None
                            )
                        )

                except Exception:
                    published_at = utc_now()

            existing = (
                JobVacancy.query
                .filter_by(
                    source="JOOBLE",
                    external_id=external_id
                )
                .first()
            )

            if existing:
                existing.title = title
                existing.company = company or None
                existing.description = description or None
                existing.country = "Brasil"
                existing.state = state
                existing.city = city
                existing.location_text = (
                    location_text or None
                )
                existing.job_type = job_type
                existing.salary = salary or None
                existing.external_url = (
                    external_url or None
                )
                existing.published_at = published_at
                existing.is_active = True

                updated += 1
                continue

            vacancy = JobVacancy(
                source="JOOBLE",
                external_id=external_id,
                title=title,
                company=company or None,
                description=description or None,
                country="Brasil",
                state=state,
                city=city,
                location_text=(
                    location_text or None
                ),
                job_type=job_type,
                work_model=None,
                salary=salary or None,
                external_url=(
                    external_url or None
                ),
                is_active=True,
                is_featured=False,
                published_at=published_at
            )

            db.session.add(vacancy)
            created += 1

        db.session.commit()

        return jsonify({
            "message":
                "Importação concluída com sucesso.",
            "keywords": keywords,
            "location": location,
            "vagas_recebidas": len(jobs),
            "novas": created,
            "atualizadas": updated,
            "ignoradas": ignored
        })

    except Exception as error:
        db.session.rollback()

        print(
            "ERRO IMPORTAÇÃO JOOBLE:",
            repr(error),
            flush=True
        )

        return jsonify({
            "message": str(error)
        }), 500        


@app.route(
    "/admin/empregos/<int:job_id>/toggle-status",
    methods=["POST"]
)
@admin_required_page
def admin_job_toggle_status(job_id):
    vacancy = db.session.get(
        JobVacancy,
        job_id
    )

    if not vacancy:
        return jsonify({
            "message": "Vaga não encontrada."
        }), 404

    try:
        vacancy.is_active = not bool(
            vacancy.is_active
        )

        db.session.commit()

        return jsonify({
            "message": (
                "Vaga ativada com sucesso."
                if vacancy.is_active
                else "Vaga desativada com sucesso."
            ),
            "is_active": vacancy.is_active
        })

    except Exception as error:
        db.session.rollback()

        print(
            "ERRO ALTERAR STATUS VAGA:",
            repr(error),
            flush=True
        )

        return jsonify({
            "message":
                "Não foi possível alterar o status da vaga."
        }), 500
        
@app.route(
    "/admin/empregos/<int:job_id>/toggle-featured",
    methods=["POST"]
)
@admin_required_page
def admin_job_toggle_featured(job_id):
    vacancy = db.session.get(
        JobVacancy,
        job_id
    )

    if not vacancy:
        return jsonify({
            "message": "Vaga não encontrada."
        }), 404

    try:
        vacancy.is_featured = not bool(
            vacancy.is_featured
        )

        db.session.commit()

        return jsonify({
            "message": (
                "Vaga destacada com sucesso."
                if vacancy.is_featured
                else "Destaque removido com sucesso."
            ),
            "is_featured":
                vacancy.is_featured
        })

    except Exception as error:
        db.session.rollback()

        print(
            "ERRO ALTERAR DESTAQUE VAGA:",
            repr(error),
            flush=True
        )

        return jsonify({
            "message":
                "Não foi possível alterar o destaque."
        }), 500 

@app.route(
    "/admin/empregos/<int:job_id>/excluir",
    methods=["DELETE"]
)
@admin_required_page
def admin_job_delete(job_id):
    vacancy = db.session.get(
        JobVacancy,
        job_id
    )

    if not vacancy:
        return jsonify({
            "message": "Vaga não encontrada."
        }), 404

    try:
        title = vacancy.title

        db.session.delete(
            vacancy
        )

        db.session.commit()

        return jsonify({
            "message":
                f'Vaga "{title}" excluída com sucesso.'
        })

    except Exception as error:
        db.session.rollback()

        print(
            "ERRO EXCLUIR VAGA:",
            repr(error),
            flush=True
        )

        return jsonify({
            "message":
                "Não foi possível excluir a vaga."
        }), 500        
  
@app.route("/admin/empregos")
@admin_required_page
def admin_jobs_page():
    vacancies = (
        JobVacancy.query
        .order_by(
            JobVacancy.created_at.desc()
        )
        .all()
    )

    total_jobs = (
        JobVacancy.query
        .count()
    )

    active_jobs = (
        JobVacancy.query
        .filter(
            JobVacancy.is_active.is_(True)
        )
        .count()
    )

    catalogin_jobs = (
        JobVacancy.query
        .filter(
            JobVacancy.source == "CATLOGIN"
        )
        .count()
    )

    jooble_jobs = (
        JobVacancy.query
        .filter(
            JobVacancy.source == "JOOBLE"
        )
        .count()
    )
    
    adzuna_jobs = (
        JobVacancy.query
        .filter(
            JobVacancy.source == "ADZUNA"
        )
        .count()
    )
    
    jsearch_jobs = (
        JobVacancy.query
        .filter(
            JobVacancy.source == "JSEARCH"
        )
        .count()
    )

    return render_template(
        "admin_jobs.html",
        vacancies=vacancies,
        total_jobs=total_jobs,
        active_jobs=active_jobs,
        catalogin_jobs=catalogin_jobs,
        jooble_jobs=jooble_jobs,
        adzuna_jobs=adzuna_jobs,
        jsearch_jobs=jsearch_jobs,
        active_page="jobs"
    )

@app.route("/ofertas")
def public_offers_page():

    now = utc_now()

    q = (
        request.args.get("q")
        or ""
    ).strip()

    category = (
        request.args.get("category")
        or ""
    ).strip()

    store = (
        request.args.get("store")
        or ""
    ).strip()

    sort = (
        request.args.get("sort")
        or "recentes"
    ).strip().lower()

    query = (
        AffiliateProduct.query
        .filter(
            AffiliateProduct.is_active.is_(True),
            or_(
                AffiliateProduct.expires_at.is_(None),
                AffiliateProduct.expires_at >= now
            )
        )
    )

    if q:

        search_term = (
            f"%{q}%"
        )

        query = query.filter(
            or_(
                AffiliateProduct.title.ilike(
                    search_term
                ),
                AffiliateProduct.description.ilike(
                    search_term
                ),
                AffiliateProduct.category.ilike(
                    search_term
                ),
                AffiliateProduct.store.ilike(
                    search_term
                )
            )
        )

    if category:

        query = query.filter(
            AffiliateProduct.category == category
        )

    if store:

        query = query.filter(
            AffiliateProduct.store == store
        )

    if sort == "menor_preco":

        query = query.order_by(
            AffiliateProduct.is_featured.desc(),
            AffiliateProduct.price.asc().nullslast(),
            AffiliateProduct.created_at.desc()
        )

    elif sort == "maior_preco":

        query = query.order_by(
            AffiliateProduct.is_featured.desc(),
            AffiliateProduct.price.desc().nullslast(),
            AffiliateProduct.created_at.desc()
        )

    else:

        sort = "recentes"

        query = query.order_by(
            AffiliateProduct.is_featured.desc(),
            AffiliateProduct.created_at.desc()
        )

    offers = query.all()

    categories = (
        db.session.query(
            AffiliateProduct.category
        )
        .filter(
            AffiliateProduct.category.isnot(None),
            AffiliateProduct.category != "",
            AffiliateProduct.is_active.is_(True)
        )
        .distinct()
        .order_by(
            AffiliateProduct.category.asc()
        )
        .all()
    )

    stores = (
        db.session.query(
            AffiliateProduct.store
        )
        .filter(
            AffiliateProduct.store.isnot(None),
            AffiliateProduct.store != "",
            AffiliateProduct.is_active.is_(True)
        )
        .distinct()
        .order_by(
            AffiliateProduct.store.asc()
        )
        .all()
    )

    categories = [
        item[0]
        for item in categories
    ]

    stores = [
        item[0]
        for item in stores
    ]
    
    affiliate_stores = (
        AffiliateStore.query
        .filter(
            AffiliateStore.is_active.is_(True)
        )
        .order_by(
            AffiliateStore.display_order.asc(),
            AffiliateStore.name.asc()
        )
        .all()
    )

    return render_template(
        "offers.html",
        offers=offers,
        affiliate_stores=affiliate_stores,
        categories=categories,
        stores=stores,
        selected_q=q,
        selected_category=category,
        selected_store=store,
        selected_sort=sort
    )
    
@app.route(
    "/ofertas/lojas/<int:store_id>/ir"
)
def affiliate_store_redirect(store_id):

    affiliate_store = db.session.get(
        AffiliateStore,
        store_id
    )

    if (
        not affiliate_store
        or not affiliate_store.is_active
        or not affiliate_store.affiliate_url
    ):
        abort(404)

    try:

        affiliate_store.click_count = (
            affiliate_store.click_count or 0
        ) + 1

        db.session.commit()

    except Exception:

        db.session.rollback()

    return redirect(
        affiliate_store.affiliate_url
    )    

@app.route("/ofertas/<int:offer_id>/ir")
def affiliate_offer_redirect(offer_id):

    offer = db.session.get(
        AffiliateProduct,
        offer_id
    )

    if (
        not offer
        or not offer.is_active
        or not offer.affiliate_url
    ):
        abort(404)

    if (
        offer.expires_at
        and offer.expires_at < utc_now()
    ):
        abort(404)

    try:
        offer.click_count = (
            offer.click_count or 0
        ) + 1

        db.session.commit()

    except Exception:
        db.session.rollback()

    return redirect(
        offer.affiliate_url
    )    
    
    
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