"""
cPanel Passenger WSGI entry point.

GoDaddy cPanel looks for `application` in this file.
Passenger strips the sub-URI prefix (e.g. /watermon) and sets SCRIPT_NAME
before calling this WSGI app, so Flask sees plain paths and url_for() works.
"""
import sys
import os

# Ensure the repo root is on the Python path
sys.path.insert(0, os.path.dirname(__file__))

from werkzeug.middleware.proxy_fix import ProxyFix
from waterapp import create_app

application = create_app()
# Respect SCRIPT_NAME/X-Forwarded headers set by Passenger/Apache
application.wsgi_app = ProxyFix(application.wsgi_app, x_prefix=1)
