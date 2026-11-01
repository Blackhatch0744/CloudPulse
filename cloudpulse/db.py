import random
import sqlite3
from datetime import date, timedelta

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS resources (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    region TEXT NOT NULL,
    status TEXT NOT NULL,
    storage_gb REAL NOT NULL DEFAULT 0,
    created TEXT NOT NULL,
    sim_cpu REAL NOT NULL,
    sim_memory REAL NOT NULL,
    sim_disk REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS metrics (
    resource_id INTEGER NOT NULL REFERENCES resources(id),
    day TEXT NOT NULL,
    running INTEGER NOT NULL,
    cpu REAL NOT NULL,
    memory REAL NOT NULL,
    storage REAL NOT NULL,
    PRIMARY KEY (resource_id, day)
);
CREATE TABLE IF NOT EXISTS budget (id INTEGER PRIMARY KEY CHECK (id = 1), amount REAL NOT NULL);
"""

# name, type, region, status, storage_gb, then simulated baseline CPU / memory / disk usage in %
SAMPLE_RESOURCES = [
    ("web-server-1", "t3.medium", "us-east-1", "active", 30, 55, 60, 45),
    ("web-server-2", "t3.medium", "us-east-1", "active", 30, 50, 58, 44),
    ("api-backend", "m5.large", "us-east-1", "active", 50, 92, 80, 60),
    ("batch-worker", "c5.xlarge", "us-west-2", "active", 100, 5, 15, 30),
    ("analytics-db", "db.m5.large", "us-east-1", "active", 200, 45, 94, 82),
    ("dev-sandbox", "t3.micro", "eu-west-1", "inactive", 20, 0, 0, 25),
    ("session-cache", "cache.t3.micro", "us-east-1", "active", 0, 20, 40, 0),
    ("legacy-app", "r5.large", "us-east-1", "failed", 40, 0, 0, 70),
    ("k8s-cluster", "eks-cluster", "us-east-1", "active", 0, 35, 40, 0),
    ("media-bucket", "s3-standard", "us-east-1", "active", 1500, 0, 0, 0),
]
HISTORY_DAYS = 90
DEFAULT_BUDGET = 500


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_app(app):
    app.teardown_appcontext(close_db)
    app.before_request(lambda: fill_metrics(get_db()))
    with app.app_context():
        db = get_db()
        db.executescript(SCHEMA)
        if not db.execute("SELECT 1 FROM resources").fetchone():
            start = (date.today() - timedelta(days=HISTORY_DAYS - 1)).isoformat()
            db.executemany(
                "INSERT INTO resources (name, type, region, status, storage_gb, created, sim_cpu, sim_memory, sim_disk)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(*r[:5], start, *r[5:]) for r in SAMPLE_RESOURCES],
            )
            db.execute("INSERT INTO budget (id, amount) VALUES (1, ?)", (DEFAULT_BUDGET,))
            db.commit()


def _pct(rng, base):
    return round(min(100, max(0, rng.gauss(base, 4))), 1) if base else 0


def fill_metrics(db):
    """Simulate one metrics row per resource per day, from its last row (or creation) up to today."""
    today = date.today()
    rows = db.execute(
        "SELECT r.*, (SELECT MAX(day) FROM metrics WHERE resource_id = r.id) AS last FROM resources r"
    ).fetchall()
    new = []
    for r in rows:
        created = date.fromisoformat(r["created"])
        day = date.fromisoformat(r["last"]) + timedelta(days=1) if r["last"] else created
        running = r["status"] == "active"
        while day <= today:
            rng = random.Random(f"{r['id']}-{day}")  # same numbers on every restart and every replica
            disk = min(99, r["sim_disk"] + 0.1 * (day - created).days) if r["sim_disk"] else 0
            new.append((r["id"], day.isoformat(), running,
                        _pct(rng, r["sim_cpu"]) if running else 0,
                        _pct(rng, r["sim_memory"]) if running else 0,
                        round(disk, 1)))
            day += timedelta(days=1)
    if new:
        db.executemany("INSERT OR IGNORE INTO metrics VALUES (?, ?, ?, ?, ?, ?)", new)
        db.commit()
