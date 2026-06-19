"""
Migrations runner — conecta direto ao Postgres via SUPABASE_DB_URL.

Uso:
    python migrations.py            # aplica todas as pendentes
    python migrations.py --list     # lista status de cada migration
"""

import argparse
import logging
import sys
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

from app.config import Config

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Migrations — adicione novas entradas ao final da lista.
# Cada migration é (name: str, sql: str). O SQL deve ser idempotente.
# ---------------------------------------------------------------------------

MIGRATIONS: list[tuple[str, str]] = [
    (
        "0001_create_conversation_messages",
        """
        CREATE TABLE IF NOT EXISTS conversation_messages (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            phone_whatsapp TEXT        NOT NULL,
            role           TEXT        NOT NULL CHECK (role IN ('human', 'ai')),
            content        TEXT        NOT NULL,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS idx_conv_messages_phone_created
            ON conversation_messages (phone_whatsapp, created_at);
        """,
    ),
    (
        "0002_add_summarized_count_to_sessions",
        """
        ALTER TABLE conversation_sessions
            ADD COLUMN IF NOT EXISTS summarized_count INTEGER NOT NULL DEFAULT 0;
        """,
    ),
]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _connect():
    url = Config.SUPABASE_DB_URL
    if not url:
        logger.error("SUPABASE_DB_URL não está configurado no .env")
        sys.exit(1)
    # Garante connect_timeout para não travar
    if "connect_timeout" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}connect_timeout=10"
    return psycopg2.connect(url)


def _ensure_migrations_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            name       TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)


def _applied(cur) -> set[str]:
    cur.execute("SELECT name FROM _migrations;")
    return {row[0] for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def run(conn):
    with conn:
        with conn.cursor() as cur:
            _ensure_migrations_table(cur)
            done = _applied(cur)

            pending = [(n, sql) for n, sql in MIGRATIONS if n not in done]
            if not pending:
                logger.info("Nenhuma migration pendente.")
                return

            for name, sql in pending:
                logger.info("Aplicando: %s", name)
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO _migrations (name, applied_at) VALUES (%s, %s);",
                    (name, datetime.now(timezone.utc)),
                )
                logger.info("OK: %s", name)

    logger.info("Migrations concluídas.")


def list_status(conn):
    with conn.cursor() as cur:
        _ensure_migrations_table(cur)
        done = _applied(cur)

    print(f"\n{'STATUS':<10} {'NOME'}")
    print("-" * 50)
    for name, _ in MIGRATIONS:
        status = "aplicada" if name in done else "pendente"
        print(f"{status:<10} {name}")
    print()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="G8-AI migrations runner")
    parser.add_argument("--list", action="store_true", help="Lista o status de cada migration")
    args = parser.parse_args()

    conn = _connect()
    try:
        if args.list:
            list_status(conn)
        else:
            run(conn)
    finally:
        conn.close()
