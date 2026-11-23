"""Settings. Every secret comes from the environment (.env locally, Render env vars when deployed)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "adforge.db"
GRAPH_DB_PATH = DATA_DIR / "graph.db"

MODEL = os.getenv("ADFORGE_MODEL", "claude-haiku-5-5")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-secret-change-me")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
# When set, the whole site asks for this password first. Empty = site is open.
SITE_PASSWORD = os.getenv("SITE_PASSWORD", "")

# Cost guards: the API key has a hard spend limit, and the site is public.
USER_DAILY_RUNS = int(os.getenv("USER_DAILY_RUNS", "40"))
GLOBAL_DAILY_RUNS = int(os.getenv("GLOBAL_DAILY_RUNS", "400"))

RETAINER_PKR = 15000
