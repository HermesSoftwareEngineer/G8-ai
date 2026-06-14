import logging
import ssl
import httpx
from supabase import create_client, Client
from app.config import Config

logger = logging.getLogger(__name__)

_client: Client | None = None

# Monkey-patch httpx para ignorar SSL no DEV (Windows sem cert corporativo)
_no_verify_transport = httpx.HTTPTransport(verify=False)
_original_init = httpx.Client.__init__

def _patched_init(self, *args, **kwargs):
    kwargs.setdefault("transport", _no_verify_transport)
    _original_init(self, *args, **kwargs)

httpx.Client.__init__ = _patched_init


def get_db() -> Client:
    global _client
    if _client is None:
        if not Config.SUPABASE_URL or not Config.SUPABASE_SERVICE_KEY:
            raise RuntimeError("SUPABASE_URL e SUPABASE_SERVICE_KEY são obrigatórios")
        _client = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)
        logger.info("Supabase client iniciado")
    return _client


# ---------------------------------------------------------------------------
# Helpers genéricos
# ---------------------------------------------------------------------------

def db_select(table: str, filters: dict = None, columns: str = "*") -> list:
    db = get_db()
    query = db.table(table).select(columns)
    if filters:
        for key, val in filters.items():
            query = query.eq(key, val)
    result = query.execute()
    return result.data or []


def db_insert(table: str, data: dict) -> dict:
    db = get_db()
    result = db.table(table).insert(data).execute()
    return result.data[0] if result.data else {}


def db_update(table: str, record_id: str, data: dict) -> dict:
    db = get_db()
    result = db.table(table).update(data).eq("id", record_id).execute()
    return result.data[0] if result.data else {}


def db_delete(table: str, record_id: str) -> bool:
    db = get_db()
    db.table(table).delete().eq("id", record_id).execute()
    return True


def db_upsert(table: str, data: dict, on_conflict: str = "id") -> dict:
    db = get_db()
    result = db.table(table).upsert(data, on_conflict=on_conflict).execute()
    return result.data[0] if result.data else {}
