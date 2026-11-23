"""Password hashing and signed tokens (standard library only)."""
import base64
import hashlib
import hmac
import json
import os
import time

from .config import SECRET_KEY


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"{salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        salt_hex, _ = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, bytes.fromhex(salt_hex)), stored)


def _sign(payload: str) -> str:
    return hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_token(subject: str, role: str = "user", ttl: int = 7 * 86400) -> str:
    body = json.dumps({"sub": subject, "role": role, "exp": int(time.time()) + ttl})
    payload = base64.urlsafe_b64encode(body.encode()).decode()
    return f"{payload}.{_sign(payload)}"


def read_token(token: str) -> dict | None:
    """Returns the claims, or None if the token is forged or expired."""
    try:
        payload, signature = token.rsplit(".", 1)
        if not hmac.compare_digest(_sign(payload), signature):
            return None
        claims = json.loads(base64.urlsafe_b64decode(payload.encode()))
        if claims.get("exp", 0) < time.time():
            return None
        return claims
    except Exception:
        return None
