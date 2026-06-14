import json
import logging
from datetime import datetime, date, timedelta
from openai import OpenAI
from app.config import Config
from app.models.database import get_db, db_insert, db_update
from app.utils.md_reader import read_shop_info
from app.utils.datetime_utils import FORTALEZA_TZ, fortaleza_to_utc, now_fortaleza
from app.services.scheduler import get_available_slots, is_slot_available
from app.services.notifications import send_confirmation, send_cancellation

logger = logging.getLogger(__name__)

_client = OpenAI(
    api_key=Config.DEEPSEEK_API_KEY,
    base_url=Config.DEEPSEEK_BASE_URL,
)

MODEL = "deepseek-v4-flash"
MAX_TOKENS = 1024
MAX_CONTEXT_MESSAGES = 20


# ---------------------------------------------------------------------------
# Session management
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
    })


def _update_session(session_id: str, **fields) -> None:
    db = get_db()
    db.table("conversation_sessions").update({
        "last_activity": "now()",
        **fields,
    }).eq("id", session_id).execute()


def _append_context(ctx: list, role: str, content: str) -> list:
    ctx.append({"role": role, "content": content})
    return ctx[-MAX_CONTEXT_MESSAGES:]


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
# Main entrypoint
# ---------------------------------------------------------------------------

def process_message(phone: str, text: str) -> str:
    session = _get_or_create_session(phone)
    customer = _get_customer(phone)

    ai_cfg = _load_ai_config()
    bot_name = ai_cfg.get("bot_name", "G8 AI")
    customer_info = (
        f"Nome: {customer['name']}, Telefone: {phone}"
        if customer
        else f"Número: {phone} (cliente novo)"
    )

    system_prompt = (
        f"Você é a {bot_name}, atendente virtual da Barbershop G8, em Fortaleza, Ceará.\n"
        f"Seu tom é casual, descontraído e simpático. Você fala português brasileiro natural.\n"
        f"Você pode tirar dúvidas sobre a barbearia e realizar agendamentos.\n\n"
        f"Informações da barbearia:\n{read_shop_info()}\n\n"
        f"Serviços disponíveis:\n{_load_services()}\n\n"
        f"Barbeiros disponíveis:\n{_load_barbers()}\n\n"
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
        f"- Datas e horários devem ser no fuso horário de Fortaleza (UTC-3).\n"
        f"- Use as ferramentas disponíveis para executar ações. Nunca simule ações sem chamar as ferramentas.\n"
    )

    # Build messages list: system + history + new user message
    context: list = session.get("context") or []
    messages = [{"role": "system", "content": system_prompt}] + list(context) + [{"role": "user", "content": text}]

    tools = _define_tools()
    response_text = _run_agent_loop(messages, tools, phone, customer)

    # Persist updated context (without system message)
    new_ctx = _append_context(list(context), "user", text)
    new_ctx = _append_context(new_ctx, "assistant", response_text)
    _update_session(session["id"], context=new_ctx)

    return response_text


# ---------------------------------------------------------------------------
# Tool definitions (OpenAI format)
# ---------------------------------------------------------------------------

def _define_tools() -> list:
    return [
        {
            "type": "function",
            "function": {
                "name": "check_availability",
                "description": "Verifica horários disponíveis para um barbeiro em uma data específica.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "barber_name": {"type": "string", "description": "Nome do barbeiro (opcional — omitir para todos)"},
                        "date": {"type": "string", "description": "Data no formato YYYY-MM-DD"},
                        "service_name": {"type": "string", "description": "Nome do serviço desejado"},
                    },
                    "required": ["date", "service_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_appointment",
                "description": "Cria um agendamento após confirmação do cliente.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "customer_phone": {"type": "string"},
                        "customer_name": {"type": "string", "description": "Nome do cliente (obrigatório se for novo)"},
                        "barber_name": {"type": "string"},
                        "service_name": {"type": "string"},
                        "date": {"type": "string", "description": "YYYY-MM-DD"},
                        "time": {"type": "string", "description": "HH:MM"},
                    },
                    "required": ["customer_phone", "barber_name", "service_name", "date", "time"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "cancel_appointment",
                "description": "Cancela o próximo agendamento ativo do cliente após confirmação.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "customer_phone": {"type": "string"},
                        "appointment_id": {"type": "string", "description": "ID do agendamento (se conhecido)"},
                    },
                    "required": ["customer_phone"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "register_customer",
                "description": "Registra um novo cliente no sistema.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "phone": {"type": "string"},
                    },
                    "required": ["name", "phone"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_customer_appointments",
                "description": "Busca os agendamentos futuros do cliente.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "customer_phone": {"type": "string"},
                    },
                    "required": ["customer_phone"],
                },
            },
        },
    ]


# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------

def _run_agent_loop(messages: list, tools: list, phone: str, customer: dict | None) -> str:
    for _ in range(10):
        response = _client.chat.completions.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )

        choice = response.choices[0]
        message = choice.message

        # No tool calls → final answer
        if not message.tool_calls:
            return (message.content or "").strip() or "Posso te ajudar com mais alguma coisa? 😊"

        # Append assistant turn (with tool_calls)
        messages.append({
            "role": "assistant",
            "content": message.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in message.tool_calls
            ],
        })

        # Execute each tool and append results
        for tc in message.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            result = _execute_tool(tc.function.name, args, phone, customer)

            # Refresh customer after registration
            if tc.function.name == "register_customer" and result.get("success"):
                customer = _get_customer(phone)

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

    return "Desculpa, tive um problema por aqui. Pode repetir o que você queria? 🙏"


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def _execute_tool(name: str, inputs: dict, phone: str, customer: dict | None) -> dict:
    logger.info("Tool: %s | inputs: %s", name, inputs)
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
        return {"error": f"Ferramenta desconhecida: {name}"}
    except Exception as e:
        logger.error("Erro na tool %s: %s", name, e, exc_info=True)
        return {"error": str(e)}


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
