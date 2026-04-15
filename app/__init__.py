import os

from dotenv import load_dotenv
from flask import Flask

from app.db import init_db


def create_app() -> Flask:
    load_dotenv()
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me")

    from app import routes

    app.register_blueprint(routes.bp)

    @app.cli.command("init-db")
    def init_db_command():
        """Create database tables (run once against Neon)."""
        init_db()
        print("Database initialized.")

    return app
