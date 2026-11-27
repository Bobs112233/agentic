"""Open agent API used by the automated evaluator.

    GET  /health                                   -> {"status": "ok", ...}
    POST /chat {"user_id", "thread_id", "message"} -> {"reply", "tool_calls", "tokens", ...}

No login: callers are identified only by the user_id they send. Each user_id gets its own account row and
each (user_id, thread_id) pair its own campaign, so callers stay isolated from each other and from website
accounts. Daily run caps still apply, and spending still pauses for an explicit "yes"."""
import hashlib
import re
import threading
from collections import defaultdict

from fastapi import APIRouter, HTTPException
from langchain_core.callbacks import UsageMetadataCallbackHandler
from pydantic import BaseModel, Field

from . import db, graph
from .config import GLOBAL_DAILY_RUNS, MODEL, USER_DAILY_RUNS

router = APIRouter()
_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)

_YES = re.compile(r"^\s*(yes|y|yeah|yep|approve[sd]?|i approve|confirm(ed)?|go ahead|ok(ay)?|sure|launch( it)?|haan|ji)\b", re.I)
_NO = re.compile(r"^\s*(no|n|nope|cancel|stop|don'?t|do not|reject|decline|nahi|nah)\b", re.I)


class ChatIn(BaseModel):
    user_id: str = Field(min_length=1, max_length=100)
    thread_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1500)


def _ids(user_id: str, thread_id: str) -> tuple[str, str]:
    uid = "api_" + hashlib.sha256(user_id.encode()).hexdigest()[:16]
    cid = "t" + hashlib.sha256(f"{user_id}\x00{thread_id}".encode()).hexdigest()[:15]
    return uid, cid


def _placeholder() -> dict:
    return {"product": graph.NO_PRODUCT, "details": "", "audience": "", "goal": "Sales", "platform": "Instagram",
            "daily_budget": 2000, "days": 5}


@router.get("/health")
def health():
    return {"status": "ok", "service": "AdForge", "model": MODEL}


@router.post("/chat")
def chat(body: ChatIn):
    uid, cid = _ids(body.user_id, body.thread_id)
    db.ensure_api_user(uid)
    db.ensure_campaign(uid, cid, _placeholder())

    lock = _locks[cid]
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "This thread is still being processed. Try again in a moment.")
    try:
        refusal = db.take_run(uid, USER_DAILY_RUNS, GLOBAL_DAILY_RUNS)
        if refusal:
            raise HTTPException(429, refusal)
        usage = UsageMetadataCallbackHandler()
        tools: list[dict] = []
        callbacks = [usage]
        try:
            pending = graph.pending_approval(uid, cid)
            if pending:
                if _YES.match(body.message) and not _NO.match(body.message):
                    graph.resume_turn(uid, cid, True, callbacks, tools)
                elif _NO.match(body.message):
                    graph.resume_turn(uid, cid, False, callbacks, tools)
                else:
                    return _response(f"{pending['question']} Reply 'yes' to approve or 'no' to cancel. "
                                     "Nothing is spent until you approve.", tools, usage, uid, cid)
            else:
                forced = None
                if not db.list_variants(uid, cid):
                    brief = graph.extract_brief(body.message, callbacks)
                    if brief:
                        db.set_brief(uid, cid, brief)
                        forced = "create"
                graph.run_turn(uid, cid, body.message, forced, callbacks, tools)
        except HTTPException:
            raise
        except Exception as error:
            db.log(uid, cid, "agent_error", type(error).__name__)
            raise HTTPException(502, "The AI service did not respond. Please try again.") from error
    finally:
        lock.release()

    pending = graph.pending_approval(uid, cid)
    if pending:
        reply = (f"{pending['question']} Reply 'yes' to approve or 'no' to cancel. "
                 "Nothing is spent until you approve.")
    else:
        messages = graph.conversation(uid, cid)
        reply = messages[-1]["text"] if messages and messages[-1]["role"] == "agent" else "Done."
    return _response(reply, tools, usage, uid, cid)


def _response(reply: str, tools: list[dict], usage: UsageMetadataCallbackHandler, uid: str, cid: str) -> dict:
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for model_usage in usage.usage_metadata.values():
        for key in totals:
            totals[key] += int(model_usage.get(key, 0) or 0)
    campaign = db.get_campaign(uid, cid) or {}
    return {
        "reply": reply,
        "tool_calls": tools,
        "tokens": totals["total_tokens"],
        "usage": totals,
        "awaiting_approval": bool(graph.pending_approval(uid, cid)),
        "campaign_status": campaign.get("status"),
        "ads": [{"label": v["label"], "angle": v["angle"], "headline": v["headline"], "text": v["body"],
                 "cta": v["cta"]} for v in db.list_variants(uid, cid)],
    }
