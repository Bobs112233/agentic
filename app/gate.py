"""Site-wide password gate. When SITE_PASSWORD is set, every page and API call needs a signed cookie
that is only given out after the visitor types the password on /gate."""
import hashlib
import hmac
import time
from html import escape
from urllib.parse import parse_qs, quote

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import SECRET_KEY, SITE_PASSWORD

COOKIE = "adforge_gate"
MAX_AGE = 7 * 86400
OPEN_PATHS = ("/gate", "/healthz", "/static/")


def _sign(value: str) -> str:
    # The password is part of the key, so changing SITE_PASSWORD logs everyone out.
    key = f"{SECRET_KEY}:{SITE_PASSWORD}".encode()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


def make_cookie() -> str:
    expires = str(int(time.time()) + MAX_AGE)
    return f"{expires}.{_sign(expires)}"


def cookie_ok(value: str | None) -> bool:
    try:
        expires, signature = (value or "").split(".", 1)
        return hmac.compare_digest(_sign(expires), signature) and int(expires) > time.time()
    except ValueError:
        return False


def _safe_next(target: str) -> str:
    return target if target.startswith("/") and not target.startswith("//") else "/"


def page(next_url: str, error: str = "") -> HTMLResponse:
    message = f'<p class="error">{escape(error)}</p>' if error else '<p class="error"></p>'
    return HTMLResponse(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AdForge: private preview</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/style.css"></head>
<body><canvas id="bg"></canvas>
<header class="nav"><span class="logo"><i></i>AdForge</span><span class="chip warn"><span class="dot"></span>private preview</span></header>
<main><div class="panel glow pad" style="max-width:420px;margin:70px auto">
<span class="label">Restricted access</span>
<h2 style="margin:8px 0 6px">Enter the site password</h2>
<p class="muted" style="margin:0 0 18px">This demo is shared privately. Ask Group G33 for the password.</p>
<form method="post" action="/gate">
<input type="hidden" name="next" value="{escape(next_url)}">
<label class="field"><span class="label">Password</span>
<input name="password" type="password" maxlength="200" autocomplete="current-password" autofocus required></label>
<button class="btn primary" style="width:100%">Enter AdForge</button>{message}
</form></div></main>
<script src="/static/bg.js"></script></body></html>""", status_code=401 if error else 200)


class SiteGate(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not SITE_PASSWORD or path.startswith(OPEN_PATHS) or path == "/favicon.ico":
            return await call_next(request)
        if cookie_ok(request.cookies.get(COOKIE)):
            return await call_next(request)
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Site password required. Reload the page."}, status_code=401)
        target = path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse("/gate?next=" + quote(target, safe=""), status_code=303)


async def gate_form(request: Request):
    if not SITE_PASSWORD or cookie_ok(request.cookies.get(COOKIE)):
        return RedirectResponse(_safe_next(request.query_params.get("next", "/")), status_code=303)
    return page(_safe_next(request.query_params.get("next", "/")))


async def gate_submit(request: Request):
    form = parse_qs((await request.body()).decode(errors="ignore")[:2000])
    password = (form.get("password") or [""])[0]
    next_url = _safe_next((form.get("next") or ["/"])[0])
    if not SITE_PASSWORD or hmac.compare_digest(password.encode(), SITE_PASSWORD.encode()):
        response = RedirectResponse(next_url, status_code=303)
        response.set_cookie(COOKIE, make_cookie(), max_age=MAX_AGE, httponly=True, samesite="lax",
                            secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https")
        return response
    time.sleep(1)  # slows down password guessing
    return page(next_url, "Wrong password.")
