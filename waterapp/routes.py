import threading
from datetime import date, timedelta

from flask import (
    Blueprint,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .auth import check_password, login_required
from . import data as d
from . import charts

bp = Blueprint("main", __name__)

# Tracks a background refresh so the UI can poll for completion
_refresh_state = {"running": False, "message": "", "error": ""}


# ── Auth ──────────────────────────────────────────────────────────────────────

@bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if check_password(request.form.get("password", "")):
            session["logged_in"] = True
            return redirect(request.args.get("next") or url_for("main.dashboard"))
        error = "Incorrect password."
    return render_template("login.html", error=error)


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.login"))


# ── Dashboard ─────────────────────────────────────────────────────────────────

@bp.route("/")
@login_required
def dashboard():
    # Date range defaults: last 90 days
    default_end = date.today()
    default_start = default_end - timedelta(days=90)

    start_str = request.args.get("start", default_start.isoformat())
    end_str = request.args.get("end", default_end.isoformat())
    tail_min = int(request.args.get("tail", 20))

    aq = d.load_aquahawk_df(start_date=start_str, end_date=end_str)
    rachio = d.load_rachio_df(start_date=start_str, end_date=end_str)
    attributed = d.attribute_gallons(aq, rachio, tail_minutes=tail_min)

    chart_data = {
        "monthly_aquahawk": charts.chart_monthly_aquahawk(aq),
        "daily_usage": charts.chart_daily_usage(aq),
        "zone_over_time": charts.chart_zone_over_time(attributed),
        "timeline": charts.chart_rachio_timeline(rachio),
        "zone_totals": charts.chart_zone_totals(attributed),
        "gpm": charts.chart_gpm(attributed),
        "alignment": charts.chart_alignment(aq, rachio),
    }

    return render_template(
        "dashboard.html",
        charts=chart_data,
        start=start_str,
        end=end_str,
        tail=tail_min,
        refresh_state=_refresh_state,
    )


# ── Data refresh ──────────────────────────────────────────────────────────────

def _run_refresh():
    _refresh_state["running"] = True
    _refresh_state["error"] = ""
    try:
        aq_count = d.download_aquahawk()
        ra_count = d.download_rachio()
        _refresh_state["message"] = (
            f"Done — {aq_count} new AquaHawk file(s), {ra_count} new Rachio file(s)."
        )
    except Exception as exc:
        _refresh_state["error"] = str(exc)
        _refresh_state["message"] = "Refresh failed."
    finally:
        _refresh_state["running"] = False


@bp.route("/refresh", methods=["POST"])
@login_required
def refresh():
    if _refresh_state["running"]:
        return jsonify({"status": "already_running"})
    t = threading.Thread(target=_run_refresh, daemon=True)
    t.start()
    return jsonify({"status": "started"})


@bp.route("/refresh/status")
@login_required
def refresh_status():
    return jsonify(_refresh_state)
