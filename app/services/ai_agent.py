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

from app.models.database import get_db, db_insert, db_update
from app.utils.md_reader import read_shop_info, read_prompt
from app.utils.datetime_utils import FORTALEZA_TZ, fortaleza_to_utc, now_fortaleza
from app.services.scheduler import get_available_slots, is_slot_available
from app.services.notifications import send_confirmation, send_cancellation

logger = logging.getLogger(__name__)

_llm: ChatOpenAI | None = None

# Active messages kept in context per invocation; older messages become the rolling summary.
CONTEXT_WINDOW = 10

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
    """No-op — conversation history is now stored in the conversation_messages table."""
    pass


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def _build_system_prompt() -> str:
    ai_cfg = _load_ai_config()
    bot_name = ai_cfg.get("bot_name", "G8 AI")
    return read_prompt().format(bot_name=bot_name)


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
# Message history helpers
# ---------------------------------------------------------------------------

def _save_message(phone: str, role: str, content: str) -> None:
    db = get_db()
    db.table("conversation_messages").insert({
        "phone_whatsapp": phone,
        "role": role,
        "content": content,
    }).execute()


def _count_messages(phone: str) -> int:
    db = get_db()
    result = (
        db.table("conversation_messages")
        .select("id", count="exact")
        .eq("phone_whatsapp", phone)
        .execute()
    )
    return result.count or 0


def _build_message_history(phone: str) -> list:
    """Returns summary context (if any) followed by the last CONTEXT_WINDOW messages."""
    db = get_db()

    sess = db.table("conversation_sessions").select("summary").eq("phone_whatsapp", phone).execute()
    summary = (sess.data[0].get("summary") or "") if sess.data else ""

    result = (
        db.table("conversation_messages")
        .select("role, content")
        .eq("phone_whatsapp", phone)
        .order("created_at", desc=True)
        .limit(CONTEXT_WINDOW)
        .execute()
    )
    recent = list(reversed(result.data or []))

    messages: list = []
    if summary:
        messages.append(HumanMessage(content=f"[Resumo do histórico desta conversa]\n{summary}"))
        messages.append(AIMessage(content="Contexto anterior carregado. Estou ciente do histórico desta conversa."))

    for m in recent:
        cls = HumanMessage if m["role"] == "human" else AIMessage
        messages.append(cls(content=m["content"]))

    return messages


# ---------------------------------------------------------------------------
# Summarization
# ---------------------------------------------------------------------------

def _generate_summary(messages_text: str) -> str:
    """Use LLM to summarize a conversation, extracting key facts."""
    llm = _get_llm()
    prompt = (
        "Resuma a seguinte conversa de atendimento da Barbershop G8. "
        "Seja conciso e extraia apenas informacoes factuais.\n\n"
        "Inclua no resumo:\n"
        "- Nome do cliente (se informado)\n"
        "- Servicos de interesse ou contratados\n"
        "- Agendamentos realizados (datas, horarios, barbeiros, servicos)\n"
        "- Preferencias e observacoes relevantes\n"
        "- Estado atual: o que ficou pendente ou qual foi o ultimo assunto\n\n"
        "Conversa:\n"
        f"{messages_text}\n\n"
        "Resumo:"
    )
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        return str(response.content).strip()
    except Exception as e:
        logger.error("Erro ao gerar resumo: %s", e)
        return ""


def _update_summary(phone: str) -> None:
    """Incrementally update the summary to cover all messages beyond the active window."""
    db = get_db()
    total = _count_messages(phone)
    if total <= CONTEXT_WINDOW:
        return

    sess = (
        db.table("conversation_sessions")
        .select("summary, summarized_count")
        .eq("phone_whatsapp", phone)
        .execute()
    )
    if not sess.data:
        return

    session = sess.data[0]
    summarized_count = session.get("summarized_count") or 0
    old_summary = session.get("summary") or ""

    # How many messages now sit outside the active window?
    new_end = total - CONTEXT_WINDOW  # exclusive upper index of messages to summarize
    if new_end <= summarized_count:
        return  # Nothing new fell out of the window

    new_msgs = (
        db.table("conversation_messages")
        .select("role, content")
        .eq("phone_whatsapp", phone)
        .order("created_at", desc=False)
        .range(summarized_count, new_end - 1)
        .execute()
        .data or []
    )
    if not new_msgs:
        return

    new_text = "\n".join(
        f"{'Cliente' if m['role'] == 'human' else 'Atendente'}: {m['content']}"
        for m in new_msgs
    )

    full_text = (
        f"[Resumo anterior]\n{old_summary}\n\n[Continuação da conversa]\n{new_text}"
        if old_summary else new_text
    )
    new_summary = _generate_summary(full_text)

    db.table("conversation_sessions").update({
        "summary": new_summary,
        "summarized_count": new_end,
        "last_activity": "now()",
    }).eq("phone_whatsapp", phone).execute()


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

def clear_thread(phone: str) -> None:
    """Clear conversation history for a phone number."""
    db = get_db()
    db.table("conversation_messages").delete().eq("phone_whatsapp", phone).execute()
    db.table("conversation_sessions").update({
        "summary": None,
        "summarized_count": 0,
        "message_count": 0,
    }).eq("phone_whatsapp", phone).execute()


def reset_session(phone: str) -> None:
    """Clear conversation history and reset session to AI mode."""
    clear_thread(phone)
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
            "message_count": 0,
            "summary": None,
            "summarized_count": 0,
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

    @tool
    def get_conversation_summary() -> str:
        """Retorna o resumo de conversas anteriores com este cliente, se disponivel.
        Use quando precisar relembrar o historico, preferencias ou agendamentos passados."""
        db = get_db()
        result = db.table("conversation_sessions").select("summary").eq("phone_whatsapp", phone).execute()
        if result.data and result.data[0].get("summary"):
            return result.data[0]["summary"]
        return "Nenhum historico anterior encontrado para este cliente."

    @tool
    def contact_supervisor(message: str) -> str:
        """Envia uma mensagem para o supervisor/operador humano.
        Use para: tirar duvidas sobre procedimentos, informar situacoes importantes,
        relatar problemas tecnicos, ou qualquer caso que precise de orientacao humana
        sem transferir o atendimento.

        Args:
            message: Mensagem que sera enviada ao supervisor
        """
        ai_cfg = _load_ai_config()
        operator_phone = ai_cfg.get("operator_whatsapp")
        if not operator_phone:
            return "Numero do supervisor nao configurado. Avise o cliente que houve um problema."
        customer = _get_customer(phone)
        customer_name = customer["name"] if customer else phone
        full_msg = (
            f"\U0001f4e9 *Mensagem do Agente IA*\n"
            f"Cliente: {customer_name}\n"
            f"Numero: {phone}\n\n"
            f"{message}"
        )
        from app.services.whatsapp import send_text
        send_text(operator_phone, full_msg)
        return "Mensagem enviada ao supervisor com sucesso."

    @tool
    def read_conversation_history(page: int = 1) -> str:
        """Lê mensagens anteriores da conversa, de 10 em 10.

        As últimas 10 mensagens já estão no seu contexto atual.
        Use page=1 para as 10 mensagens imediatamente anteriores,
        page=2 para as 10 anteriores a essas, e assim por diante.

        Args:
            page: Página do histórico (1 = mensagens 11-20, 2 = mensagens 21-30, etc.)
        """
        if page < 1:
            return "Página inválida. Use page >= 1."
        db = get_db()
        offset = CONTEXT_WINDOW + (page - 1) * CONTEXT_WINDOW
        result = (
            db.table("conversation_messages")
            .select("role, content")
            .eq("phone_whatsapp", phone)
            .order("created_at", desc=True)
            .range(offset, offset + CONTEXT_WINDOW - 1)
            .execute()
        )
        msgs = list(reversed(result.data or []))
        if not msgs:
            return "Não há mensagens anteriores nesta página."
        lines = [f"[Histórico — página {page}]"]
        for m in msgs:
            role = "Cliente" if m["role"] == "human" else "Atendente"
            lines.append(f"{role}: {m['content']}")
        return "\n".join(lines)

    return [
        get_shop_info, get_services, get_barbers, check_availability,
        create_appointment, cancel_appointment, register_customer,
        get_customer_appointments, transfer_to_human, get_conversation_summary,
        contact_supervisor, read_conversation_history,
    ]


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------

def process_message(phone: str, text: str) -> str:
    # Persist the incoming human message before building context
    _save_message(phone, "human", text)

    system_prompt = _build_system_prompt()
    tools = _build_tools(phone)

    # Context: rolling summary (if any) + last CONTEXT_WINDOW messages (includes current)
    history = _build_message_history(phone)

    graph = create_react_agent(_get_llm(), tools, prompt=system_prompt)

    try:
        result = graph.invoke({"messages": history})
    except Exception as e:
        logger.error("Erro no LangGraph: %s", e, exc_info=True)
        return "Eita, deu um erro aqui. Pode repetir? 🙏"

    messages = result.get("messages", [])
    response = "Posso te ajudar com mais alguma coisa? 😊"
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            response = str(msg.content).strip()
            break

    # Persist AI response
    _save_message(phone, "ai", response)

    # Update rolling summary if messages fell outside the active window
    try:
        _update_summary(phone)
    except Exception as e:
        logger.error("Erro ao atualizar resumo: %s", e)

    return response


# ---------------------------------------------------------------------------
# Tool implementations
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
