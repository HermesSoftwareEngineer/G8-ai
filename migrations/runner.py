"""
Migration runner — executa arquivos .py de migração na ordem numérica.
Cada migração define up() e opcionalmente down().

Uso:
    python -m migrations.runner           # aplica migrações pendentes
    python -m migrations.runner --down 1  # reverte migração 001
    python -m migrations.runner --status  # lista migrações pendentes

O estado é armazenado na tabela _migrations (criada automaticamente).
Toda operação em _migrations usa conexão direta Postgres, pois o PostgREST
não cacheia a tabela instantaneamente após DDL.
"""

import importlib
import os
import sys
import re
import logging
import psycopg
from dotenv import load_dotenv

load_dotenv()

from app.config import Config

logger = logging.getLogger("migrations")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

MIGRATIONS_DIR = os.path.dirname(__file__)


def _pg_conn():
    db_url = Config.SUPABASE_DB_URL
    if not db_url:
        raise RuntimeError("SUPABASE_DB_URL não configurado")
    return psycopg.connect(db_url, connect_timeout=10)


def _ensure_migrations_table():
    with _pg_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                applied_at TIMESTAMPTZ DEFAULT now()
            );
        """)
    logger.info("Tabela _migrations pronta")


def _get_applied():
    with _pg_conn() as conn:
        rows = conn.execute("SELECT name FROM _migrations ORDER BY name").fetchall()
    return {r[0] for r in rows}


def _discover():
    files = []
    for f in sorted(os.listdir(MIGRATIONS_DIR)):
        m = re.match(r"^(\d{3})_(.+)\.py$", f)
        if m:
            files.append((m.group(1), m.group(2), f))
    return files


def _apply(name: str, module):
    logger.info("Aplicando %s ...", name)
    module.up()
    with _pg_conn() as conn:
        conn.execute("INSERT INTO _migrations (name) VALUES (%s)", (name,))
    logger.info("%s ✓", name)


def _revert(name: str, module):
    if not hasattr(module, "down"):
        logger.warning("%s não tem down(), pulando", name)
        return
    logger.info("Revertendo %s ...", name)
    module.down()
    with _pg_conn() as conn:
        conn.execute("DELETE FROM _migrations WHERE name = %s", (name,))
    logger.info("%s revertida", name)


def run():
    _ensure_migrations_table()
    applied = _get_applied()
    migrations = _discover()

    if "--status" in sys.argv:
        print("Migrações:")
        for num, nm, fn in migrations:
            full = f"{num}_{nm}"
            status = "applied" if full in applied else "pending"
            print(f"  [{status:8}] {full}")
        return

    if "--down" in sys.argv:
        try:
            idx = sys.argv.index("--down") + 1
            target = sys.argv[idx]
        except (ValueError, IndexError):
            print("Uso: python -m migrations.runner --down <numero>")
            return
        for num, nm, fn in reversed(migrations):
            full = f"{num}_{nm}"
            if num == target and full in applied:
                mod = importlib.import_module(f"migrations.{fn[:-3]}")
                _revert(full, mod)
                return
        print(f"Migração {target} não encontrada ou não aplicada")
        return

    for num, nm, fn in migrations:
        full = f"{num}_{nm}"
        if full not in applied:
            mod = importlib.import_module(f"migrations.{fn[:-3]}")
            _apply(full, mod)


if __name__ == "__main__":
    run()
