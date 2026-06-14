"""
Cria tabela notification_templates e insere templates padrão.
"""

import psycopg
from app.config import Config

DDL = """
CREATE TABLE IF NOT EXISTS notification_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_key TEXT UNIQUE NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS notification_templates_updated_at ON notification_templates;
CREATE TRIGGER notification_templates_updated_at
    BEFORE UPDATE ON notification_templates
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
"""

SEED_SQL = """
INSERT INTO notification_templates (template_key, subject, body) VALUES
    ('confirmation_client', 'Confirmação para o cliente',
     '✅ Agendamento confirmado!\n\n'
     '📅 Data: {data}\n'
     '⏰ Horário: {hora}\n'
     '💈 Serviço: {servico}\n'
     '👤 Barbeiro: {barbeiro}\n\n'
     'Até lá! 🤙'),
    ('confirmation_barber', 'Alerta para o barbeiro',
     '🔔 Novo agendamento!\n\n'
     '👤 Cliente: {cliente}\n'
     '📱 WhatsApp: {cliente_phone}\n'
     '📅 Data: {data}\n'
     '⏰ Horário: {hora}\n'
     '💈 Serviço: {servico}'),
    ('reminder_1h_client', 'Lembrete para o cliente',
     '⏰ Lembrete: seu horário na Barbershop G8 é em 1 hora!\n\n'
     '🕐 {hora} com {barbeiro}\n'
     '💈 {servico}\n\n'
     'Qualquer dúvida, é só chamar aqui. 👊'),
    ('reminder_1h_barber', 'Lembrete para o barbeiro',
     '⏰ Lembrete: você tem um cliente em 1 hora!\n\n'
     '👤 {cliente}\n'
     '🕐 {hora}\n'
     '💈 {servico}'),
    ('cancellation_barber', 'Cancelamento para o barbeiro',
     '❌ Agendamento cancelado!\n\n'
     '👤 Cliente: {cliente}\n'
     '📅 Data: {data}\n'
     '⏰ Horário: {hora}')
ON CONFLICT (template_key) DO NOTHING;
"""


def _pg_conn():
    db_url = Config.SUPABASE_DB_URL
    if not db_url:
        raise RuntimeError("SUPABASE_DB_URL não configurado")
    return psycopg.connect(db_url, connect_timeout=10)


def up():
    with _pg_conn() as conn:
        conn.execute(DDL)
        conn.execute(SEED_SQL)
        conn.execute("NOTIFY pgrst, 'reload schema'")


def down():
    with _pg_conn() as conn:
        conn.execute("DROP TABLE IF EXISTS notification_templates CASCADE;")
        conn.execute("NOTIFY pgrst, 'reload schema'")
