"""
Adiciona colunas summary e message_count à tabela conversation_sessions
para suporte a sumarização automática de conversas longas.
"""

import psycopg
from app.config import Config

DDL = """
ALTER TABLE conversation_sessions
    ADD COLUMN IF NOT EXISTS summary TEXT,
    ADD COLUMN IF NOT EXISTS message_count INTEGER DEFAULT 0;
"""


def _pg_conn():
    db_url = Config.SUPABASE_DB_URL
    if not db_url:
        raise RuntimeError("SUPABASE_DB_URL não configurado")
    return psycopg.connect(db_url, connect_timeout=10)


def up():
    with _pg_conn() as conn:
        conn.execute(DDL)
        conn.execute("NOTIFY pgrst, 'reload schema'")


def down():
    with _pg_conn() as conn:
        conn.execute("ALTER TABLE conversation_sessions DROP COLUMN IF EXISTS summary;")
        conn.execute("ALTER TABLE conversation_sessions DROP COLUMN IF EXISTS message_count;")
        conn.execute("NOTIFY pgrst, 'reload schema'")
