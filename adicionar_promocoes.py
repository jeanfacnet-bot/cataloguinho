from sqlalchemy import text
from app import app, db


with app.app_context():
    db.session.execute(text("""
        ALTER TABLE app_settings
        ADD COLUMN IF NOT EXISTS
        new_user_vip_promotion_enabled
        BOOLEAN NOT NULL DEFAULT FALSE
    """))

    db.session.execute(text("""
        ALTER TABLE app_settings
        ADD COLUMN IF NOT EXISTS
        new_user_vip_promotion_plan
        VARCHAR(20) NOT NULL DEFAULT 'VIP_BRONZE'
    """))

    db.session.execute(text("""
        ALTER TABLE app_settings
        ADD COLUMN IF NOT EXISTS
        new_user_vip_promotion_days
        INTEGER NOT NULL DEFAULT 30
    """))

    db.session.commit()

    print("Colunas de promoções criadas com sucesso.")