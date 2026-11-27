"""Short-term and long-term memory.

Short-term: a LangGraph checkpointer keyed by thread_id (one thread per campaign).
Long-term:  a LangGraph store keyed by user_id. Namespaces:
    (user_id, "brand")        the brand profile: product, audience, tone
    (user_id, "preferences")  standing instructions the owner stated ("never offer discounts")
    (user_id, "learnings")    which angle won each campaign
Raw chats, budgets, payment details and passwords are never written to long-term memory."""
import re
import sqlite3
import uuid

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.sqlite import SqliteStore

from .config import GRAPH_DB_PATH

_checkpoint_conn = sqlite3.connect(GRAPH_DB_PATH, check_same_thread=False)
checkpointer = SqliteSaver(_checkpoint_conn)

_store_conn = sqlite3.connect(GRAPH_DB_PATH, check_same_thread=False, isolation_level=None)
store = SqliteStore(_store_conn)
store.setup()

# What we refuse to keep: long digit runs (cards, accounts, CNIC) and credentials.
_SENSITIVE = re.compile(r"(\d[ -]?){11,}|password|passcode|\bpin\b|cvv|api[ _-]?key|secret", re.I)


def is_sensitive(text: str) -> bool:
    return bool(_SENSITIVE.search(text))


def save_profile(user_id: str, profile: dict) -> None:
    """One profile per product, so a second product does not overwrite what we know about the first."""
    key = re.sub(r"[^a-z0-9]+", "-", str(profile.get("product", "profile")).lower()).strip("-")[:40] or "profile"
    store.put((user_id, "brand"), key, profile)


def save_preference(user_id: str, text: str) -> bool:
    if is_sensitive(text):
        return False
    store.put((user_id, "preferences"), uuid.uuid4().hex[:8], {"text": text[:240]})
    return True


def save_learning(user_id: str, campaign_id: str, learning: dict) -> None:
    store.put((user_id, "learnings"), campaign_id, learning)


def forget(user_id: str, kind: str, key: str) -> None:
    if kind in ("brand", "preferences", "learnings"):
        store.delete((user_id, kind), key)


def list_memory(user_id: str) -> list[dict]:
    items = []
    for kind in ("brand", "preferences", "learnings"):
        for item in store.search((user_id, kind), limit=20):
            items.append({"kind": kind, "key": item.key, "value": item.value})
    return items


def recall(user_id: str) -> str:
    """The long-term memory of one brand as a prompt block."""
    lines = []
    for item in list_memory(user_id):
        value = item["value"]
        if item["kind"] == "brand":
            lines.append("Brand profile: " + "; ".join(f"{k}: {v}" for k, v in value.items()))
        elif item["kind"] == "preferences":
            lines.append("Standing preference: " + value["text"])
        else:
            lines.append(f"Past learning: winning angle was '{value.get('winner_angle')}'. {value.get('summary', '')}")
    return "\n".join(lines) or "Nothing saved yet."
