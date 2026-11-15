"""Write protection for public deployments.

Set CLOUDPULSE_ADMIN_TOKEN to require a token for every request that changes data
(POST, PUT, PATCH, DELETE). Reads stay public. If the variable is unset, writes are
open, which keeps local development and the tests working as before.

API clients send the token as a bearer token:
    curl -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
         -d '{"amount": 750}' https://your-app.onrender.com/api/budget

Browsers use HTTP Basic auth: visit /login, enter any username and the token as the
password, and the browser sends it with the dashboard forms from then on.
"""

import hmac
from urllib.parse import urlsplit

from flask import current_app, redirect, request

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
REALM = 'Basic realm="CloudPulse admin", charset="UTF-8"'


def _supplied_token():
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    if request.authorization and request.authorization.type == "basic":
        return request.authorization.password or ""
    return None


def is_authorized():
    token = current_app.config.get("ADMIN_TOKEN")
    if not token:
        return True
    supplied = _supplied_token()
    return supplied is not None and hmac.compare_digest(supplied.encode(), token.encode())


def _same_origin():
    """Block cross-site form posts, since browsers attach Basic auth credentials automatically."""
    source = request.headers.get("Origin") or request.headers.get("Referer")
    if not source:
        return True  # non-browser clients (curl, scripts) send neither header
    return urlsplit(source).netloc == request.host


def _challenge():
    if request.path.startswith("/api/"):
        return {"error": "authentication required"}, 401, {"WWW-Authenticate": 'Bearer realm="CloudPulse"'}
    return ("Authentication required. Visit /login first.", 401, {"WWW-Authenticate": REALM})


def protect_writes():
    if request.method in SAFE_METHODS:
        return None
    if not current_app.config.get("ADMIN_TOKEN"):
        return None
    if not _same_origin():
        return {"error": "cross-site request blocked"}, 403
    if not is_authorized():
        return _challenge()
    return None


def login():
    """Ask the browser for credentials once; it then reuses them for the dashboard forms."""
    if current_app.config.get("ADMIN_TOKEN") and not (request.authorization and is_authorized()):
        return "Enter the admin token as the password.", 401, {"WWW-Authenticate": REALM}
    return redirect("/")
