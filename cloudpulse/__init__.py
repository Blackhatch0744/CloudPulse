import os

from flask import Flask

from . import db, routes


def create_app(db_path=None, admin_token=None):
    app = Flask(__name__)
    app.config["ADMIN_TOKEN"] = admin_token or os.environ.get("CLOUDPULSE_ADMIN_TOKEN", "")
    app.config["DATABASE"] = db_path or os.environ.get("CLOUDPULSE_DB", "cloudpulse.db")
    app.add_template_filter(lambda v: f"${v:,.2f}", "money")
    db.init_app(app)
    app.register_blueprint(routes.bp)
    return app
