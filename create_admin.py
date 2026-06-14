"""
Script para criar o usuário admin inicial.
Execute uma vez após rodar o schema.sql:

    .venv\Scripts\python create_admin.py
"""
from dotenv import load_dotenv
load_dotenv()

from app.models.database import get_db
from app.utils.auth import hash_password

NAME     = "Hermes"
EMAIL    = "hermesbarbosa9@gmail.com"
PASSWORD = "admin123"  # Troque após o primeiro login

db = get_db()

# Busca role dev
role = db.table("roles").select("id").eq("name", "dev").execute()
if not role.data:
    print("[ERRO] Role 'dev' nao encontrada. Rode o schema.sql primeiro.")
    exit(1)
role_id = role.data[0]["id"]

# Verifica se já existe
existing = db.table("users").select("id").eq("email", EMAIL).execute()
if existing.data:
    print(f"[!] Usuario {EMAIL} ja existe.")
    exit(0)

# Cria usuário
user = db.table("users").insert({
    "name": NAME,
    "email": EMAIL,
    "password_hash": hash_password(PASSWORD),
    "role_id": role_id,
}).execute()

print(f"[OK] Admin criado!")
print(f"     Email: {EMAIL}")
print(f"     Senha: {PASSWORD}")
print(f"     Role:  dev (todas as permissoes)")
print()
print("[!] Troque a senha apos o primeiro login.")
