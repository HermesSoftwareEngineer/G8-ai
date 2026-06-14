import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "http://localhost:8080")
    EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY")
    EVOLUTION_INSTANCE_NAME = os.getenv("EVOLUTION_INSTANCE_NAME", "g8-ai")
    WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")

    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-in-prod")
    FLASK_ENV = os.getenv("FLASK_ENV", "development")
    PORT = int(os.getenv("PORT", 5001))

    TZ = os.getenv("TZ", "America/Fortaleza")

    NGROK_AUTHTOKEN = os.getenv("NGROK_AUTHTOKEN", "")
    NGROK_DOMAIN = os.getenv("NGROK_DOMAIN", "")
    NGROK_USE_FIXED_URL = os.getenv("NGROK_USE_FIXED_URL", "false").lower() == "true"

    JWT_ALGORITHM = "HS256"
    JWT_EXPIRY_HOURS = 24

    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")

    # LangGraph / LangSmith
    SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL")          # postgresql://... direct connection
    LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY")
    LANGCHAIN_PROJECT = os.getenv("LANGCHAIN_PROJECT", "g8-ai")
    LANGCHAIN_TRACING_V2 = os.getenv("LANGCHAIN_TRACING_V2", "false")
