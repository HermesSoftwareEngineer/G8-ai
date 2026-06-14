import json
import logging
import os
from datetime import datetime, date, timedelta
from app.config import Config

# LangSmith tracing — must be set before langchain imports
if Config.LANGSMITH_API_KEY:
    os.environ.setdefault("LANGCHAIN_API_KEY", Config.LANGSMITH_API_KEY)
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_PROJECT", Config.LANGCHAIN_PROJECT)

from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.postgres import PostgresSaver

from app.models.database import get_db, db_insert, db_update
from app.utils.md_reader import read_shop_info, read_prompt
from app.utils.datetime_utils import FORTALEZA_TZ, fortaleza_to_utc, now_fortaleza
from app.services.scheduler import get_available_slots, is_slot_available
from app.services.notifications import send_confirmation, send_cancellation

logger = logging.getLogger(__name__)

_llm: ChatOpenAI | None = None
_checkpointer_ready = False

RESET_COMMANDS = {"/reset", "/reiniciar", "reiniciar"}


def _db_url() -> str:
    """Append connect_timeout so a bad/unreachable DB fails fast instead of hanging."""
    url = Config.SUPABASE_DB_URL or ""
    if url and "connect_timeout" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}connect_timeout=10"
    return url


# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------

def _get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            api_key=Config.DEEPSEEK_API_KEY,
            base_url=Config.DEEPSEEK_BASE_URL,
            model="deepseek-v4-flash",
            max_tokens=1024,
        )
    return _llm


def init_checkpointer() -> None:
    """Create LangGraph checkpoint tables in Supabase. Call once at app startup."""
    global _checkpointer_ready
    if _checkpointer_ready or not Config.SUPABASE_DB_URL:
        return
    try:
        with PostgresSaver.from_conn_string(_db_url()) as cp:
            cp.setup()
        _checkpointer_ready = True
        logger.info("LangGraph PostgresSaver initialized")
    except Exception as e:
        logger.error("Falha ao inicializar checkpointer: %s", e)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def _build_system_prompt(phone: str, customer: dict | None) -> str:
    ai_cfg = _load_ai_config()
    bot_name = ai_cfg.get("bot_name", "G8 AI")
    customer_info = (
        f"Nome: {customer['name']}, Telefone: {phone}"
        if customer
        else f"Número: {phone} (cliente novo)"
    )
    return read_prompt().format(bot_name=bot_name, customer_info=customer_info)


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _load_services() -> str:
    db = get_db()
    rows = db.table("services").select("name, description, duration_minutes, price").eq("is_active", True).execute().data or []
    if not rows:
        return "Nenhum serviço cadastrado."
    return "\n".join(
        f"- {s['name']} ({s['duration_minutes']}min) — R$ {s['price']:.2f}"
        + (f": {s['description']}" if s.get("description") else "")
        for s in rows
    )


def _load_barbers() -> str:
    db = get_db()
    rows = db.table("barbers").select("name, bio").eq("is_active", True).execute().data or []
    if not rows:
        return "Nenhum barbeiro cadastrado."
    return "\n".join(
        f"- {b['name']}" + (f": {b['bio']}" if b.get("bio") else "")
        for b in rows
    )


def _load_ai_config() -> dict:
    db = get_db()
    rows = db.table("ai_config").select("key, value").execute().data or []
    return {r["key"]: r["value"] for r in rows}


def _get_customer(phone: str) -> dict | None:
    db = get_db()
    result = db.table("customers").select("*").eq("phone_whatsapp", phone).execute()
    return result.data[0] if result.data else None


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def _get_or_create_session(phone: str) -> dict:
    db = get_db()
    result = db.table("conversation_sessions").select("*").eq("phone_whatsapp", phone).execute()
    if result.data:
        return result.data[0]
    return db_insert("conversation_sessions", {
        "phone_whatsapp": phone,
        "context": [],
        "state": "idle",
        "mode": "ai",
    })


def get_session_mode(phone: str) -> str:
    """Returns 'ai' or 'human'. Defaults to 'ai' if no session exists."""
    db = get_db()
    result = db.table("conversation_sessions").select("mode").eq("phone_whatsapp", phone).execute()
    if result.data:
        return result.data[0].get("mode") or "ai"
    return "ai"


# ---------------------------------------------------------------------------
# Handoff
# ---------------------------------------------------------------------------

def _do_handoff(phone: str, reason: str) -> None:
    db = get_db()
    result = db.table("conversation_sessions").select("id").eq("phone_whatsapp", phone).execute()
    if result.data:
        db.table("conversation_sessions").update({
            "mode": "human",
            "handoff_reason": reason,
            "handoff_at": "now()",
            "last_activity": "now()",
        }).eq("phone_whatsapp", phone).execute()
    else:
        db_insert("conversation_sessions", {
            "phone_whatsapp": phone,
            "mode": "human",
            "handoff_reason": reason,
            "context": [],
            "state": "idle",
        })

    try:
        ai_cfg = _load_ai_config()
        operator_phone = ai_cfg.get("operator_whatsapp")
        if operator_phone:
            from app.services.whatsapp import send_text
            customer = _get_customer(phone)
            customer_name = customer["name"] if customer else phone
            send_text(
                operator_phone,
                f"⚠️ *Atendimento Humano Solicitado*\n"
                f"Cliente: {customer_name}\n"
                f"Número: {phone}\n"
                f"Motivo: {reason}",
            )
    except Exception as e:
        logger.error("Erro ao notificar operador: %s", e)


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

def reset_session(phone: str) -> None:
    """Clear LangGraph thread and reset session mode to 'ai'."""
    if Config.SUPABASE_DB_URL:
        try:
            with PostgresSaver.from_conn_string(_db_url()) as checkpointer:
                checkpointer.delete_thread(phone)
        except Exception as e:
            logger.error("Erro ao limpar checkpoints LangGraph: %s", e)

    db = get_db()
    result = db.table("conversation_sessions").select("id").eq("phone_whatsapp", phone).execute()
    if result.data:
        db.table("conversation_sessions").update({
            "mode": "ai",
            "assigned_to": None,
            "handoff_reason": None,
            "handoff_at": None,
            "context": [],
            "state": "idle",
            "last_activity": "now()",
        }).eq("phone_whatsapp", phone).execute()


# ---------------------------------------------------------------------------
# Tool factory (closure captures phone context)
# ---------------------------------------------------------------------------

def _build_tools(phone: str) -> list:
    @tool
    def get_shop_info() -> str:
        """Retorna informações da barbearia: endereço, horário de funcionamento, políticas e redes sociais."""
        return read_shop_info()

    @tool
    def get_services() -> str:
        """Retorna a lista de serviços disponíveis com nome, duração e preço."""
        return _load_services()

    @tool
    def get_barbers() -> str:
        """Retorna a lista de barbeiros disponíveis com nome e bio."""
        return _load_barbers()

    @tool
    def check_availability(date: str, service_name: str, barber_name: str = "") -> str:
        """Verifica horários disponíveis para um barbeiro em uma data específica.

        Args:
            date: Data no formato YYYY-MM-DD
            service_name: Nome do serviço desejado
            barber_name: Nome do barbeiro (opcional — omitir para verificar todos)
        """
        return json.dumps(_tool_check_availability({
            "date": date, "service_name": service_name, "barber_name": barber_name,
        }), ensure_ascii=False)

    @tool
    def create_appointment(
        barber_name: str,
        service_name: str,
        date: str,
        time: str,
        customer_name: str = "",
    ) -> str:
        """Cria um agendamento após confirmação explícita do cliente.

        Args:
            barber_name: Nome do barbeiro escolhido
            service_name: Nome do serviço escolhido
            date: Data no formato YYYY-MM-DD
            time: Horário no formato HH:MM
            customer_name: Nome do cliente (obrigatório se for novo)
        """
        customer = _get_customer(phone)
        return json.dumps(_tool_create_appointment(
            {"barber_name": barber_name, "service_name": service_name,
             "date": date, "time": time, "customer_name": customer_name,
             "customer_phone": phone},
            phone, customer,
        ), ensure_ascii=False)

    @tool
    def cancel_appointment(appointment_id: str = "") -> str:
        """Cancela o próximo agendamento ativo do cliente após confirmação.

        Args:
            appointment_id: ID do agendamento (opcional — cancela o próximo se omitido)
        """
        return json.dumps(_tool_cancel_appointment(
            {"customer_phone": phone, "appointment_id": appointment_id}
        ), ensure_ascii=False)

    @tool
    def register_customer(name: str) -> str:
        """Registra um novo cliente no sistema usando o número de WhatsApp atual.

        Args:
            name: Nome completo do cliente
        """
        return json.dumps(_tool_register_customer({"name": name, "phone": phone}), ensure_ascii=False)

    @tool
    def get_customer_appointments() -> str:
        """Busca os agendamentos futuros do cliente atual."""
        return json.dumps(_tool_get_customer_appointments({"customer_phone": phone}), ensure_ascii=False)

    @tool
    def transfer_to_human(reason: str) -> str:
        """Transfere o atendimento para um operador humano.

        Use quando: cliente pede explicitamente para falar com humano, situação muito
        complexa ou sensível, reclamação grave, ou qualquer caso que exige julgamento humano.

        Args:
            reason: Motivo da transferência (será enviado ao operador)
        """
        _do_handoff(phone, reason)
        return "Transferência realizada. O operador foi notificado e assumirá o atendimento em breve."

    return [
        get_shop_info, get_services, get_barbers, check_availability,
        create_appointment, cancel_appointment, register_customer,
        get_customer_appointments, transfer_to_human,
    ]


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------

def process_message(phone: str, text: str) -> str:
    customer = _get_customer(phone)
    system_prompt = _build_system_prompt(phone, customer)
    tools = _build_tools(phone)

    if not Config.SUPABASE_DB_URL:
        logger.warning("SUPABASE_DB_URL não configurado — usando fallback sem checkpointer")
        return _process_without_checkpointer(system_prompt, tools, phone, text)

    try:
        with PostgresSaver.from_conn_string(_db_url()) as checkpointer:
            graph = create_react_agent(
                _get_llm(),
                tools,
                checkpointer=checkpointer,
                prompt=system_prompt,
            )
            config = {"configurable": {"thread_id": phone}}
            result = graph.invoke(
                {"messages": [HumanMessage(content=text)]},
                config=config,
            )
    except Exception as e:
        logger.error("Erro no LangGraph: %s", e, exc_info=True)
        return "Eita, deu um erro aqui. Pode repetir? 🙏"

    messages = result.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            return str(msg.content).strip()
    return "Posso te ajudar com mais alguma coisa? 😊"


def _process_without_checkpointer(system_prompt: str, tools: list, phone: str, text: str) -> str:
    """Fallback: runs without postgres checkpointer (no persistent history)."""
    graph = create_react_agent(_get_llm(), tools, state_modifier=system_prompt)
    config = {"configurable": {"thread_id": phone}}
    result = graph.invoke({"messages": [HumanMessage(content=text)]}, config=config)
    messages = result.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            return str(msg.content).strip()
    return "Posso te ajudar com mais alguma coisa? 😊"


# ---------------------------------------------------------------------------
# Tool implementations (unchanged logic from original)
# ---------------------------------------------------------------------------

def _tool_check_availability(inputs: dict) -> dict:
    db = get_db()
    service_name = inputs["service_name"]
    date_str = inputs["date"]
    barber_name = inputs.get("barber_name")

    svc = db.table("services").select("id, duration_minutes").ilike("name", f"%{service_name}%").eq("is_active", True).execute()
    if not svc.data:
        return {"error": f"Serviço '{service_name}' não encontrado."}
    duration = svc.data[0]["duration_minutes"]

    query = db.table("barbers").select("id, name").eq("is_active", True)
    if barber_name:
        query = query.ilike("name", f"%{barber_name}%")
    barbers = query.execute().data or []
    if not barbers:
        return {"error": "Nenhum barbeiro encontrado."}

    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        return {"error": f"Data inválida: {date_str}"}

    availability = {}
    for b in barbers:
        slots = get_available_slots(b["id"], target_date, duration)
        if slots:
            availability[b["name"]] = slots

    if not availability:
        return {"available": False, "message": "Sem horários disponíveis nesta data."}
    return {"available": True, "date": date_str, "slots_by_barber": availability}


def _tool_create_appointment(inputs: dict, phone: str, customer: dict | None) -> dict:
    db = get_db()

    if not customer:
        customer_name = inputs.get("customer_name")
        if not customer_name:
            return {"error": "Nome do cliente necessário para o primeiro agendamento."}
        customer = db_insert("customers", {"name": customer_name, "phone_whatsapp": phone})

    barber_res = db.table("barbers").select("id, name").ilike("name", f"%{inputs['barber_name']}%").eq("is_active", True).execute()
    if not barber_res.data:
        return {"error": f"Barbeiro '{inputs['barber_name']}' não encontrado."}
    barber = barber_res.data[0]

    svc_res = db.table("services").select("id, name, duration_minutes, price").ilike("name", f"%{inputs['service_name']}%").eq("is_active", True).execute()
    if not svc_res.data:
        return {"error": f"Serviço '{inputs['service_name']}' não encontrado."}
    service = svc_res.data[0]

    try:
        local_dt = FORTALEZA_TZ.localize(datetime.strptime(f"{inputs['date']} {inputs['time']}", "%Y-%m-%d %H:%M"))
    except ValueError:
        return {"error": f"Data/hora inválida: {inputs['date']} {inputs['time']}"}

    if not is_slot_available(barber["id"], local_dt.replace(tzinfo=None), service["duration_minutes"]):
        return {"error": "Este horário não está mais disponível. Por favor, escolha outro."}

    start_utc = fortaleza_to_utc(local_dt)
    end_utc = start_utc + timedelta(minutes=service["duration_minutes"])

    appt = db_insert("appointments", {
        "customer_id": customer["id"],
        "barber_id": barber["id"],
        "service_id": service["id"],
        "start_datetime": start_utc.isoformat(),
        "end_datetime": end_utc.isoformat(),
        "status": "confirmed",
    })

    try:
        send_confirmation(appt["id"])
    except Exception as e:
        logger.error("Erro ao enviar notificações: %s", e)

    return {
        "success": True,
        "appointment_id": appt["id"],
        "barber": barber["name"],
        "service": service["name"],
        "date": inputs["date"],
        "time": inputs["time"],
        "price": float(service["price"]),
    }


def _tool_cancel_appointment(inputs: dict) -> dict:
    import datetime as dt
    db = get_db()
    phone = inputs["customer_phone"]

    customer_res = db.table("customers").select("id").eq("phone_whatsapp", phone).execute()
    if not customer_res.data:
        return {"error": "Cliente não encontrado."}
    customer_id = customer_res.data[0]["id"]

    appointment_id = inputs.get("appointment_id")
    if appointment_id:
        appt_res = db.table("appointments").select("id, status").eq("id", appointment_id).eq("customer_id", customer_id).execute()
    else:
        now_utc = now_fortaleza().astimezone(dt.timezone.utc)
        appt_res = (
            db.table("appointments")
            .select("id, status")
            .eq("customer_id", customer_id)
            .in_("status", ["pending", "confirmed"])
            .gte("start_datetime", now_utc.isoformat())
            .order("start_datetime")
            .limit(1)
            .execute()
        )

    if not appt_res.data:
        return {"error": "Nenhum agendamento ativo encontrado."}

    appt = appt_res.data[0]
    if appt["status"] == "cancelled":
        return {"error": "Este agendamento já está cancelado."}

    db_update("appointments", appt["id"], {"status": "cancelled"})

    try:
        send_cancellation(appt["id"])
    except Exception as e:
        logger.error("Erro ao notificar cancelamento: %s", e)

    return {"success": True, "cancelled_id": appt["id"]}


def _tool_register_customer(inputs: dict) -> dict:
    existing = _get_customer(inputs["phone"])
    if existing:
        return {"success": True, "customer_id": existing["id"], "already_existed": True}
    customer = db_insert("customers", {"name": inputs["name"], "phone_whatsapp": inputs["phone"]})
    return {"success": True, "customer_id": customer["id"], "already_existed": False}


def _tool_get_customer_appointments(inputs: dict) -> dict:
    import datetime as dt
    from app.utils.datetime_utils import format_datetime_br, parse_iso
    db = get_db()

    customer_res = db.table("customers").select("id").eq("phone_whatsapp", inputs["customer_phone"]).execute()
    if not customer_res.data:
        return {"appointments": []}
    customer_id = customer_res.data[0]["id"]

    now_utc = now_fortaleza().astimezone(dt.timezone.utc)
    appts = (
        db.table("appointments")
        .select("id, start_datetime, status, barbers(name), services(name)")
        .eq("customer_id", customer_id)
        .in_("status", ["pending", "confirmed"])
        .gte("start_datetime", now_utc.isoformat())
        .order("start_datetime")
        .execute()
        .data or []
    )

    return {
        "appointments": [
            {
                "id": a["id"],
                "datetime": format_datetime_br(parse_iso(a["start_datetime"])),
                "barber": a["barbers"]["name"],
                "service": a["services"]["name"],
                "status": a["status"],
            }
            for a in appts
        ]
    }
