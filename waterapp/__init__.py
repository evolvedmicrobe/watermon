import os
import sys

from flask import Flask

# Ensure repo root is on path so waterapp can import common and config
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import SECRET_KEY


def create_app():
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"),
        static_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "static"),
    )
    app.secret_key = SECRET_KEY

    from .routes import bp
    app.register_blueprint(bp)

    return app
