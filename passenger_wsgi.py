"""
cPanel Passenger WSGI entry point.

GoDaddy cPanel looks for `application` in this file.
Passenger sets SCRIPT_NAME from PassengerBaseURI (e.g. /watermon2) and passes
the remaining path as PATH_INFO, so Flask sees plain paths and url_for() works.
"""
import sys
import os

# Ensure the repo root is on the Python path
sys.path.insert(0, os.path.dirname(__file__))

from waterapp import create_app

application = create_app()
