import os
import json
import requests
from flask import Flask, request
import telebot
from datetime import datetime, timedelta
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ============================================================
#                CONFIGURATION
# ============================================================

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
APP_URL = os.environ.get("APP_URL")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "webhooksecret")

GIST_TOKEN = os.environ.get("GIST_TOKEN")
GIST_ID = os.environ.get("GIST_ID")
GIST_FILENAME = "allenamenti.json"

bot = telebot.TeleBot(TOKEN, threaded=False)
app = Flask(__name__)

# ============================================================
#                TIME SLOTS (with extra before/after)
# ============================================================

hours = (
    ["prima delle 9:00"] +
    [f"dalle {h}:00" for h in range(9, 21)] +
    ["dopo le 20:00"]
)

days = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
months = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]

# ============================================================
#                MULTI-GROUP DATABASE
# ============================================================

# Structure:
# {
#   "groups": {
#       "<chat_id>": {
#           "db": { day: { hour: [entries] }},
#           "user_selections": {},
#           "delete_state": {}
#       }
#   }
# }

GLOBAL_DB = { "groups": {} }

def ensure_group(chat_id):
    cid = str(chat_id)
    if cid not in GLOBAL_DB["groups"]:
        GLOBAL_DB["groups"][cid] = {
            "db": { g: {h: [] for h in hours} for g in days },
            "user_selections": {},
            "delete_state": {}
        }
    return GLOBAL_DB["groups"][cid]

def _gist_headers():
    return {
        "Authorization": f"Bearer {GIST_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

def load_db():
    global GLOBAL_DB
    try:
        url = f"https://api.github.com/gists/{GIST_ID}"
        r = requests.get(url, headers=_gist_headers(), timeout=10)
        r.raise_for_status()
        raw = r.json()
        content = raw["files"][GIST_FILENAME]["content"]
        GLOBAL_DB = json.loads(content)
        if "groups" not in GLOBAL_DB:
            GLOBAL_DB = {"groups": {}}
        print("✔ Multi-group DB loaded")
    except Exception as e:
        print(f"[WARN] Cannot load Gist: {e}")
        GLOBAL_DB = {"groups": {}}

def save_db():
    try:
        payload = {
            "files": {
                GIST_FILENAME: {
                    "content": json.dumps(GLOBAL_DB, ensure_ascii=False, indent=2)
                }
            }
        }
        url = f"https://api.github.com/gists/{GIST_ID}"
        r = requests.patch(url, headers=_gist_headers(), json=payload, timeout=10)
        r.raise_for_status()
        print("✔ Multi-group DB saved")
    except Exception as e:
        print(f"[WARN] Cannot save Gist: {e}")

if GIST_TOKEN and GIST_ID:
    load_db()

# ============================================================
#                HELPERS
# ============================================================

def is_owner(chat_id, user_id):
    try:
        admins = bot.get_chat_administrators(chat_id)
        return any(a.user.id == user_id and a.status == "creator" for a in admins)
    except:
        return False

def reset_group_state(group):
    group["db"] = { g: {h: [] for h in hours} for g in days }
    group["user_selections"] = {}
    group["delete_state"] = {}
    save_db()

def get_week_dates():
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    res = {}
    for i, g in enumerate(days):
        d = monday + timedelta(days=i)
        res[g] = (d.day, months[d.month - 1])
    return res

def matches_user(entry, uid, name):
    if isinstance(entry, dict):
        return entry.get("id") == uid
    return str(entry) == name

def display_entry(entry):
    if isinstance(entry, dict):
        first = entry.get("first_name") or "?"
        uname = entry.get("username")
        return f"{first} (@{uname})" if uname else first
    return str(entry)

def generate_summary(group):
    txt = "🦍 **RIEPILOGO ALLENAMENTI SETTIMANALI** 🦍\n\n"
    week = get_week_dates()
    empty = True

    for g in days:
        lines = []
        for h in hours:
            ppl = group["db"][g][h]
            if ppl:
                names = ", ".join(display_entry(p) for p in ppl)
                lines.append(f" {h}: {names}")
        if lines:
            dn, m = week[g]
            txt += f"**{g} {dn} {m}**\n" + "\n".join(lines) + "\n\n"
            empty = False

    if empty:
        txt += "_Nessuna prenotazione._"
    return txt

# ============================================================
#                KEYBOARDS
# ============================================================

def keyboard_days(selected):
    markup = InlineKeyboardMarkup()
    row = []
    for g in days:
        label = f"✅ {g}" if g in selected else g
        btn = InlineKeyboardButton(label, callback_data=f"selgiorno_{g}")
        row.append(btn)
        if len(row) == 2:
            markup.row(*row)
            row = []
    if len(row) == 1:
        markup.row(row[0])

    markup.row(InlineKeyboardButton("🗑️ Cancella", callback_data="cancella_tutto"))
    if selected:
        markup.row(InlineKeyboardButton("➡️ CONFERMA GIORNI", callback_data="conferma_giorni"))
    return markup

def keyboard_hours(day):
    markup = InlineKeyboardMarkup()
    row = []
    for h in hours:
        btn = InlineKeyboardButton(h, callback_data=f"selora_{day}_{h}")
        row.append(btn)
        if len(row) == 2:
            markup.row(*row)
            row = []
    if row:
        markup.row(row[0])
    return markup

def keyboard_delete(bookings, selected):
    markup = InlineKeyboardMarkup()
    for i, (d, h) in enumerate(bookings):
        label = f"{'✅ ' if i in selected else ''}{d} — {h}"
        markup.add(InlineKeyboardButton(label, callback_data=f"delpick_{i}"))

    if bookings:
        markup.row(
            InlineKeyboardButton("✅ Conferma eliminazione", callback_data="delconfirm"),
            InlineKeyboardButton("↩️ Annulla", callback_data="delcancel")
        )
    else:
        markup.add(InlineKeyboardButton("↩️ Chiudi", callback_data="delcancel"))
    return markup

# ============================================================
#                BOT COMMANDS
# ============================================================

@bot.message_handler(commands=["start", "allenamento"])
def start(message):
    chat_id = message.chat.id
    group = ensure_group(chat_id)

    if not is_owner(chat_id, message.from_user.id):
        bot.send_message(chat_id, "❌ Solo il proprietario può usare questo comando.")
        return

    reset_group_state(group)
    bot.send_message(
        chat_id,
        generate_summary(group),
        reply_markup=keyboard_days([]),
        parse_mode="Markdown"
    )

# ============================================================
#                CALLBACKS (MULTIGROUP)
# ============================================================

@bot.callback_query_handler(func=lambda c: True)
def callback(c):
    chat_id = c.message.chat.id
    group = ensure_group(chat_id)

    uid = c.from_user.id
    first = c.from_user.first_name or ""
    uname = c.from_user.username
    data = c.data
    msg = c.message.message_id

    # --- DELETE FLOW ---
    if data == "cancella_tutto":
        bookings = []
        for d in days:
            for h in hours:
                if any(matches_user(e, uid, first) for e in group["db"][d][h]):
                    bookings.append((d, h))

        group["delete_state"][uid] = {"items": bookings, "selected": set()}
        save_db()

        bot.edit_message_text(
            "Seleziona le prenotazioni da cancellare:",
            chat_id, msg,
            reply_markup=keyboard_delete(bookings, set()),
            parse_mode="Markdown"
        )
        return

    if data.startswith("delpick_"):
        idx = int(data.split("_", 1)[1])
        state = group["delete_state"][uid]
        if idx in state["selected"]:
            state["selected"].remove(idx)
        else:
            state["selected"].add(idx)
        save_db()

        bot.edit_message_reply_markup(
            chat_id, msg,
            reply_markup=keyboard_delete(state["items"], state["selected"])
        )
        return

    if data == "delconfirm":
        state = group["delete_state"].get(uid, {})
        for i in sorted(state.get("selected", [])):
            d, h = state["items"][i]
            group["db"][d][h] = [
                e for e in group["db"][d][h]
                if not matches_user(e, uid, first)
            ]
        group["delete_state"].pop(uid, None)
        save_db()

        bot.edit_message_text(
            generate_summary(group),
            chat_id, msg,
            reply_markup=keyboard_days([]),
            parse_mode="Markdown"
        )
        return

    if data == "delcancel":
        group["delete_state"].pop(uid, None)
        bot.edit_message_text(
            generate_summary(group),
            chat_id, msg,
            reply_markup=keyboard_days([]),
            parse_mode="Markdown"
        )
        return

    # --- SELECT DAY ---
    if data.startswith("selgiorno_"):
        day = data.split("_", 1)[1]
        sel = group["user_selections"].setdefault(uid, {"days": [], "index": 0})
        if day in sel["days"]:
            sel["days"].remove(day)
        else:
            sel["days"].append(day)
        save_db()

        bot.edit_message_reply_markup(
            chat_id, msg,
            reply_markup=keyboard_days(sel["days"])
        )
        return

    # --- CONFIRM DAYS ---
    if data == "conferma_giorni":
        sel = group["user_selections"].get(uid)
        if not sel or not sel["days"]:
            bot.answer_callback_query(c.id, "Seleziona almeno un giorno!")
            return

        sel["index"] = 0
        first_day = sel["days"][0]
        save_db()

        bot.edit_message_text(
            f"Ottimo {first}! Per **{first_day}**, a che ora ci sarai?",
            chat_id, msg,
            reply_markup=keyboard_hours(first_day),
            parse_mode="Markdown"
        )
        return

    # --- SELECT HOUR ---
    if data.startswith("selora_"):
        _, d, h = data.split("_", 2)
        sel = group["user_selections"][uid]

        entry = {"id": uid, "first_name": first, "username": uname}

        if not any(matches_user(e, uid, first) for e in group["db"][d][h]):
            group["db"][d][h].append(entry)
            save_db()

        sel["index"] += 1
        if sel["index"] < len(sel["days"]):
            nxt = sel["days"][sel["index"]]
            bot.edit_message_text(
                f"E per **{nxt}**?",
                chat_id, msg,
                reply_markup=keyboard_hours(nxt),
                parse_mode="Markdown"
            )
        else:
            group["user_selections"].pop(uid, None)
            save_db()
            bot.edit_message_text(
                generate_summary(group),
                chat_id, msg,
                reply_markup=keyboard_days([]),
                parse_mode="Markdown"
            )
        return

# ============================================================
#                WEBHOOK
# ============================================================

@app.get("/")
def home():
    return "OK - Gym Apes Bot (Multigroup)", 200

@app.get("/ping")
def ping():
    return "pong", 200

@app.get("/setwebhook")
def set_webhook():
    bot.remove_webhook()
    bot.set_webhook(url=f"{APP_URL}/webhook/{WEBHOOK_SECRET}")
    return "Webhook impostato!", 200

@app.post(f"/webhook/{WEBHOOK_SECRET}")
def webhook():
    update = request.get_json()
    if update:
        bot.process_new_updates([telebot.types.Update.de_json(update)])
    return "OK", 200

if __name__ == "__main__":
    print("🚀 Bot running with webhook...")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))