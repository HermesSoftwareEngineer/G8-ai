# G8-AI — Backend

Sistema de atendimento inteligente via WhatsApp para a **Barbershop G8**.

## Stack

- **Python 3.11+** / Flask
- **Supabase** (PostgreSQL)
- **Evolution API** (WhatsApp)
- **Claude Sonnet** (Anthropic)
- **APScheduler** (lembretes automáticos)

---

## Setup

### 1. Clone o repositório

```bash
git clone https://github.com/HermesSoftwareEngineer/G8-ai.git
cd G8-ai
```

### 2. Crie o ambiente virtual

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

### 3. Instale as dependências

```bash
pip install -r requirements.txt
```

### 4. Configure o `.env`

```bash
cp .env.example .env
```

Preencha todas as variáveis no `.env`:

| Variável | Descrição |
|---|---|
| `SUPABASE_URL` | URL do projeto Supabase |
| `SUPABASE_SERVICE_KEY` | Chave service role do Supabase |
| `ANTHROPIC_API_KEY` | Chave da API Anthropic |
| `EVOLUTION_API_URL` | URL base da Evolution API |
| `EVOLUTION_API_KEY` | Chave da Evolution API |
| `EVOLUTION_INSTANCE_NAME` | Nome da instância (padrão: `g8-ai`) |
| `FLASK_SECRET_KEY` | Chave secreta Flask (gere uma aleatória) |

### 5. Configure o Supabase

1. Acesse seu projeto em [app.supabase.com](https://app.supabase.com)
2. Vá em **SQL Editor**
3. Cole e execute o conteúdo de `database/schema.sql`
4. Isso criará todas as tabelas, índices, triggers e dados iniciais (roles + permissões + ai_config padrão)

### 6. Configure a Evolution API

1. Certifique-se que a Evolution API está rodando e acessível
2. Crie uma instância chamada `g8-ai` (ou o nome configurado em `EVOLUTION_INSTANCE_NAME`)
3. Conecte o WhatsApp escaneando o QR code
4. Configure o webhook da instância para apontar para:
   ```
   POST http://SEU_IP:5000/webhook/whatsapp
   ```
5. Ative o evento `MESSAGES_UPSERT` no webhook

> **Dica DEV:** Use [ngrok](https://ngrok.com) para expor o servidor local: `ngrok http 5000`

### 7. Inicie o servidor

```bash
python run.py
```

O servidor iniciará em `http://localhost:5000`.

---

## Endpoints

### Health Check
```
GET /health
```

### Webhook WhatsApp
```
POST /webhook/whatsapp
```

### Auth
```
POST /api/auth/login     → { email, password }
POST /api/auth/logout
```

### Agendamentos
```
GET    /api/appointments                    → ?barber_id, ?status, ?date_from, ?date_to
GET    /api/appointments/:id
POST   /api/appointments
PATCH  /api/appointments/:id/status        → { status }
DELETE /api/appointments/:id
```

### Barbeiros
```
GET    /api/barbers
GET    /api/barbers/:id
POST   /api/barbers
PUT    /api/barbers/:id
DELETE /api/barbers/:id
GET    /api/barbers/:id/availability       → ?date=YYYY-MM-DD&service_id=
```

### Serviços
```
GET    /api/services
GET    /api/services/:id
POST   /api/services
PUT    /api/services/:id
DELETE /api/services/:id
```

### Clientes
```
GET    /api/customers                      → ?search, ?active
GET    /api/customers/:id
POST   /api/customers
PUT    /api/customers/:id
```

### Usuários & Permissões
```
GET    /api/users
POST   /api/users
PUT    /api/users/:id
DELETE /api/users/:id
GET    /api/roles
PUT    /api/roles/:id/permissions          → { actions: [...] }
```

### Horários
```
GET  /api/schedules/:barber_id
PUT  /api/schedules/:barber_id             → { schedules: [{day_of_week, start_time, end_time}] }
POST /api/schedules/:barber_id/exceptions  → { date, type, start_time?, end_time?, reason? }
DELETE /api/schedules/:barber_id/exceptions/:id
```

### Configurações
```
GET /api/config/ai
PUT /api/config/ai                         → { bot_name, tone, language, welcome_message }
GET /api/config/shop
PUT /api/config/shop
GET /api/config/shop/md                    → retorna shop_info.md como string
PUT /api/config/shop/md                    → { content: "..." }
```

---

## Autenticação

Todos os endpoints (exceto `/health` e `/webhook/whatsapp`) exigem JWT.

```
Authorization: Bearer <token>
```

O token é obtido via `POST /api/auth/login` e expira em 24h.

### Roles e Permissões

| Role | Permissões |
|---|---|
| `dev` | Todas |
| `owner` | Tudo exceto manage_users |
| `attendant` | view/manage_appointments, view/manage_customers |
| `barber` | view_calendar, manage_appointments, view_customers |

---

## Arquivo `shop_info.md`

Edite `shop_info.md` diretamente ou via API (`PUT /api/config/shop/md`) para atualizar as informações que a IA usa nas respostas. Não requer reinicialização do servidor.

---

## Lembretes Automáticos

O APScheduler roda em background e verifica a cada **15 minutos** se há agendamentos começando em 45–75 minutos. Se sim, envia mensagens de lembrete via WhatsApp para o cliente e para o barbeiro.

---

## Estrutura do Projeto

```
g8-ai/
├── app/
│   ├── __init__.py          # Factory da aplicação Flask
│   ├── config.py            # Variáveis de ambiente
│   ├── routes/              # Blueprints (endpoints)
│   ├── services/            # Lógica de negócio (IA, WhatsApp, scheduler)
│   ├── models/              # Cliente Supabase
│   └── utils/               # Helpers (datetime, auth, md)
├── database/
│   └── schema.sql           # Schema completo do banco
├── shop_info.md             # Infos editáveis da barbearia
├── run.py                   # Entrypoint
└── requirements.txt
```
