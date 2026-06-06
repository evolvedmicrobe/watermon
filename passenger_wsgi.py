"""
cPanel Passenger WSGI entry point.

GoDaddy cPanel looks for `application` in this file.
Passenger strips the sub-URI prefix (e.g. /watermon2) and sets SCRIPT_NAME
before calling this WSGI app, so Flask sees plain paths and url_for() works.
"""
import sys
import os

# Ensure the repo root is on the Python path
sys.path.insert(0, os.path.dirname(__file__))

from werkzeug.middleware.proxy_fix import ProxyFix
from waterapp import create_app

application = create_app()
# Respect SCRIPT_NAME set by Passenger/Apache based on PassengerBaseURI
_proxied = ProxyFix(application.wsgi_app, x_prefix=1)


def _wsgi(environ, start_response):
    """Outermost shim. Hitting any URL containing 'wmdebug' returns the RAW
    WSGI environ (as Passenger handed it to us, before ProxyFix) so we can see
    how SCRIPT_NAME / PATH_INFO are being mapped. Remove once diagnosed."""
    if "wmdebug" in environ.get("REQUEST_URI", "") or "wmdebug" in environ.get("QUERY_STRING", ""):
        import json

        keys = [
            "REQUEST_URI", "SCRIPT_NAME", "PATH_INFO", "QUERY_STRING",
            "SERVER_NAME", "HTTP_HOST", "wsgi.url_scheme",
        ]
        info = {k: environ.get(k) for k in keys}
        info["_all_environ"] = {k: str(v) for k, v in environ.items()}
        info["_passenger_keys"] = {
            k: v for k, v in environ.items() if k.startswith("PASSENGER")
        }
        info["_x_forwarded"] = {
            k: v for k, v in environ.items() if k.startswith("HTTP_X_FORWARDED")
        }
        body = json.dumps(info, indent=2, default=str).encode()
        start_response("200 OK", [("Content-Type", "application/json")])
        return [body]
    return _proxied(environ, start_response)


application.wsgi_app = _wsgi
