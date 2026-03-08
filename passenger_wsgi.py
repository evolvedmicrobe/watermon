"""
cPanel Passenger WSGI entry point.

GoDaddy cPanel looks for `application` in this file.
"""
import sys
import os

# Ensure the repo root is on the Python path
sys.path.insert(0, os.path.dirname(__file__))

from waterapp import create_app

application = create_app()
