import os

# ---- Telegram & Gist credentials ----
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
APP_URL = os.environ.get("APP_URL")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "webhooksecret")

GIST_TOKEN = os.environ.get("GIST_TOKEN")
GIST_ID = os.environ.get("GIST_ID")
GIST_FILENAME = "allenamenti.json"

# ---- Domain constants ----
HOURS = (
    ["prima delle 9:00"] +
    [f"dalle {h}:00" for h in range(9, 21)] +
    ["dopo le 20:00"]
)
DAYS = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
MONTHS = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]

# ---- FSM States ----
STATE_SELECT_DAYS = "SELECT_DAYS"
STATE_SELECT_HOURS = "SELECT_HOURS"
STATE_DELETING = "DELETING"
