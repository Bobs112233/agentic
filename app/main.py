"""AdForge API and website (FastAPI). Run: uvicorn app.main:app --reload"""
import hmac
import re
import threading
from collections import defaultdict
from datetime import date

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import agent_api, db, gate, graph, memory, security
from .config import ADMIN_PASSWORD, GLOBAL_DAILY_RUNS, RETAINER_PKR, ROOT, USER_DAILY_RUNS

db.init()
app = FastAPI(title="AdForge", docs_url=None, redoc_url=None)
WEB = ROOT / "web"
app.add_middleware(gate.SiteGate)
app.include_router(agent_api.router)  # open /health and /chat for the evaluator
app.add_api_route("/gate", gate.gate_form, methods=["GET"], include_in_schema=False)
app.add_api_route("/gate", gate.gate_submit, methods=["POST"], include_in_schema=False)
app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")

_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)  # one agent run per campaign at a time
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------- auth
def _claims(authorization: str | None) -> dict:
    token = (authorization or "").removeprefix("Bearer ").strip()
    claims = security.read_token(token)
    if not claims:
        raise HTTPException(401, "Please log in again.")
    return claims


def current_user(authorization: str | None = Header(default=None)) -> dict:
    claims = _claims(authorization)
    user = db.user_by_id(claims["sub"]) if claims.get("role") == "user" else None
    if not user:
        raise HTTPException(401, "Please log in again.")
    return user


def current_admin(authorization: str | None = Header(default=None)) -> dict:
    claims = _claims(authorization)
    if claims.get("role") != "admin":
        raise HTTPException(403, "Admin only.")
    return claims


class Signup(BaseModel):
    email: str = Field(max_length=120)
    password: str = Field(min_length=6, max_length=120)
    business: str = Field(min_length=2, max_length=60)


class Login(BaseModel):
    email: str = Field(max_length=120)
    password: str = Field(max_length=120)


@app.post("/api/signup")
def signup(body: Signup):
    if not _EMAIL.match(body.email):
        raise HTTPException(400, "Enter a valid email address.")
    if graph.looks_like_injection(body.business):
        raise HTTPException(400, "That business name is not allowed.")
    if db.user_by_email(body.email):
        raise HTTPException(409, "An account with this email already exists. Log in instead.")
    user = db.create_user(body.email, body.business, security.hash_password(body.password))
    db.log(user["id"], None, "signup", user["business"])
    return {"token": security.make_token(user["id"]), "user": user}


@app.post("/api/login")
def login(body: Login):
    user = db.user_by_email(body.email)
    if not user or not security.check_password(body.password, user["pw_hash"]):
        raise HTTPException(401, "Wrong email or password.")
    return {"token": security.make_token(user["id"]),
            "user": {"id": user["id"], "email": user["email"], "business": user["business"]}}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    return {"user": user, "memory": memory.list_memory(user["id"])}


@app.delete("/api/memory/{kind}/{key}")
def forget(kind: str, key: str, user: dict = Depends(current_user)):
    memory.forget(user["id"], kind, key)
    return {"memory": memory.list_memory(user["id"])}


# ---------------------------------------------------------------- campaigns
class Brief(BaseModel):
    product: str = Field(min_length=2, max_length=80)
    details: str = Field(default="", max_length=500)
    audience: str = Field(default="", max_length=200)
    goal: str = Field(default="Sales", max_length=40)
    platform: str = Field(default="Instagram", max_length=40)
    daily_budget: int = Field(ge=500, le=500000)
    days: int = Field(ge=1, le=30)


class Chat(BaseModel):
    message: str = Field(min_length=1, max_length=1500)


class Action(BaseModel):
    action: str


class Approval(BaseModel):
    approve: bool


def _metrics(result: dict) -> dict:
    impressions, clicks, conversions, spend = (result[k] or 0 for k in ("impressions", "clicks", "conversions", "spend"))
    return {**result,
            "ctr": round(clicks / impressions * 100, 2) if impressions else 0,
            "cpc": round(spend / clicks, 2) if clicks else None,
            "cpa": round(spend / conversions, 2) if conversions else None}


def snapshot(user: dict, campaign_id: str, trace: list[str] | None = None) -> dict:
    campaign = db.get_campaign(user["id"], campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found.")
    return {
        "campaign": campaign,
        "variants": db.list_variants(user["id"], campaign_id),
        "results": [_metrics(r) for r in db.list_results(user["id"], campaign_id)],
        "recommendations": db.list_recommendations(user["id"], campaign_id),
        "messages": graph.conversation(user["id"], campaign_id),
        "pending": graph.pending_approval(user["id"], campaign_id),
        "memory": memory.list_memory(user["id"]),
        "trace": trace or [],
    }


def _agent(user: dict, campaign_id: str, work) -> dict:
    """Runs one agent turn behind the cost cap and the per-campaign lock."""
    if not db.get_campaign(user["id"], campaign_id):
        raise HTTPException(404, "Campaign not found.")
    lock = _locks[campaign_id]
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "The agents are still working on this campaign. Try again in a moment.")
    try:
        refusal = db.take_run(user["id"], USER_DAILY_RUNS, GLOBAL_DAILY_RUNS)
        if refusal:
            raise HTTPException(429, refusal)
        try:
            trace = work()
        except HTTPException:
            raise
        except Exception as error:
            db.log(user["id"], campaign_id, "agent_error", type(error).__name__)
            raise HTTPException(502, "The AI service did not respond. Please try again.") from error
    finally:
        lock.release()
    return snapshot(user, campaign_id, trace)


@app.get("/api/campaigns")
def campaigns(user: dict = Depends(current_user)):
    return {"campaigns": [{"id": c["id"], "name": c["name"], "status": c["status"],
                           "daily_budget": c["daily_budget"], "days": c["days"]}
                          for c in db.list_campaigns(user["id"])]}


@app.post("/api/campaigns")
def create_campaign(brief: Brief, user: dict = Depends(current_user)):
    text = " ".join([brief.product, brief.details, brief.audience, brief.goal, brief.platform])
    if graph.looks_like_injection(text):
        db.log(user["id"], None, "refused", "injection in brief")
        raise HTTPException(400, "This brief was blocked by the safety guard. Describe only your product and audience.")
    if len(db.list_campaigns(user["id"])) >= 12:
        raise HTTPException(400, "Campaign limit reached for this account.")
    campaign = db.create_campaign(user["id"], brief.model_dump())
    db.log(user["id"], campaign["id"], "campaign_created", brief.product)
    return _agent(user, campaign["id"],
                  lambda: graph.run_turn(user["id"], campaign["id"], "New campaign brief submitted.", "create"))


@app.get("/api/campaigns/{campaign_id}")
def get_campaign(campaign_id: str, user: dict = Depends(current_user)):
    return snapshot(user, campaign_id)


def _no_pending(user: dict, campaign_id: str) -> None:
    if db.get_campaign(user["id"], campaign_id) and graph.pending_approval(user["id"], campaign_id):
        raise HTTPException(409, "Approve or cancel the pending launch first.")


@app.post("/api/campaigns/{campaign_id}/chat")
def chat(campaign_id: str, body: Chat, user: dict = Depends(current_user)):
    _no_pending(user, campaign_id)
    return _agent(user, campaign_id, lambda: graph.run_turn(user["id"], campaign_id, body.message))


ACTIONS = {
    "launch": ("Launch this campaign.", "launch"),
    "analyze": ("Analyse the results: which ad is winning, and what should I fix?", "assistant"),
    "revise": ("Write a new challenger ad using the latest recommendation.", "revise"),
}


@app.post("/api/campaigns/{campaign_id}/action")
def action(campaign_id: str, body: Action, user: dict = Depends(current_user)):
    if body.action not in ACTIONS:
        raise HTTPException(400, "Unknown action.")
    _no_pending(user, campaign_id)
    message, intent = ACTIONS[body.action]
    if body.action == "revise" and len(db.list_variants(user["id"], campaign_id)) >= 6:
        raise HTTPException(400, "This campaign already has 6 ads. Start a new campaign to test more.")
    return _agent(user, campaign_id, lambda: graph.run_turn(user["id"], campaign_id, message, intent))


@app.post("/api/campaigns/{campaign_id}/approval")
def approval(campaign_id: str, body: Approval, user: dict = Depends(current_user)):
    if not db.get_campaign(user["id"], campaign_id):
        raise HTTPException(404, "Campaign not found.")
    if not graph.pending_approval(user["id"], campaign_id):
        raise HTTPException(409, "Nothing is waiting for approval.")
    return _agent(user, campaign_id, lambda: graph.resume_turn(user["id"], campaign_id, body.approve))


# ---------------------------------------------------------------- admin
class AdminLogin(BaseModel):
    password: str = Field(max_length=200)


@app.post("/api/admin/login")
def admin_login(body: AdminLogin):
    if not ADMIN_PASSWORD or not hmac.compare_digest(body.password, ADMIN_PASSWORD):
        raise HTTPException(401, "Wrong admin password.")
    return {"token": security.make_token("admin", role="admin", ttl=86400)}


@app.get("/api/admin/overview")
def admin_overview(_: dict = Depends(current_admin)):
    brands = db.rows(
        "SELECT u.id, u.business, u.email, u.created, "
        "(SELECT COUNT(*) FROM campaigns c WHERE c.user_id = u.id) AS campaigns, "
        "(SELECT COUNT(*) FROM campaigns c WHERE c.user_id = u.id AND c.status = 'live') AS live, "
        "(SELECT COALESCE(SUM(r.spend), 0) FROM results r WHERE r.user_id = u.id) AS spend, "
        "(SELECT COALESCE(SUM(r.conversions), 0) FROM results r WHERE r.user_id = u.id) AS conversions "
        "FROM users u ORDER BY u.created DESC")
    campaigns = db.rows(
        "SELECT c.id, c.name, c.status, c.daily_budget, c.days, c.created, u.business, "
        "(SELECT COUNT(*) FROM variants v WHERE v.campaign_id = c.id) AS ads, "
        "(SELECT COALESCE(SUM(r.spend), 0) FROM results r WHERE r.campaign_id = c.id) AS spend, "
        "(SELECT COALESCE(SUM(r.clicks), 0) FROM results r WHERE r.campaign_id = c.id) AS clicks, "
        "(SELECT COALESCE(SUM(r.conversions), 0) FROM results r WHERE r.campaign_id = c.id) AS conversions "
        "FROM campaigns c JOIN users u ON u.id = c.user_id ORDER BY c.created DESC LIMIT 60")
    audit = db.rows(
        "SELECT a.action, a.detail, a.created, COALESCE(u.business, '') AS business "
        "FROM audit a LEFT JOIN users u ON u.id = a.user_id ORDER BY a.id DESC LIMIT 40")
    runs_today = db.row("SELECT COALESCE(SUM(runs), 0) AS n FROM usage WHERE day = ?", (date.today().isoformat(),))["n"]
    refused = db.row("SELECT COUNT(*) AS n FROM audit WHERE action = 'refused'")["n"]
    return {
        "totals": {"brands": len(brands), "mrr": len(brands) * RETAINER_PKR,
                   "campaigns": sum(b["campaigns"] for b in brands), "live": sum(b["live"] for b in brands),
                   "ad_spend": round(sum(b["spend"] for b in brands)), "runs_today": runs_today,
                   "run_cap": GLOBAL_DAILY_RUNS, "refused": refused},
        "brands": brands, "campaigns": campaigns, "audit": audit,
    }


# ---------------------------------------------------------------- pages
@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/", include_in_schema=False)
def landing():
    return FileResponse(WEB / "index.html")


@app.get("/app", include_in_schema=False)
def workspace():
    return FileResponse(WEB / "app.html")


@app.get("/admin", include_in_schema=False)
def admin_page():
    return FileResponse(WEB / "admin.html")
