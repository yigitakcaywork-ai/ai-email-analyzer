from flask import Flask

from .auth import auth_bp
from .dashboard import dashboard_bp
from .follow_ups import follow_ups_bp
from .gmail_actions import gmail_actions_bp
from .replies import replies_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(gmail_actions_bp)
    app.register_blueprint(replies_bp)
    app.register_blueprint(follow_ups_bp)
