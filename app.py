from flask import Flask

from database import init_database
from routes import register_blueprints


def create_app() -> Flask:
    app = Flask(__name__)

    init_database()
    register_blueprints(app)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
