import logging
import os
from flask import Flask, jsonify
from flask_cors import CORS
from app.config import Config


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = Config.SECRET_KEY

    # Logging
    log_level = logging.DEBUG if Config.FLASK_ENV == "development" else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # CORS
    CORS(app, origins=Config.CORS_ORIGINS, supports_credentials=True)

    # Register blueprints
    from app.routes.webhook import bp as webhook_bp
    from app.routes.appointments import bp as appointments_bp
    from app.routes.barbers import bp as barbers_bp
    from app.routes.customers import bp as customers_bp
    from app.routes.services import bp as services_bp
    from app.routes.users import bp as users_bp
    from app.routes.schedules import bp as schedules_bp
    from app.routes.config import bp as config_bp
    from app.routes.dashboard import bp_dashboard
    from app.routes.sessions import bp as sessions_bp

    app.register_blueprint(webhook_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(barbers_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(services_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(schedules_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(bp_dashboard)
    app.register_blueprint(sessions_bp)

    # Health check
    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "env": Config.FLASK_ENV})

    # Start background scheduler (not in testing)
    if not app.testing:
        from app.services.reminder_job import start_scheduler
        from app.services.whatsapp import setup_webhook
        from app.services.ai_agent import init_checkpointer

        start_scheduler()
        init_checkpointer()

        # In development, auto-start ngrok and use its URL as webhook
        webhook_url = None
        if Config.FLASK_ENV == "development":
            from app.services.ngrok_service import start_dev_tunnel
            webhook_url = start_dev_tunnel()

        setup_webhook(webhook_url=webhook_url)

    return app
