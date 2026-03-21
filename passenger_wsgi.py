"""
cPanel Passenger WSGI entry point.

GoDaddy cPanel looks for `application` in this file.
"""
import sys
import os

# Ensure the repo root is on the Python path
sys.path.insert(0, os.path.dirname(__file__))

from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.wrappers import Response
from waterapp import create_app

_app = create_app()
_app.config["APPLICATION_ROOT"] = "/watermon"
_app.config["PREFERRED_URL_SCHEME"] = "http"

# Mount the Flask app at /watermon so url_for() generates correct paths
application = DispatcherMiddleware(
    Response("Not Found", status=404),
    {"/watermon": _app},
)
