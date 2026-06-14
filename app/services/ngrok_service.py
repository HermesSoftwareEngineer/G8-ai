import logging
import os
from app.config import Config

logger = logging.getLogger(__name__)


def start_dev_tunnel() -> str | None:
    """
    Start an ngrok tunnel in development and return the full webhook URL.

    - Uses NGROK_AUTHTOKEN from .env if set (specific account / static domain).
    - Falls back to anonymous tunnel (random URL, changes each restart).
    - Skips entirely outside development or when Werkzeug reloader parent process runs.
    """
    if Config.FLASK_ENV != "development":
        return None

    # Werkzeug debug mode spawns a parent monitor + a child server.
    # WERKZEUG_RUN_MAIN is set to "true" only in the child. Skip the parent
    # to avoid starting two ngrok tunnels.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "false":
        return None

    try:
        from pyngrok import conf, ngrok

        if Config.NGROK_USE_FIXED_URL:
            logger.info("🚇 [ngrok] Modo: URL FIXA (domínio estático)")
            if not Config.NGROK_AUTHTOKEN or not Config.NGROK_DOMAIN:
                logger.error("🚇 [ngrok] ❌ NGROK_USE_FIXED_URL=true mas NGROK_AUTHTOKEN ou NGROK_DOMAIN não definidos")
                return None
        else:
            logger.info("🚇 [ngrok] Modo: URL ALEATÓRIA (muda a cada restart)")

        logger.info("🚇 [ngrok] Iniciando tunnel na porta %s...", Config.PORT)

        if Config.NGROK_AUTHTOKEN:
            conf.get_default().ngrok_path = Config.NGROK_PATH
            conf.get_default().auth_token = Config.NGROK_AUTHTOKEN
            masked = Config.NGROK_AUTHTOKEN[:8] + "****"
            logger.info("🚇 [ngrok] Authtoken: %s", masked)
        else:
            logger.info("🚇 [ngrok] Sem authtoken — sessão anônima")

        ngrok.kill()
        logger.debug("🚇 [ngrok] Tunnels anteriores encerrados")

        connect_kwargs = {"proto": "http", "addr": Config.PORT}
        if Config.NGROK_USE_FIXED_URL and Config.NGROK_DOMAIN:
            connect_kwargs["hostname"] = Config.NGROK_DOMAIN
            logger.info("🚇 [ngrok] Domínio fixo: %s", Config.NGROK_DOMAIN)

        logger.info("🚇 [ngrok] Conectando...")
        tunnel = ngrok.connect(**connect_kwargs)
        public_url = tunnel.public_url
        if public_url.startswith("http://"):
            public_url = "https://" + public_url[7:]

        webhook_url = f"{public_url}/webhook/whatsapp"
        logger.info("🚇 [ngrok] ✅ Tunnel ativo!")
        logger.info("🚇 [ngrok]    URL pública : %s", public_url)
        logger.info("🚇 [ngrok]    Webhook URL : %s", webhook_url)
        return webhook_url

    except ImportError:
        logger.warning("🚇 [ngrok] pyngrok não instalado — usando WEBHOOK_URL do .env")
        return None
    except Exception as e:
        logger.warning("🚇 [ngrok] ❌ Falha ao iniciar: %s", e)
        logger.warning("🚇 [ngrok] Usando WEBHOOK_URL do .env como fallback")
        return None
