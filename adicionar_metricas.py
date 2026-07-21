from app import app, db
from sqlalchemy import text


def executar(sql):
    db.session.execute(text(sql))


with app.app_context():
    try:
        print("Criando tabela site_visitors...")

        executar("""
        CREATE TABLE IF NOT EXISTS site_visitors (
            id SERIAL PRIMARY KEY,
            visitor_id VARCHAR(100) NOT NULL UNIQUE,
            first_visit_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_visit_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """)

        print("Criando tabela search_metrics...")

        executar("""
        CREATE TABLE IF NOT EXISTS search_metrics (
            id SERIAL PRIMARY KEY,
            visitor_id VARCHAR(100),
            search_term VARCHAR(255),
            searched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """)

        print("Criando índices...")

        executar("""
        CREATE INDEX IF NOT EXISTS ix_site_visitors_visitor_id
        ON site_visitors(visitor_id);
        """)

        executar("""
        CREATE INDEX IF NOT EXISTS ix_site_visitors_first_visit_at
        ON site_visitors(first_visit_at);
        """)

        executar("""
        CREATE INDEX IF NOT EXISTS ix_site_visitors_last_visit_at
        ON site_visitors(last_visit_at);
        """)

        executar("""
        CREATE INDEX IF NOT EXISTS ix_search_metrics_visitor_id
        ON search_metrics(visitor_id);
        """)

        executar("""
        CREATE INDEX IF NOT EXISTS ix_search_metrics_search_term
        ON search_metrics(search_term);
        """)

        executar("""
        CREATE INDEX IF NOT EXISTS ix_search_metrics_searched_at
        ON search_metrics(searched_at);
        """)

        db.session.commit()

        print("\n===================================")
        print("Métricas criadas com sucesso!")
        print("===================================")

    except Exception as e:
        db.session.rollback()

        print("\nERRO:")
        print(e)