from datetime import date

from flask import Blueprint, abort, redirect, render_template, request, url_for

from . import analytics, auth
from .db import get_db
from .pricing import HOURLY

bp = Blueprint("cloudpulse", __name__)
bp.before_request(auth.protect_writes)
bp.get("/login")(auth.login)
STATUSES = ("active", "inactive", "failed")


def _json():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _validate_resource(data):
    name = str(data.get("name") or "").strip()
    region = str(data.get("region") or "us-east-1").strip()
    status = data.get("status") or "active"
    try:
        storage = float(data.get("storage_gb") or 0)
    except (TypeError, ValueError):
        return None, "storage_gb must be a number"
    if not name or len(name) > 64:
        return None, "name is required (max 64 characters)"
    if data.get("type") not in HOURLY:
        return None, f"type must be one of: {', '.join(HOURLY)}"
    if not region or len(region) > 32:
        return None, "region is required (max 32 characters)"
    if status not in STATUSES:
        return None, f"status must be one of: {', '.join(STATUSES)}"
    if not 0 <= storage <= 1_000_000:  # also rejects NaN and inf
        return None, "storage_gb must be between 0 and 1000000"
    return (name, data["type"], region, status, storage), None


def _validate_amount(value):
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None, "amount must be a number"
    if not 0 < amount <= 1e9:
        return None, "amount must be greater than 0"
    return amount, None


def _add_resource(fields):
    name, type_, region, status, storage = fields
    compute = HOURLY[type_][1] > 0
    db = get_db()
    cur = db.execute(
        "INSERT INTO resources (name, type, region, status, storage_gb, created, sim_cpu, sim_memory, sim_disk)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (name, type_, region, status, storage, date.today().isoformat(),
         30 if compute else 0, 40 if compute else 0, 20 if storage else 0))
    db.commit()
    return cur.lastrowid


def _set_budget(amount):
    db = get_db()
    db.execute("UPDATE budget SET amount = ? WHERE id = 1", (amount,))
    db.commit()


@bp.get("/health")
def health():
    return {"status": "ok"}


# ---- JSON API ----

@bp.get("/api/overview")
def api_overview():
    return analytics.overview(get_db())


@bp.get("/api/resources")
def api_resources():
    return analytics.resources(get_db())


@bp.post("/api/resources")
def api_add_resource():
    fields, error = _validate_resource(_json())
    if error:
        return {"error": error}, 400
    return {"id": _add_resource(fields)}, 201


@bp.get("/api/resources/<int:rid>")
def api_resource(rid):
    return analytics.resource_detail(get_db(), rid) or abort(404)


@bp.get("/api/costs")
def api_costs():
    return analytics.costs(get_db())


@bp.get("/api/budget")
def api_budget():
    return analytics.budget(get_db())


@bp.put("/api/budget")
def api_set_budget():
    amount, error = _validate_amount(_json().get("amount"))
    if error:
        return {"error": error}, 400
    _set_budget(amount)
    return analytics.budget(get_db())


@bp.get("/api/optimization")
def api_optimization():
    return analytics.optimization(get_db())


@bp.get("/api/alerts")
def api_alerts():
    return analytics.alerts(get_db())


@bp.get("/api/reports")
def api_reports():
    return analytics.reports(get_db())


# ---- Dashboard pages ----

@bp.get("/")
def overview():
    return render_template("overview.html", data=analytics.overview(get_db()))


@bp.route("/resources", methods=["GET", "POST"])
def resources_page():
    error = None
    if request.method == "POST":
        fields, error = _validate_resource(request.form)
        if not error:
            _add_resource(fields)
            return redirect(url_for(".resources_page"))
    return render_template("resources.html", resources=analytics.resources(get_db()),
                           types=HOURLY, statuses=STATUSES, error=error), 400 if error else 200


@bp.get("/resources/<int:rid>")
def resource_detail(rid):
    r = analytics.resource_detail(get_db(), rid) or abort(404)
    return render_template("resource_detail.html", r=r)


@bp.get("/costs")
def costs():
    return render_template("costs.html", data=analytics.costs(get_db()))


@bp.route("/budget", methods=["GET", "POST"])
def budget_page():
    error = None
    if request.method == "POST":
        amount, error = _validate_amount(request.form.get("amount"))
        if not error:
            _set_budget(amount)
            return redirect(url_for(".budget_page"))
    db = get_db()
    return render_template("budget.html", data=analytics.budget(db), error=error,
                           alerts=[a for a in analytics.alerts(db) if a["category"] == "budget"]), 400 if error else 200


@bp.get("/optimization")
def optimization():
    return render_template("optimization.html", data=analytics.optimization(get_db()))


@bp.get("/alerts")
def alerts():
    return render_template("alerts.html", alerts=analytics.alerts(get_db()))


@bp.get("/reports")
def reports():
    return render_template("reports.html", data=analytics.reports(get_db()))
