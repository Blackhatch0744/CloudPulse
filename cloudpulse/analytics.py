import calendar
from collections import defaultdict
from datetime import date, timedelta
from statistics import mean

from .pricing import HOURLY, daily_cost

# thresholds in %; CPU/memory checks use the 7-day average so one noisy day doesn't fire an alert
CPU_ALERT = 85
MEMORY_ALERT = 90
STORAGE_ALERT = 90
UNDERUSED_CPU = 10
BUDGET_WARN = 80


def resources(db):
    rows = db.execute("""
        SELECT r.id, r.name, r.type, r.region, r.status, r.storage_gb, r.created,
               m.cpu, m.memory, m.storage,
               (SELECT AVG(cpu) FROM metrics WHERE resource_id = r.id AND day > date(m.day, '-7 day')) AS avg_cpu,
               (SELECT AVG(memory) FROM metrics WHERE resource_id = r.id AND day > date(m.day, '-7 day')) AS avg_memory
        FROM resources r
        LEFT JOIN metrics m ON m.resource_id = r.id
             AND m.day = (SELECT MAX(day) FROM metrics WHERE resource_id = r.id)
        ORDER BY r.id""").fetchall()
    out = []
    for row in rows:
        r = dict(row)
        r["service"], hourly = HOURLY[r["type"]]
        r["compute"] = hourly > 0
        r["avg_cpu"] = round(r["avg_cpu"] or 0, 1)
        r["avg_memory"] = round(r["avg_memory"] or 0, 1)
        cost = daily_cost(r["type"], r["storage_gb"], r["status"] == "active")
        r["daily_cost"] = round(cost, 2)
        r["monthly_cost"] = round(cost * 30, 2)
        out.append(r)
    return out


def resource_detail(db, rid):
    r = next((r for r in resources(db) if r["id"] == rid), None)
    if r:
        r["history"] = [dict(m) for m in db.execute(
            "SELECT day, cpu, memory, storage FROM metrics WHERE resource_id = ? ORDER BY day", (rid,))]
    return r


def cost_history(db):
    per_day = defaultdict(float)
    for m in db.execute(
            "SELECT m.day, m.running, r.type, r.storage_gb FROM metrics m JOIN resources r ON r.id = m.resource_id"):
        per_day[m["day"]] += daily_cost(m["type"], m["storage_gb"], m["running"])
    return [{"day": d, "cost": round(c, 2)} for d, c in sorted(per_day.items())]


def costs(db):
    res = resources(db)
    by_service = defaultdict(float)
    for r in res:
        by_service[r["service"]] += r["monthly_cost"]
    history = cost_history(db)
    month = date.today().isoformat()[:7]
    return {
        "daily": round(sum(r["daily_cost"] for r in res), 2),
        "monthly": round(sum(r["monthly_cost"] for r in res), 2),
        "month_to_date": round(sum(h["cost"] for h in history if h["day"].startswith(month)), 2),
        "by_service": {k: round(v, 2) for k, v in sorted(by_service.items(), key=lambda kv: -kv[1])},
        "by_resource": sorted(({"id": r["id"], "name": r["name"], "service": r["service"],
                                "monthly_cost": r["monthly_cost"]} for r in res),
                              key=lambda r: -r["monthly_cost"]),
        "history": history,
    }


def budget(db):
    amount = db.execute("SELECT amount FROM budget").fetchone()[0]
    spent = costs(db)["month_to_date"]
    today = date.today()
    projected = spent / today.day * calendar.monthrange(today.year, today.month)[1]
    status = "exceeded" if spent > amount else "at risk" if projected > amount else "on track"
    return {"amount": amount, "spent": spent, "projected": round(projected, 2),
            "remaining": round(amount - spent, 2), "used_pct": round(spent / amount * 100, 1), "status": status}


def alerts(db):
    out = []

    def add(severity, category, message):
        out.append({"severity": severity, "category": category, "message": message})

    for r in resources(db):
        if r["status"] == "failed":
            add("critical", "failure", f"{r['name']} has failed and is not serving traffic")
        if r["status"] == "active" and r["avg_cpu"] > CPU_ALERT:
            add("critical", "cpu", f"{r['name']} CPU averaged {r['avg_cpu']}% over 7 days (limit {CPU_ALERT}%)")
        if r["status"] == "active" and r["avg_memory"] > MEMORY_ALERT:
            add("warning", "memory",
                f"{r['name']} memory averaged {r['avg_memory']}% over 7 days (limit {MEMORY_ALERT}%)")
        if r["storage"] and r["storage"] > STORAGE_ALERT:
            add("warning", "storage", f"{r['name']} storage is {r['storage']}% full (limit {STORAGE_ALERT}%)")
    b = budget(db)
    if b["status"] == "exceeded":
        add("critical", "budget", f"Monthly budget of ${b['amount']:,.2f} exceeded: ${b['spent']:,.2f} spent")
    elif b["status"] == "at risk":
        add("warning", "budget", f"Projected spend ${b['projected']:,.2f} will exceed the ${b['amount']:,.2f} budget")
    elif b["used_pct"] >= BUDGET_WARN:
        add("warning", "budget", f"{b['used_pct']}% of the monthly budget is already used")
    return sorted(out, key=lambda a: a["severity"] != "critical")


def optimization(db):
    res = resources(db)
    active = [r for r in res if r["status"] == "active" and r["compute"]]
    underutilized = [r for r in active if r["avg_cpu"] < UNDERUSED_CPU]
    recs = []
    for r in underutilized:
        # one instance size down roughly halves the hourly price
        recs.append({"resource": r["name"], "action": f"Downsize or stop: CPU averages {r['avg_cpu']}%",
                     "saving": round(HOURLY[r["type"]][1] * 24 * 30 / 2, 2)})
    for r in res:
        if r["status"] != "active" and r["monthly_cost"] > 0:
            recs.append({"resource": r["name"], "action": f"Snapshot and delete the storage of this {r['status']} resource",
                         "saving": r["monthly_cost"]})
    return {
        "underutilized": underutilized,
        "high_usage": [r for r in active if r["avg_cpu"] > CPU_ALERT or r["avg_memory"] > MEMORY_ALERT],
        "expensive": sorted(res, key=lambda r: -r["monthly_cost"])[:3],
        "recommendations": recs,
        "total_saving": round(sum(x["saving"] for x in recs), 2),
    }


def reports(db):
    c = costs(db)
    today = date.today()
    monthly = defaultdict(float)
    for h in c["history"]:
        monthly[h["day"][:7]] += h["cost"]

    def window(days_from, days_to):
        lo, hi = (today - timedelta(days=days_from)).isoformat(), (today - timedelta(days=days_to)).isoformat()
        cpu, memory = db.execute(
            "SELECT AVG(cpu), AVG(memory) FROM metrics WHERE cpu > 0 AND day BETWEEN ? AND ?", (lo, hi)).fetchone()
        return {"avg_cpu": round(cpu or 0, 1), "avg_memory": round(memory or 0, 1),
                "cost": round(sum(h["cost"] for h in c["history"] if lo <= h["day"] <= hi), 2)}

    since = (today - timedelta(days=30)).isoformat()
    utilization = [dict(r) for r in db.execute("""
        SELECT r.name, ROUND(AVG(m.cpu), 1) AS avg_cpu, MAX(m.cpu) AS max_cpu,
               ROUND(AVG(m.memory), 1) AS avg_memory, MAX(m.memory) AS max_memory, MAX(m.storage) AS storage
        FROM metrics m JOIN resources r ON r.id = m.resource_id
        WHERE m.day > ? GROUP BY r.id ORDER BY r.id""", (since,))]
    opt = optimization(db)
    return {
        "daily": c["history"][-30:],
        "monthly": [{"month": m, "cost": round(v, 2)} for m, v in sorted(monthly.items())],
        "utilization": utilization,
        "comparison": {"this_week": window(6, 0), "last_week": window(13, 7)},
        "by_service": c["by_service"],
        "optimization": {"recommendations": len(opt["recommendations"]), "total_saving": opt["total_saving"],
                         "underutilized": len(opt["underutilized"]), "high_usage": len(opt["high_usage"])},
    }


def overview(db):
    res = resources(db)
    active = [r for r in res if r["status"] == "active"]
    compute = [r for r in active if r["compute"]]
    al = alerts(db)
    c = costs(db)
    return {
        "total": len(res),
        "active": len(active),
        "inactive": len(res) - len(active),
        "failed": sum(r["status"] == "failed" for r in res),
        "monthly_cost": c["monthly"],
        "month_to_date": c["month_to_date"],
        "avg_cpu": round(mean(r["cpu"] for r in compute), 1) if compute else 0,
        "avg_memory": round(mean(r["memory"] for r in compute), 1) if compute else 0,
        "alerts": len(al),
        "status": "Critical" if any(a["severity"] == "critical" for a in al) else "Warning" if al else "Healthy",
        "by_service": c["by_service"],
    }
