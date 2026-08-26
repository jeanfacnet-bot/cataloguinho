from app import app, db, AppSetting


with app.app_context():

    table_name = (
        AppSetting.__table__.name
    )

    print(
        "Tabela AppSetting encontrada como:",
        table_name
    )

    statements = [
        f"""
        ALTER TABLE "{table_name}"
        ADD COLUMN IF NOT EXISTS
        mercado_livre_access_token TEXT
        """,

        f"""
        ALTER TABLE "{table_name}"
        ADD COLUMN IF NOT EXISTS
        mercado_livre_refresh_token TEXT
        """,

        f"""
        ALTER TABLE "{table_name}"
        ADD COLUMN IF NOT EXISTS
        mercado_livre_token_expires_at TIMESTAMP
        """,

        f"""
        ALTER TABLE "{table_name}"
        ADD COLUMN IF NOT EXISTS
        mercado_livre_user_id VARCHAR(50)
        """
    ]

    try:

        for statement in statements:

            db.session.execute(
                db.text(statement)
            )

        db.session.commit()

        print(
            "Migração Mercado Livre concluída com sucesso."
        )

    except Exception as error:

        db.session.rollback()

        print(
            "ERRO NA MIGRAÇÃO:",
            repr(error)
        )

        raise