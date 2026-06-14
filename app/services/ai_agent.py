import json
import logging
from datetime import datetime, date
import anthropic
from app.config import Config
from app.models.database import get_db, db_insert, db_update, db_upsert
from app.utils.md_reader import read_shop_info
from app.utils.datetime_utils import FORTALEZA_TZ, fortaleza_to_utc, now_fortaleza
from app.services.scheduler import get_available_slots, is_slot_available
from app.services.notifications import send_confirmation, send_cancellation

logger = logging.getLogger(__name__)

_anthropic = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1024
MAX_CONTEXT_MESSAGES = 20  # Keep last N messages in session context


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def _get_or_create_session(phone: str) -> dict:
    db = get_db()
    result = db.table("conversation_sessions").select("*").eq("phone_whatsapp", phone).execute()
    if result.data:
        return result.data[0]
    new_session = db_insert("conversation_sessions", {
        "phone_whatsapp": phone,
        "context": [],
        "state": "idle",
    })
    return new_session


def _update_session(session_id: str, **fields) -> None:
    db = get_db()
    db.table("conversation_sessions").update({
        "last_activity": "now()",
        **fields,
    }).eq("id", session_id).execute()


def _append_context(session: dict, role: str, content: str) -> list:
    ctx: list = session.get("context") or []
    ctx.append({"role": role, "content": content})
    # Trim to last MAX_CONTEXT_MESSAGES
    return ctx[-MAX_CONTEXT_MESSAGES:]


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _load_services() -> str:
    db = get_db()
    services = db.table("services").select("name, description, duration_minutes, price").eq("is_active", True).execute().data or []
    if not services:
        return "Nenhum serviço cadastrado."
    lines = [f"- {s['name']} ({s['duration_minutes']}min) — R$ {s['price']:.2f}" + (f": {s['description']}" if s.get("description") else "") for s in services]
    return "\n".join(lines)


def _load_barbers() -> str:
    db = get_db()
    barbers = db.table("barbers").select("name, bio").eq("is_active", True).execute().data or []
    if not barbers:
        return "Nenhum barbeiro cadastrado."
    lines = [f"- {b['name']}" + (f": {b['bio']}" if b.get("bio") else "") for b in barbers]
    return "\n".join(lines)


def _load_ai_config() -> dict:
    db = get_db()
    rows = db.table("ai_config").select("key, value").execute().data or []
    return {r["key"]: r["value"] for r in rows}


def _get_or_create_customer(phone: str) -> dict | None:
    db = get_db()
    result = db.table("customers").select("*").eq("phone_whatsapp", phone).execute()
    return result.data[0] if result.data else None


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------

def process_message(phone: str, text: str) -> str:
    session = _get_or_create_session(phone)
    customer = _get_or_create_customer(phone)

    # Build system prompt
    ai_cfg = _load_ai_config()
    shop_info = read_shop_info()
    services_txt = _load_services()
    barbers_txt = _load_barbers()
    bot_name = ai_cfg.get("bot_name", "G8 AI")
    customer_info = f"Nome: {customer['name']}, Telefone: {phone}" if customer else f"Número: {phone} (cliente novo)"

    system_prompt = (
        f"Você é a {bot_name}, atendente virtual da Barbershop G8, em Fortaleza, Ceará.\n"
        f"Seu tom é casual, descontraído e simpático. Você fala português brasileiro natural.\n"
        f"Você pode tirar dúvidas sobre a barbearia e realizar agendamentos.\n\n"
        f"Informações da barbearia:\n{shop_info}\n\n"
        f"Serviços disponíveis:\n{services_txt}\n\n"
        f"Barbeiros disponíveis:\n{barbers_txt}\n\n"
        f"Cliente atual:\n{customer_info}\n\n"
        f"Estado atual da conversa: {session['state']}\n\n"
        f"Regras:\n"
        f"- Nunca invente informações. Se não souber, diga que vai verificar.\n"
        f"- Para agendamentos, colete: serviço desejado, barbeiro (ou qualquer disponível), data e horário.\n"
        f"- Confirme sempre antes de finalizar o agendamento.\n"
        f"- Ao confirmar agendamento, informe todos os detalhes claramente.\n"
        f"- Se o cliente quiser cancelar, confirme antes de cancelar.\n"
        f"- Mantenha respostas curtas e diretas para WhatsApp.\n"
        f"- Quando o cliente for novo e quiser agendar, pergunte o nome dele primeiro.\n"
        f"- Datas e horários devem ser no fuso horário de Fortaleza (UTC-3).\n\n"
        f"IMPORTANTE: Quando precisar executar ações (criar agendamento, cancelar, verificar disponibilidade, "
        f"registrar cliente), use as ferramentas disponíveis. Nunca simule ações sem chamar as ferramentas.\n"
    )

    # Build messages list
    context: list = session.get("context") or []
    messages = list(context) + [{"role": "user", "content": text}]

    # Define tools for the AI
    tools = _define_tools()

    response_text = _run_agent_loop(system_prompt, messages, tools, session, phone, customer)

    # Update session context
    new_ctx = _append_context(session, "user", text)
    new_ctx = _append_context({"context": new_ctx}, "assistant", response_text)
    _update_session(session["id"], context=new_ctx)

    return response_text


# ---------------------------------------------------------------------------
# Tool definitions & execution
# ---------------------------------------------------------------------------

def _define_tools() -> list:
    return [
        {
            "name": "check_availability",
            "description": "Verifica horários disponíveis para um barbeiro em uma data específica.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "barber_name": {"type": "string", "description": "Nome do barbeiro"},
                    "date": {"type": "string", "description": "Data no formato YYYY-MM-DD"},
                    "service_name": {"type": "string", "description": "Nome do serviço desejado"},
                },
                "required": ["date", "service_name"],
            },
        },
        {
            "name": "create_appointment",
            "description": "Cria um agendamento confirmado pelo cliente.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "customer_phone": {"type": "string"},
                    "customer_name": {"type": "string", "description": "Nome do cliente (necessário se for novo)"},
                    "barber_name": {"type": "string"},
                    "service_name": {"type": "string"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "time": {"type": "string", "description": "HH:MM"},
                },
                "required": ["customer_phone", "barber_name", "service_name", "date", "time"],
            },
        },
        {
            "name": "cancel_appointment",
            "description": "Cancela o próximo agendamento ativo do cliente.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "customer_phone": {"type": "string"},
                    "appointment_id": {"type": "string", "description": "ID do agendamento (se conhecido)"},
                },
                "required": ["customer_phone"],
            },
        },
        {
            "name": "register_customer",
            "description": "Registra um novo cliente no sistema.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "phone": {"type": "string"},
                },
                "required": ["name", "phone"],
            },
        },
        {
            "name": "get_customer_appointments",
            "description": "Busca os agendamentos futuros do cliente.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "customer_phone": {"type": "string"},
                },
                "required": ["customer_phone"],
            },
        },
    ]


def _run_agent_loop(system: str, messages: list, tools: list, session: dict, phone: str, customer: dict | None) -> str:
    """Run the Claude agentic loop handling tool calls."""
    for _ in range(10):  # Max 10 iterations to prevent infinite loops
        response = _anthropic.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=messages,
            tools=tools,
        )

        # Collect text blocks
        text_parts = [b.text for b in response.content if hasattr(b, "text")]
        tool_uses = [b for b in response.content if b.type == "tool_use"]

        if response.stop_reason == "end_turn" or not tool_uses:
            return "\n".join(text_parts).strip() or "Posso te ajudar com mais alguma coisa? 😊"

        # Append assistant turn with all content blocks
        messages.append({"role": "assistant", "content": response.content})

        # Execute tools
        tool_results = []
        for tool_use in tool_uses:
            result = _execute_tool(tool_use.name, tool_use.input, phone, customer, session)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": json.dumps(result, ensure_ascii=False),
            })
            # Refresh customer after potential registration
            if tool_use.name == "register_customer":
                customer = _get_or_create_customer(phone)

        messages.append({"role": "user", "content": tool_results})

    return "Desculpa, tive um problema por aqui. Pode repetir o que você queria? 🙏"


def _execute_tool(name: str, inputs: dict, phone: str, customer: dict | None, session: dict) -> dict:
    logger.info("Tool chamada: %s | inputs: %s", name, inputs)
    try:
        if name == "check_availability":
            return _tool_check_availability(inputs)
        elif name == "create_appointment":
            return _tool_create_appointment(inputs, phone, customer)
        elif name == "cancel_appointment":
            return _tool_cancel_appointment(inputs)
        elif name == "register_customer":
            return _tool_register_customer(inputs)
        elif name == "get_customer_appointments":
            return _tool_get_customer_appointments(inputs)
        else:
            return {"error": f"Ferramenta desconhecida: {name}"}
    except Exception as e:
        logger.error("Erro na tool %s: %s", name, e, exc_info=True)
        return {"error": str(e)}


def _tool_check_availability(inputs: dict) -> dict:
    db = get_db()
    service_name = inputs["service_name"]
    date_str = inputs["date"]
    barber_name = inputs.get("barber_name")

    # Find service
    svc_result = db.table("services").select("id, duration_minutes").ilike("name", f"%{service_name}%").eq("is_active", True).execute()
    if not svc_result.data:
        return {"error": f"Serviço '{service_name}' não encontrado."}
    service = svc_result.data[0]
    duration = service["duration_minutes"]

    # Find barbers
    if barber_name:
        barbers_result = db.table("barbers").select("id, name").ilike("name", f"%{barber_name}%").eq("is_active", True).execute()
    else:
        barbers_result = db.table("barbers").select("id, name").eq("is_active", True).execute()

    if not barbers_result.data:
        return {"error": "Nenhum barbeiro encontrado."}

    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        return {"error": f"Data inválida: {date_str}"}

    availability = {}
    for barber in barbers_result.data:
        slots = get_available_slots(barber["id"], target_date, duration)
        if slots:
            availability[barber["name"]] = slots

    if not availability:
        return {"available": False, "message": "Sem horários disponíveis nesta data."}

    return {"available": True, "date": date_str, "slots_by_barber": availability}


def _tool_create_appointment(inputs: dict, phone: str, customer: dict | None) -> dict:
    db = get_db()
    barber_name = inputs["barber_name"]
    service_name = inputs["service_name"]
    date_str = inputs["date"]
    time_str = inputs["time"]
    customer_name = inputs.get("customer_name")

    # Ensure customer exists
    if not customer:
        if not customer_name:
            return {"error": "Nome do cliente necessário para o primeiro agendamento."}
        customer = db_insert("customers", {"name": customer_name, "phone_whatsapp": phone})

    # Find barber
    barber_res = db.table("barbers").select("id, name").ilike("name", f"%{barber_name}%").eq("is_active", True).execute()
    if not barber_res.data:
        return {"error": f"Barbeiro '{barber_name}' não encontrado."}
    barber = barber_res.data[0]

    # Find service
    svc_res = db.table("services").select("id, name, duration_minutes, price").ilike("name", f"%{service_name}%").eq("is_active", True).execute()
    if not svc_res.data:
        return {"error": f"Serviço '{service_name}' não encontrado."}
    service = svc_res.data[0]

    # Parse datetime in Fortaleza TZ
    try:
        local_dt = FORTALEZA_TZ.localize(datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M"))
    except ValueError:
        return {"error": f"Data/hora inválida: {date_str} {time_str}"}

    if not is_slot_available(barber["id"], local_dt.replace(tzinfo=None), service["duration_minutes"]):
        return {"error": "Este horário não está mais disponível. Por favor, escolha outro."}

    start_utc = fortaleza_to_utc(local_dt)
    from datetime import timedelta
    end_utc = start_utc + timedelta(minutes=service["duration_minutes"])

    appt = db_insert("appointments", {
        "customer_id": customer["id"],
        "barber_id": barber["id"],
        "service_id": service["id"],
        "start_datetime": start_utc.isoformat(),
        "end_datetime": end_utc.isoformat(),
        "status": "confirmed",
    })

    # Send notifications async-style (still synchronous here)
    try:
        send_confirmation(appt["id"])
    except Exception as e:
        logger.error("Erro ao enviar notificações de confirmação: %s", e)

    return {
        "success": True,
        "appointment_id": appt["id"],
        "barber": barber["name"],
        "service": service["name"],
        "date": date_str,
        "time": time_str,
        "price": float(service["price"]),
    }


def _tool_cancel_appointment(inputs: dict) -> dict:
    db = get_db()
    phone = inputs["customer_phone"]
    appointment_id = inputs.get("appointment_id")

    customer_res = db.table("customers").select("id").eq("phone_whatsapp", phone).execute()
    if not customer_res.data:
        return {"error": "Cliente não encontrado."}
    customer_id = customer_res.data[0]["id"]

    if appointment_id:
        appt_res = db.table("appointments").select("id, status").eq("id", appointment_id).eq("customer_id", customer_id).execute()
    else:
        now_utc = now_fortaleza().astimezone(__import__("datetime").timezone.utc)
        appt_res = (
            db.table("appointments")
            .select("id, status, start_datetime")
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
        logger.error("Erro ao enviar notificação de cancelamento: %s", e)

    return {"success": True, "cancelled_id": appt["id"]}


def _tool_register_customer(inputs: dict) -> dict:
    name = inputs["name"]
    phone = inputs["phone"]
    existing = _get_or_create_customer(phone)
    if existing:
        return {"success": True, "customer_id": existing["id"], "already_existed": True}
    customer = db_insert("customers", {"name": name, "phone_whatsapp": phone})
    return {"success": True, "customer_id": customer["id"], "already_existed": False}


def _tool_get_customer_appointments(inputs: dict) -> dict:
    db = get_db()
    phone = inputs["customer_phone"]
    customer_res = db.table("customers").select("id").eq("phone_whatsapp", phone).execute()
    if not customer_res.data:
        return {"appointments": []}
    customer_id = customer_res.data[0]["id"]
    now_utc = now_fortaleza().astimezone(__import__("datetime").timezone.utc)
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
    from app.utils.datetime_utils import format_datetime_br, parse_iso
    result = []
    for a in appts:
        result.append({
            "id": a["id"],
            "datetime": format_datetime_br(parse_iso(a["start_datetime"])),
            "barber": a["barbers"]["name"],
            "service": a["services"]["name"],
            "status": a["status"],
        })
    return {"appointments": result}
