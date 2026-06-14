# G8-AI — API Reference

Base URL (DEV): `http://localhost:5000`

Todos os endpoints (exceto `/health`, `/webhook/whatsapp`, `/api/auth/login`) exigem:
```
Authorization: Bearer <token>
```

---

## Auth

### POST `/api/auth/login`
Autentica o usuário e retorna o token JWT.

**Body**
```json
{ "email": "user@email.com", "password": "senha" }
```

**Response 200**
```json
{
  "token": "eyJ...",
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user": {
    "id": "uuid",
    "name": "Hermes",
    "email": "user@email.com",
    "role_id": "uuid",
    "roles": { "name": "dev" },
    "is_active": true
  }
}
```

---

### POST `/api/auth/refresh`
Renova o token do usuário autenticado.

**Response 200** — mesmo formato do login.

---

### POST `/api/auth/logout`
Invalida a sessão no lado do cliente (JWT é stateless).

**Response 200**
```json
{ "message": "Logout realizado com sucesso" }
```

---

## Dashboard

### GET `/api/dashboard/summary`
Resumo para a tela inicial do painel.

**Response 200**
```json
{
  "today": {
    "total": 8,
    "confirmed": 5,
    "completed": 2,
    "cancelled": 1,
    "pending": 0
  },
  "month": {
    "total": 142,
    "completed": 120,
    "cancelled": 10
  },
  "totals": {
    "customers": 89,
    "barbers": 3
  }
}
```

---

## Agendamentos

### GET `/api/appointments`
Lista agendamentos com filtros opcionais.

**Query params**
| Param | Tipo | Descrição |
|---|---|---|
| `barber_id` | uuid | Filtra por barbeiro |
| `status` | string | `pending \| confirmed \| cancelled \| completed \| no_show` |
| `date_from` | ISO 8601 | Data início |
| `date_to` | ISO 8601 | Data fim |

**Response 200** — array de agendamentos com joins:
```json
[
  {
    "id": "uuid",
    "start_datetime": "2026-06-14T14:00:00+00:00",
    "end_datetime": "2026-06-14T14:30:00+00:00",
    "status": "confirmed",
    "notes": null,
    "customers": { "name": "João", "phone_whatsapp": "5585999990000" },
    "barbers": { "name": "Carlos" },
    "services": { "name": "Corte", "price": 35.00 }
  }
]
```

---

### GET `/api/appointments/:id`
Retorna um agendamento completo com todos os dados relacionados.

---

### POST `/api/appointments`
Cria um agendamento manualmente (pelo painel).

**Body**
```json
{
  "customer_id": "uuid",
  "barber_id": "uuid",
  "service_id": "uuid",
  "start_datetime": "2026-06-14T14:00:00-03:00",
  "end_datetime": "2026-06-14T14:30:00-03:00",
  "status": "confirmed",
  "notes": "opcional",
  "send_notification": true
}
```

**Response 201** — objeto do agendamento criado.

---

### PATCH `/api/appointments/:id/status`
Atualiza o status de um agendamento.

**Body**
```json
{ "status": "completed" }
```

Status válidos: `pending | confirmed | cancelled | completed | no_show`

---

### DELETE `/api/appointments/:id`
Remove um agendamento permanentemente.

---

## Barbeiros

### GET `/api/barbers`
Lista barbeiros ativos com seus serviços.

**Query params**
| Param | Padrão | Descrição |
|---|---|---|
| `active` | `true` | `true` retorna só os ativos |

---

### GET `/api/barbers/:id`
Retorna barbeiro com todos os serviços associados.

---

### POST `/api/barbers`
Cria um barbeiro.

**Body**
```json
{
  "name": "Carlos",
  "phone_whatsapp": "5585999990001",
  "bio": "Especialista em degradê",
  "avatar_url": "https://...",
  "user_id": "uuid (opcional)",
  "service_ids": ["uuid", "uuid"]
}
```

---

### PUT `/api/barbers/:id`
Atualiza dados do barbeiro. Enviar `service_ids` substitui as associações.

---

### DELETE `/api/barbers/:id`
Desativa o barbeiro (`is_active = false`).

---

### GET `/api/barbers/:id/availability`
Retorna horários disponíveis para um barbeiro em uma data.

**Query params (obrigatórios)**
| Param | Exemplo |
|---|---|
| `date` | `2026-06-15` |
| `service_id` | `uuid` |

**Response 200**
```json
{ "date": "2026-06-15", "available_slots": ["09:00", "09:30", "10:00"] }
```

---

## Serviços

### GET `/api/services`
Lista serviços. Query param `active=true` (padrão) filtra ativos.

### GET `/api/services/:id`

### POST `/api/services`
```json
{
  "name": "Corte + Barba",
  "description": "opcional",
  "duration_minutes": 60,
  "price": 55.00
}
```

### PUT `/api/services/:id`

### DELETE `/api/services/:id`
Desativa o serviço (`is_active = false`).

---

## Clientes

### GET `/api/customers`
**Query params**
| Param | Descrição |
|---|---|
| `search` | Busca por nome ou telefone |
| `active` | `true` (padrão) |

### GET `/api/customers/:id`
Retorna cliente + últimos 10 agendamentos.

### POST `/api/customers`
```json
{
  "name": "João Silva",
  "phone_whatsapp": "5585999990000",
  "email": "opcional",
  "birth_date": "1995-03-20",
  "gender": "masculino",
  "how_found_us": "instagram",
  "notes": "opcional"
}
```

Valores válidos para `gender`: `masculino | feminino | outro | prefiro_nao_informar`
Valores válidos para `how_found_us`: `instagram | indicacao | passando_na_rua | google | outro`

### PUT `/api/customers/:id`

---

## Usuários & Permissões

### GET `/api/users`
Lista todos os usuários com suas roles.

### POST `/api/users`
```json
{
  "name": "Ana",
  "email": "ana@g8.com",
  "password": "senha",
  "phone": "5585999990002",
  "role_id": "uuid"
}
```

### PUT `/api/users/:id`
Campos opcionais: `name`, `email`, `phone`, `role_id`, `is_active`, `password`.

### DELETE `/api/users/:id`
Desativa o usuário (`is_active = false`).

---

### GET `/api/roles`
Lista roles com suas permissões.

**Response 200**
```json
[
  {
    "id": "uuid",
    "name": "owner",
    "permissions": [
      { "action": "manage_barbers" },
      { "action": "manage_services" }
    ]
  }
]
```

### PUT `/api/roles/:id/permissions`
Substitui todas as permissões de uma role.

```json
{ "actions": ["manage_barbers", "manage_services", "view_calendar"] }
```

---

## Horários dos Barbeiros

### GET `/api/schedules/:barber_id`
Retorna a grade semanal e as exceções do barbeiro.

**Response 200**
```json
{
  "schedules": [
    { "id": "uuid", "day_of_week": 1, "start_time": "09:00", "end_time": "18:00", "is_active": true }
  ],
  "exceptions": [
    { "id": "uuid", "date": "2026-06-20", "type": "block", "reason": "Feriado" }
  ]
}
```

`day_of_week`: `0 = domingo … 6 = sábado`

---

### PUT `/api/schedules/:barber_id`
Substitui toda a grade semanal do barbeiro.

```json
{
  "schedules": [
    { "day_of_week": 1, "start_time": "09:00", "end_time": "18:00" },
    { "day_of_week": 2, "start_time": "09:00", "end_time": "18:00" }
  ]
}
```

---

### POST `/api/schedules/:barber_id/exceptions`
Adiciona uma exceção (folga ou horário extra).

```json
{
  "date": "2026-06-20",
  "type": "block",
  "start_time": "14:00",
  "end_time": "18:00",
  "reason": "Consulta médica"
}
```

`type`: `block` (bloqueia) ou `extra` (adiciona horário fora da grade)
`start_time` / `end_time` opcionais — sem eles, bloqueia o dia inteiro.

### DELETE `/api/schedules/:barber_id/exceptions/:id`

---

## Configurações

### GET `/api/config/ai`
Retorna as configurações da IA.

**Response 200**
```json
{
  "bot_name":           { "value": "G8 AI", "description": "Nome do bot" },
  "tone":               { "value": "casual", "description": "Tom de comunicação" },
  "language":           { "value": "pt-BR", "description": "Idioma" },
  "welcome_message":    { "value": "Eae! ...", "description": "Mensagem de boas-vindas" },
  "operator_whatsapp":  { "value": "5585999999999", "description": "Número do operador para notificações de handoff" }
}
```

### PUT `/api/config/ai`
```json
{
  "bot_name": "G8 AI",
  "tone": "casual",
  "welcome_message": "Oi! Sou a G8 AI...",
  "operator_whatsapp": "5585999999999"
}
```

> **`operator_whatsapp`** — número no formato internacional sem `+` (ex: `5585999999999`).
> Quando a IA aciona a tool `transfer_to_human`, este número recebe uma mensagem WhatsApp com o nome do cliente e o motivo do handoff.

---

### GET `/api/config/shop`
Retorna as configurações da barbearia (chave/valor do banco).

### PUT `/api/config/shop`
```json
{ "address": "Rua X, 123", "instagram": "@g8barbershop" }
```

---

### GET `/api/config/shop/md`
Retorna o conteúdo do arquivo `shop_info.md` usado pela IA.

**Response 200**
```json
{ "content": "# Barbershop G8\n\n## Endereço\n..." }
```

### PUT `/api/config/shop/md`
Salva o conteúdo do `shop_info.md` (a IA usa na próxima mensagem, sem restart).

```json
{ "content": "# Barbershop G8\n\n## Endereço\nRua X, 123..." }
```

---

### GET `/api/config/ai/prompt`
Retorna o conteúdo do arquivo `prompt.md` — o system prompt da IA editável pelo painel.

**Response 200**
```json
{ "content": "# Prompt da G8 AI\n\nVocê é a {bot_name}..." }
```

### PUT `/api/config/ai/prompt`
Salva o `prompt.md`. A IA usa o novo prompt na próxima mensagem recebida, sem restart.

```json
{ "content": "# Prompt da G8 AI\n\nVocê é a {bot_name}..." }
```

> **Variáveis obrigatórias** — o prompt deve conter:
>
> | Variável | O que injeta |
> |---|---|
> | `{bot_name}` | Nome do bot (configurado em `/api/config/ai`) |
>
> Se a variável estiver faltando, o endpoint retorna **400**.

---

## Notification Templates

Templates editáveis de notificações WhatsApp (confirmação, lembrete, cancelamento).

### GET `/api/notification-templates`
Retorna todos os templates com `subject` (rótulo para o frontend) e `body` (texto com placeholders).

**Response 200**
```json
{
  "confirmation_client": {
    "subject": "Confirmação para o cliente",
    "body": "✅ Agendamento confirmado!\n\n📅 Data: {data}\n..."
  },
  "confirmation_barber": {
    "subject": "Alerta para o barbeiro",
    "body": "🔔 Novo agendamento!\n\n👤 Cliente: {cliente}\n..."
  },
  "reminder_1h_client": {
    "subject": "Lembrete para o cliente",
    "body": "⏰ Lembrete: seu horário..."
  },
  "reminder_1h_barber": {
    "subject": "Lembrete para o barbeiro",
    "body": "⏰ Lembrete: você tem um cliente..."
  },
  "cancellation_barber": {
    "subject": "Cancelamento para o barbeiro",
    "body": "❌ Agendamento cancelado!\n..."
  }
}
```

### PUT `/api/notification-templates`
Atualiza um ou mais templates. Envie apenas as chaves que deseja alterar.

**Body**
```json
{
  "confirmation_client": {
    "subject": "Confirmação para o cliente",
    "body": "✅ Agendado! \n\n{data} às {hora}\n{servico} com {barbeiro}\n\nValeu! 🤙"
  }
}
```

**Response 200** — mesmo formato do GET, com todos os templates atualizados.

**Placeholders disponíveis**

| Placeholder | Templates onde aparece |
|---|---|
| `{data}` | confirmation_client, confirmation_barber, cancellation_barber |
| `{hora}` | confirmation_client, confirmation_barber, reminder_1h_client, reminder_1h_barber, cancellation_barber |
| `{servico}` | confirmation_client, confirmation_barber, reminder_1h_client, reminder_1h_barber |
| `{barbeiro}` | confirmation_client, reminder_1h_client |
| `{cliente}` | confirmation_barber, reminder_1h_barber, cancellation_barber |
| `{cliente_phone}` | confirmation_barber |

---

## Sessões de Atendimento

Gerencia qual contato está sendo atendido pela IA ou por um humano.

### GET `/api/sessions`
Lista todas as sessões ativas com modo e informações de handoff.

**Response 200**
```json
[
  {
    "phone_whatsapp": "5585999990000",
    "customer_name": "João Silva",
    "mode": "ai",
    "handoff_reason": null,
    "handoff_at": null,
    "last_activity": "2026-06-14T18:30:00Z"
  },
  {
    "phone_whatsapp": "5585888880000",
    "customer_name": "Maria Souza",
    "mode": "human",
    "handoff_reason": "Cliente quer falar sobre reclamação",
    "handoff_at": "2026-06-14T17:55:00Z",
    "last_activity": "2026-06-14T17:55:00Z"
  }
]
```

> `mode`: `"ai"` — IA respondendo automaticamente | `"human"` — IA silenciada, operador assume

---

### PUT `/api/sessions/:phone/mode`
Alterna o modo de atendimento de um contato.

**Body**
```json
{ "mode": "human" }
```

**Response 200**
```json
{ "status": "ok", "phone": "5585999990000", "mode": "human" }
```

> Ao passar `mode: "ai"`, os campos `handoff_reason` e `handoff_at` são limpos automaticamente.

---

### DELETE `/api/sessions/:phone`
Reseta a conversa: apaga o histórico LangGraph do contato e volta o modo para `"ai"`.
Equivalente ao comando `/reset` enviado pelo WhatsApp.

**Response 200**
```json
{ "status": "reset", "phone": "5585999990000" }
```

---

### POST `/api/sessions/:phone/message`
Envia uma mensagem WhatsApp em nome do operador humano (modo `"human"`).

**Body**
```json
{ "text": "Olá! Sou o Carlos, atendente da G8. Como posso ajudar?" }
```

**Response 200**
```json
{ "status": "sent", "phone": "5585999990000" }
```

---

## Health Check

### GET `/health`
```json
{ "status": "ok", "env": "development" }
```

---

## Webhook (Evolution API)

### POST `/webhook/whatsapp`
Recebido automaticamente pela Evolution API. Não deve ser chamado pelo frontend.

---

## Códigos de erro comuns

| Código | Significado |
|---|---|
| `401` | Token ausente, inválido ou expirado |
| `403` | Token válido mas sem permissão para a ação |
| `404` | Recurso não encontrado |
| `400` | Campos obrigatórios ausentes ou inválidos |
