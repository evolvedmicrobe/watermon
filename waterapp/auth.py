from functools import wraps

from flask import redirect, request, session, url_for

from config import APP_PASSWORD


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("main.login", next=request.path))
        return f(*args, **kwargs)
    return decorated


def check_password(password: str) -> bool:
    return password == APP_PASSWORD
