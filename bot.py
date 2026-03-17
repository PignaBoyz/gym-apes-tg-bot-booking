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
#                TIME SLOTS
# ============================================================

hours = (
    ["prima delle 9:00"] +
    [f"dalle {h}:00" for h in range(9, 21)] +
    ["dopo le 20:00"]
)

days = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
months = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]

# ============================================================
#                DATABASE + GIST PERSISTENCE
# ============================================================

db_trainings = {g: {o: [] for o in hours} for g in days}
user_selections = {}
delete_state = {}

def _gist_headers():
    return {
        "Authorization": f"Bearer {GIST_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

def _ensure_structure():
    for g in days:
        if g not in db_trainings:
            db_trainings[g] = {}
        for h in hours:
            if h not in db_trainings[g] or not isinstance(db_trainings[g][h], list):
                db_trainings[g][h] = []

def load_db():
    global db_trainings, user_selections
    try:
        url = f"https://api.github.com/gists/{GIST_ID}"
        r = requests.get(url, headers=_gist_headers(), timeout=10)
        r.raise_for_status()
        gist = r.json()
        content = gist["files"][GIST_FILENAME]["content"]
        data = json.loads(content)

        if isinstance(data.get("db_trainings"), dict):
            db_trainings = data["db_trainings"]
        user_selections = data.get("user_selections", {})

        _ensure_structure()
        print("✔ Loaded data from Gist")
    except Exception as e:
        print(f"[WARN] Cannot load Gist: {e}")

def save_db():
    try:
        payload = {
            "files": {
                GIST_FILENAME: {
                    "content": json.dumps({
                        "db_trainings": db_trainings,
                        "user_selections": user_selections
                    }, ensure_ascii=False, indent=2)
                }
            }
        }
        url = f"https://api.github.com/gists/{GIST_ID}"
        r = requests.patch(url, headers=_gist_headers(), json=payload, timeout=10)
        r.raise_for_status()
        print("✔ Saved data to Gist")
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

def reset_trainings():
    global db_trainings, user_selections, delete_state
    db_trainings = {g: {o: [] for o in hours} for g in days}
    user_selections = {}
    delete_state = {}
    save_db()

def get_week_dates():
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    res = {}
    for i, g in enumerate(days):
        d = monday + timedelta(days=i)
        res[g] = (d.day, months[d.month - 1])
    return res

def display_entry(entry):
    if isinstance(entry, dict):
        name = entry.get("first_name") or "?"
        uname = entry.get("username")
        return f"{name} (@{uname})" if uname else name
    return str(entry)

def matches_user(entry, uid, first_name):
    if isinstance(entry, dict):
        return entry.get("id") == uid
    return str(entry) == first_name

def generate_summary():
    txt = "🦍 **RIEPILOGO ALLENAMENTI SETTIMANALI** 🦍\n\n"
    week = get_week_dates()
    empty = True

    for g in days:
        lines = []
        for h in hours:
            ppl = db_trainings[g][h]
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
#                KEYBOARDS (2 columns except delete)
# ============================================================

def keyboard_days(selected):
    markup = InlineKeyboardMarkup()
    row = []

    for g in days:
        label = f"✅ {g}" if g in selected else g
        bt = InlineKeyboardButton(label, callback_data=f"selgiorno_{g}")
        row.append(bt)
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
    if len(row) == 1:
        markup.row(row[0])

    return markup

# 🔥 DELETE MENU IN ONE COLUMN (your request)
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

def get_user_bookings(uid, first_name):
    res = []
    for d in days:
        for h in hours:
            if any(matches_user(e, uid, first_name) for e in db_trainings[d][h]):
                res.append((d, h))
    return res

# ============================================================
#                BOT LOGIC
# ============================================================

@bot.message_handler(commands=["start", "allenamento"])
def start(message):
    if not is_owner(message.chat.id, message.from_user.id):
        bot.send_message(message.chat.id, "❌ Solo il proprietario può usare questo comando.")
        return

    reset_trainings()
    bot.send_message(
        message.chat.id,
        generate_summary(),
        reply_markup=keyboard_days([]),
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda c: True)
def callback(c):
    uid = c.from_user.id
    first = c.from_user.first_name or ""
    uname = c.from_user.username
    data = c.data
    chat = c.message.chat.id
    mid = c.message.message_id

    # --- DELETE MODE ---
    if data == "cancella_tutto":
        bookings = get_user_bookings(uid, first)
        delete_state[uid] = {"items": bookings, "selected": set()}
        try:
            bot.edit_message_text(
                "Seleziona le prenotazioni da cancellare:",
                chat, mid,
                reply_markup=keyboard_delete(bookings, delete_state[uid]["selected"]),
                parse_mode="Markdown"
            )
        except:
            bot.send_message(
                chat, "Seleziona le prenotazioni da cancellare:",
                reply_markup=keyboard_delete(bookings, delete_state[uid]["selected"]),
                parse_mode="Markdown"
            )
        return

    if data.startswith("delpick_"):
        idx = int(data.split("_", 1)[1])
        st = delete_state.get(uid)
        if not st:
            bot.answer_callback_query(c.id, "Sessione non attiva.")
            return

        if idx in st["selected"]:
            st["selected"].remove(idx)
        else:
            st["selected"].add(idx)

        try:
            bot.edit_message_reply_markup(
                chat, mid,
                reply_markup=keyboard_delete(st["items"], st["selected"])
            )
        except:
            pass

        bot.answer_callback_query(c.id)
        return

    if data == "delconfirm":
        st = delete_state.get(uid)
        if not st:
            bot.answer_callback_query(c.id)
            return

        for i in sorted(st["selected"]):
            d, h = st["items"][i]
            db_trainings[d][h] = [
                e for e in db_trainings[d][h]
                if not matches_user(e, uid, first)
            ]

        save_db()
        delete_state.pop(uid, None)

        try:
            bot.edit_message_text(
                generate_summary(), chat, mid,
                reply_markup=keyboard_days([]),
                parse_mode="Markdown"
            )
        except:
            bot.send_message(chat, generate_summary(), reply_markup=keyboard_days([]))

        bot.answer_callback_query(c.id, "Eliminato!")
        return

    if data == "delcancel":
        delete_state.pop(uid, None)
        try:
            bot.edit_message_text(
                generate_summary(), chat, mid,
                reply_markup=keyboard_days([]),
                parse_mode="Markdown"
            )
        except:
            bot.send_message(chat, generate_summary(), reply_markup=keyboard_days([]))
        return

    # --- SELECT DAYS ---
    if data.startswith("selgiorno_"):
        day = data.split("_", 1)[1]
        if uid not in user_selections:
            user_selections[uid] = {"days": [], "index": 0}

        if day in user_selections[uid]["days"]:
            user_selections[uid]["days"].remove(day)
        else:
            user_selections[uid]["days"].append(day)

        try:
            bot.edit_message_reply_markup(
                chat, mid,
                reply_markup=keyboard_days(user_selections[uid]["days"])
            )
        except:
            pass

        bot.answer_callback_query(c.id)
        return

    # --- CONFIRM DAYS ---
    if data == "conferma_giorni":
        if uid not in user_selections or not user_selections[uid]["days"]:
            bot.answer_callback_query(c.id, "Seleziona almeno un giorno!")
            return

        user_selections[uid]["index"] = 0
        first_day = user_selections[uid]["days"][0]

        try:
            bot.edit_message_text(
                f"Ottimo {first}! Per **{first_day}**, a che ora ci sarai?",
                chat, mid,
                reply_markup=keyboard_hours(first_day),
                parse_mode="Markdown"
            )
        except:
            bot.send_message(
                chat,
                f"Ottimo {first}! Per **{first_day}**, a che ora ci sarai?",
                reply_markup=keyboard_hours(first_day),
                parse_mode="Markdown"
            )

        bot.answer_callback_query(c.id)
        return

    # --- SELECT HOUR ---
    if data.startswith("selora_"):
        _, d, h = data.split("_", 2)

        entry = {"id": uid, "first_name": first, "username": uname}

        if not any(matches_user(e, uid, first) for e in db_trainings[d][h]):
            db_trainings[d][h].append(entry)
            save_db()

        sel = user_selections[uid]["days"]
        idx = user_selections[uid]["index"] + 1
        user_selections[uid]["index"] = idx

        if idx < len(sel):
            nxt = sel[idx]
            try:
                bot.edit_message_text(
                    f"E per **{nxt}**?",
                    chat, mid,
                    reply_markup=keyboard_hours(nxt),
                    parse_mode="Markdown"
                )
            except:
                bot.send_message(
                    chat, f"E per **{nxt}**?",
                    reply_markup=keyboard_hours(nxt),
                    parse_mode="Markdown"
                )
        else:
            user_selections.pop(uid, None)
            save_db()
            try:
                bot.edit_message_text(
                    generate_summary(), chat, mid,
                    reply_markup=keyboard_days([]),
                    parse_mode="Markdown"
                )
            except:
                bot.send_message(chat, generate_summary(), reply_markup=keyboard_days([]))

        bot.answer_callback_query(c.id, "Registrato!")
        return

# ============================================================
#                WEBHOOK ENDPOINTS
# ============================================================

@app.get("/")
def home():
    return "OK - Gym Apes Bot running", 200

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

# ============================================================
#                START
# ============================================================

if __name__ == "__main__":
    print("🚀 Bot running with webhook...")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
