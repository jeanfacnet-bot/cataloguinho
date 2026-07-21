from sqlalchemy import text
from app import app, db


with app.app_context():
    try:
        db.session.execute(
            text("""
                ALTER TABLE ads
                ADD COLUMN IF NOT EXISTS show_on_home
                BOOLEAN NOT NULL DEFAULT FALSE
            """)
        )

        db.session.execute(
            text("""
                CREATE INDEX IF NOT EXISTS ix_ads_show_on_home
                ON ads(show_on_home)
            """)
        )

        db.session.commit()

        print(
            "Coluna show_on_home criada com sucesso."
        )

    except Exception as error:
        db.session.rollback()

        print(
            "Erro ao criar a coluna:",
            error
        )