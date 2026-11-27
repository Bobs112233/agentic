"""SQLite data layer. Every read and write of business data takes user_id and filters by it,
so one brand can never reach another brand's rows."""
import json
import sqlite3
import time
import uuid
from datetime import date

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, business TEXT NOT NULL,
    pw_hash TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL, brief TEXT NOT NULL,
    strategy TEXT, status TEXT NOT NULL DEFAULT 'draft',
    daily_budget INTEGER NOT NULL, days INTEGER NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS variants (
    id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, user_id TEXT NOT NULL, label TEXT NOT NULL,
    angle TEXT, headline TEXT NOT NULL, body TEXT NOT NULL, cta TEXT NOT NULL,
    creative TEXT, svg TEXT, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS results (
    variant_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, user_id TEXT NOT NULL,
    impressions INTEGER, clicks INTEGER, conversions INTEGER, spend REAL);
CREATE TABLE IF NOT EXISTS recommendations (
    id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, user_id TEXT NOT NULL,
    winner TEXT, summary TEXT NOT NULL, fixes TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, campaign_id TEXT,
    action TEXT NOT NULL, detail TEXT, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS usage (
    day TEXT NOT NULL, user_id TEXT NOT NULL, runs INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, user_id));
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def rows(sql: str, args: tuple = ()) -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def row(sql: str, args: tuple = ()) -> dict | None:
    found = rows(sql, args)
    return found[0] if found else None


def run(sql: str, args: tuple = ()) -> None:
    with connect() as conn:
        conn.execute(sql, args)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------- users ----------
def create_user(email: str, business: str, pw_hash: str) -> dict:
    user = {"id": new_id(), "email": email.lower().strip(), "business": business.strip()}
    run("INSERT INTO users (id, email, business, pw_hash, created) VALUES (?,?,?,?,?)",
        (user["id"], user["email"], user["business"], pw_hash, time.time()))
    return user


def user_by_email(email: str) -> dict | None:
    return row("SELECT * FROM users WHERE email = ?", (email.lower().strip(),))


def user_by_id(user_id: str) -> dict | None:
    return row("SELECT id, email, business, created FROM users WHERE id = ?", (user_id,))


# ---------- campaigns ----------
def create_campaign(user_id: str, brief: dict) -> dict:
    campaign_id = new_id()
    run("INSERT INTO campaigns (id, user_id, name, brief, daily_budget, days, created) VALUES (?,?,?,?,?,?,?)",
        (campaign_id, user_id, brief["product"][:60], json.dumps(brief),
         brief["daily_budget"], brief["days"], time.time()))
    return get_campaign(user_id, campaign_id)


def _decode(campaign: dict | None) -> dict | None:
    if campaign:
        campaign["brief"] = json.loads(campaign["brief"])
        campaign["strategy"] = json.loads(campaign["strategy"]) if campaign["strategy"] else None
    return campaign


def get_campaign(user_id: str, campaign_id: str) -> dict | None:
    return _decode(row("SELECT * FROM campaigns WHERE id = ? AND user_id = ?", (campaign_id, user_id)))


def list_campaigns(user_id: str) -> list[dict]:
    return [_decode(c) for c in
            rows("SELECT * FROM campaigns WHERE user_id = ? ORDER BY created DESC", (user_id,))]


def update_campaign(user_id: str, campaign_id: str, **fields) -> None:
    allowed = {"strategy", "status"}
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(key)
        if key == "strategy":
            value = json.dumps(value)
        run(f"UPDATE campaigns SET {key} = ? WHERE id = ? AND user_id = ?", (value, campaign_id, user_id))


def set_brief(user_id: str, campaign_id: str, brief: dict) -> None:
    run("UPDATE campaigns SET name = ?, brief = ?, daily_budget = ?, days = ? WHERE id = ? AND user_id = ?",
        (brief["product"][:60], json.dumps(brief), brief["daily_budget"], brief["days"], campaign_id, user_id))


def ensure_api_user(user_id: str) -> None:
    """Callers of the open /chat API get their own account row, separate from website accounts."""
    run("INSERT OR IGNORE INTO users (id, email, business, pw_hash, created) VALUES (?,?,?,?,?)",
        (user_id, f"{user_id}@api.adforge", "API user", "!", time.time()))


def ensure_campaign(user_id: str, campaign_id: str, brief: dict) -> None:
    run("INSERT OR IGNORE INTO campaigns (id, user_id, name, brief, daily_budget, days, created) "
        "VALUES (?,?,?,?,?,?,?)",
        (campaign_id, user_id, brief["product"][:60], json.dumps(brief), brief["daily_budget"], brief["days"],
         time.time()))


# ---------- variants ----------
def list_variants(user_id: str, campaign_id: str) -> list[dict]:
    found = rows("SELECT * FROM variants WHERE campaign_id = ? AND user_id = ? ORDER BY label",
                 (campaign_id, user_id))
    for variant in found:
        variant["creative"] = json.loads(variant["creative"]) if variant["creative"] else None
    return found


def add_variant(user_id: str, campaign_id: str, angle: str, headline: str, body: str, cta: str) -> str:
    """Labels are assigned here (A, B, C...), never by the model."""
    label = chr(ord("A") + len(list_variants(user_id, campaign_id)))
    run("INSERT INTO variants (id, campaign_id, user_id, label, angle, headline, body, cta, created) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (new_id(), campaign_id, user_id, label, angle, headline, body, cta, time.time()))
    return label


def set_creative(user_id: str, campaign_id: str, label: str, creative: dict, svg: str) -> bool:
    with connect() as conn:
        cur = conn.execute(
            "UPDATE variants SET creative = ?, svg = ? WHERE campaign_id = ? AND user_id = ? AND label = ?",
            (json.dumps(creative), svg, campaign_id, user_id, label))
        return cur.rowcount > 0


# ---------- results and recommendations ----------
def save_result(user_id: str, campaign_id: str, variant_id: str, stats: dict) -> None:
    run("INSERT OR REPLACE INTO results (variant_id, campaign_id, user_id, impressions, clicks, conversions, spend) "
        "VALUES (?,?,?,?,?,?,?)",
        (variant_id, campaign_id, user_id, stats["impressions"], stats["clicks"],
         stats["conversions"], stats["spend"]))


def list_results(user_id: str, campaign_id: str) -> list[dict]:
    return rows(
        "SELECT v.label, v.headline, v.angle, r.impressions, r.clicks, r.conversions, r.spend "
        "FROM results r JOIN variants v ON v.id = r.variant_id "
        "WHERE r.campaign_id = ? AND r.user_id = ? ORDER BY v.label", (campaign_id, user_id))


def add_recommendation(user_id: str, campaign_id: str, winner: str, summary: str, fixes: list[str]) -> None:
    run("INSERT INTO recommendations (id, campaign_id, user_id, winner, summary, fixes, created) VALUES (?,?,?,?,?,?,?)",
        (new_id(), campaign_id, user_id, winner, summary, json.dumps(fixes), time.time()))


def list_recommendations(user_id: str, campaign_id: str) -> list[dict]:
    found = rows("SELECT * FROM recommendations WHERE campaign_id = ? AND user_id = ? ORDER BY created DESC",
                 (campaign_id, user_id))
    for rec in found:
        rec["fixes"] = json.loads(rec["fixes"])
    return found


# ---------- audit and usage ----------
def log(user_id: str | None, campaign_id: str | None, action: str, detail: str = "") -> None:
    run("INSERT INTO audit (user_id, campaign_id, action, detail, created) VALUES (?,?,?,?,?)",
        (user_id, campaign_id, action, detail[:500], time.time()))


def take_run(user_id: str, user_limit: int, global_limit: int) -> str | None:
    """Counts one agent run. Returns a refusal reason when a daily cap is reached."""
    today = date.today().isoformat()
    with connect() as conn:
        mine = conn.execute("SELECT runs FROM usage WHERE day = ? AND user_id = ?", (today, user_id)).fetchone()
        total = conn.execute("SELECT COALESCE(SUM(runs), 0) AS n FROM usage WHERE day = ?", (today,)).fetchone()
        if mine and mine["runs"] >= user_limit:
            return "You have reached today's limit of agent runs. Please come back tomorrow."
        if total["n"] >= global_limit:
            return "AdForge has reached its daily usage limit. Please try again tomorrow."
        conn.execute("INSERT INTO usage (day, user_id, runs) VALUES (?, ?, 1) "
                     "ON CONFLICT(day, user_id) DO UPDATE SET runs = runs + 1", (today, user_id))
    return None
