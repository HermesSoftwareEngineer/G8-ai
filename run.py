import os
from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.config import Config

app = create_app()

if __name__ == "__main__":
    port = Config.PORT
    debug = Config.FLASK_ENV == "development"
    print(f"🚀 G8-AI iniciando em http://localhost:{port} [{'DEBUG' if debug else 'PROD'}]")
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)
