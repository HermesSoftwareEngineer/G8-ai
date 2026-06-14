-- G8-AI Database Schema
-- Execute este arquivo no Supabase SQL Editor

-- =============================================
-- EXTENSÕES
-- =============================================
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =============================================
-- ROLES
-- =============================================
CREATE TABLE IF NOT EXISTS roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE, -- dev, owner, barber, attendant
    created_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================
-- PERMISSIONS
-- =============================================
CREATE TABLE IF NOT EXISTS permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role_id UUID REFERENCES roles(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    -- Ações: manage_users, manage_barbers, manage_services,
    --        manage_schedules, view_calendar, manage_appointments,
    --        edit_ai_config, edit_shop_info, view_customers, manage_customers
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(role_id, action)
);

-- =============================================
-- USERS
-- =============================================
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    phone TEXT,
    password_hash TEXT NOT NULL,
    role_id UUID REFERENCES roles(id),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================
-- BARBERS
-- =============================================
CREATE TABLE IF NOT EXISTS barbers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    phone_whatsapp TEXT NOT NULL,
    avatar_url TEXT,
    bio TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================
-- SERVICES
-- =============================================
CREATE TABLE IF NOT EXISTS services (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    duration_minutes INTEGER NOT NULL DEFAULT 30,
    price NUMERIC(10,2) NOT NULL,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================
-- BARBER_SERVICES
-- =============================================
CREATE TABLE IF NOT EXISTS barber_services (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    barber_id UUID REFERENCES barbers(id) ON DELETE CASCADE,
    service_id UUID REFERENCES services(id) ON DELETE CASCADE,
    UNIQUE(barber_id, service_id)
);

-- =============================================
-- SCHEDULES
-- =============================================
CREATE TABLE IF NOT EXISTS schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    barber_id UUID REFERENCES barbers(id) ON DELETE CASCADE,
    day_of_week INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6), -- 0=domingo, 6=sábado
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    is_active BOOLEAN DEFAULT true
);

-- =============================================
-- SCHEDULE_EXCEPTIONS
-- =============================================
CREATE TABLE IF NOT EXISTS schedule_exceptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    barber_id UUID REFERENCES barbers(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    start_time TIME,
    end_time TIME,
    reason TEXT,
    type TEXT NOT NULL CHECK (type IN ('block', 'extra')),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================
-- CUSTOMERS
-- =============================================
CREATE TABLE IF NOT EXISTS customers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    phone_whatsapp TEXT UNIQUE NOT NULL,
    email TEXT,
    birth_date DATE,
    gender TEXT CHECK (gender IN ('masculino', 'feminino', 'outro', 'prefiro_nao_informar')),
    avatar_url TEXT,
    how_found_us TEXT CHECK (how_found_us IN ('instagram', 'indicacao', 'passando_na_rua', 'google', 'outro')),
    notes TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================
-- APPOINTMENTS
-- =============================================
CREATE TABLE IF NOT EXISTS appointments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID REFERENCES customers(id) ON DELETE SET NULL,
    barber_id UUID REFERENCES barbers(id) ON DELETE SET NULL,
    service_id UUID REFERENCES services(id) ON DELETE SET NULL,
    start_datetime TIMESTAMPTZ NOT NULL,
    end_datetime TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'confirmed', 'cancelled', 'completed', 'no_show')
    ),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================
-- APPOINTMENT_NOTIFICATIONS
-- =============================================
CREATE TABLE IF NOT EXISTS appointment_notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    appointment_id UUID REFERENCES appointments(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (
        type IN ('confirmation', 'reminder_1h', 'barber_alert', 'barber_reminder_1h')
    ),
    sent_at TIMESTAMPTZ,
    channel TEXT DEFAULT 'whatsapp',
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed'))
);

-- =============================================
-- AI_CONFIG
-- =============================================
CREATE TABLE IF NOT EXISTS ai_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key TEXT UNIQUE NOT NULL,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================
-- SHOP_INFO
-- =============================================
CREATE TABLE IF NOT EXISTS shop_info (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key TEXT UNIQUE NOT NULL,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================
-- CONVERSATION_SESSIONS
-- =============================================
CREATE TABLE IF NOT EXISTS conversation_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone_whatsapp TEXT NOT NULL,
    customer_id UUID REFERENCES customers(id) ON DELETE SET NULL,
    context JSONB DEFAULT '[]',
    state TEXT DEFAULT 'idle' CHECK (
        state IN (
            'idle', 'collecting_info', 'choosing_service',
            'choosing_barber', 'choosing_datetime', 'confirming', 'cancelling'
        )
    ),
    last_activity TIMESTAMPTZ DEFAULT now(),
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(phone_whatsapp)
);

-- =============================================
-- INDEXES
-- =============================================
CREATE INDEX IF NOT EXISTS idx_appointments_barber_date ON appointments(barber_id, start_datetime);
CREATE INDEX IF NOT EXISTS idx_appointments_customer ON appointments(customer_id);
CREATE INDEX IF NOT EXISTS idx_appointments_status ON appointments(status);
CREATE INDEX IF NOT EXISTS idx_schedules_barber ON schedules(barber_id, day_of_week);
CREATE INDEX IF NOT EXISTS idx_schedule_exceptions_barber_date ON schedule_exceptions(barber_id, date);
CREATE INDEX IF NOT EXISTS idx_conversation_sessions_phone ON conversation_sessions(phone_whatsapp);
CREATE INDEX IF NOT EXISTS idx_notifications_appointment ON appointment_notifications(appointment_id, status);

-- =============================================
-- TRIGGERS: updated_at automático
-- =============================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER barbers_updated_at BEFORE UPDATE ON barbers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER services_updated_at BEFORE UPDATE ON services
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER customers_updated_at BEFORE UPDATE ON customers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER appointments_updated_at BEFORE UPDATE ON appointments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER ai_config_updated_at BEFORE UPDATE ON ai_config
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER shop_info_updated_at BEFORE UPDATE ON shop_info
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- =============================================
-- SEED: Dados iniciais
-- =============================================

-- Roles
INSERT INTO roles (name) VALUES
    ('dev'),
    ('owner'),
    ('barber'),
    ('attendant')
ON CONFLICT (name) DO NOTHING;

-- Permissões por role
INSERT INTO permissions (role_id, action)
SELECT r.id, a.action FROM roles r
CROSS JOIN (VALUES
    ('manage_users'), ('manage_barbers'), ('manage_services'),
    ('manage_schedules'), ('view_calendar'), ('manage_appointments'),
    ('edit_ai_config'), ('edit_shop_info'), ('view_customers'), ('manage_customers')
) AS a(action)
WHERE r.name = 'dev'
ON CONFLICT (role_id, action) DO NOTHING;

INSERT INTO permissions (role_id, action)
SELECT r.id, a.action FROM roles r
CROSS JOIN (VALUES
    ('manage_barbers'), ('manage_services'), ('manage_schedules'),
    ('view_calendar'), ('manage_appointments'), ('edit_ai_config'),
    ('edit_shop_info'), ('view_customers'), ('manage_customers')
) AS a(action)
WHERE r.name = 'owner'
ON CONFLICT (role_id, action) DO NOTHING;

INSERT INTO permissions (role_id, action)
SELECT r.id, a.action FROM roles r
CROSS JOIN (VALUES
    ('view_calendar'), ('manage_appointments'), ('view_customers')
) AS a(action)
WHERE r.name = 'barber'
ON CONFLICT (role_id, action) DO NOTHING;

INSERT INTO permissions (role_id, action)
SELECT r.id, a.action FROM roles r
CROSS JOIN (VALUES
    ('view_calendar'), ('manage_appointments'), ('view_customers'), ('manage_customers')
) AS a(action)
WHERE r.name = 'attendant'
ON CONFLICT (role_id, action) DO NOTHING;

-- AI Config padrão
INSERT INTO ai_config (key, value, description) VALUES
    ('bot_name', 'G8 AI', 'Nome do bot de atendimento'),
    ('tone', 'casual', 'Tom de comunicação: casual | formal'),
    ('language', 'pt-BR', 'Idioma de atendimento'),
    ('welcome_message', 'Eae! 👋 Sou a G8 AI, atendente virtual da Barbershop G8. Como posso te ajudar hoje?', 'Mensagem de boas-vindas')
ON CONFLICT (key) DO NOTHING;
