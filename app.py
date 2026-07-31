import os

from dotenv import load_dotenv
from flask import Flask, redirect, request, session, url_for

from database import init_database
from routes import register_blueprints


load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__)

    secret_key = os.getenv("FLASK_SECRET_KEY", "").strip()
    if not secret_key:
        raise RuntimeError("FLASK_SECRET_KEY .env dosyasında bulunamadı.")

    app.secret_key = secret_key
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=False,  # HTTPS yayında True yapılacak.
    )

    init_database()
    register_blueprints(app)

    @app.before_request
    def require_login():
        public_endpoints = {
            "auth.login",
            "auth.oauth_start",
            "auth.oauth_callback",
            "static",
        }

        if request.endpoint in public_endpoints:
            return None

        if request.endpoint is None:
            return None

        if not session.get("user_id"):
            return redirect(url_for("auth.login"))

        return None

    @app.context_processor
    def inject_current_user():
        return {
            "current_user": session.get("user"),
        }

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
