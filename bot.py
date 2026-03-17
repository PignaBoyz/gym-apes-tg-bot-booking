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
APP_URL = os.environ.get("APP_URL")  # e.g., https://your-app.onrender.com
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "webhooksecret")

GIST_TOKEN = os.environ.get("GIST_TOKEN")
GIST_ID = os.environ.get("GIST_ID")
GIST_FILENAME = "allenamenti.json"

bot = telebot.TeleBot(TOKEN, threaded=False)
app = Flask(__name__)

# ============================================================
#                IN-MEMORY DB + GIST PERSISTENCE
# ============================================================

days = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
hours = [f"dalle {h}:00" for h in range(9, 21)]
months = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]

# Booking entry format (preferred):
# { "id": <int>, "first_name": "<str>", "username": "<str|None>" }
# Back-compat: old entries may be plain strings with just the name.

db_trainings = {g: {o: [] for o in hours} for g in days}
user_selections = {}   # { uid: {"days": [..], "index": int} }
delete_state = {}      # { uid: {"items": [(day, hour), ...], "selected": set[int]} }

def _gist_headers():
    return {
        "Authorization": f"Bearer {GIST_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

def _ensure_loaded_structure():
    """Back-compat safety: ensure the nested dict structure exists."""
    for g in days:
        if g not in db_trainings or not isinstance(db_trainings[g], dict):
            db_trainings[g] = {}
        for h in hours:
            if h not in db_trainings[g] or not isinstance(db_trainings[g][h], list):
                db_trainings[g][h] = []

def load_db():
    """Load JSON from Gist into db_trainings and user states (if present)."""
    global db_trainings, user_selections
    try:
        url = f"https://api.github.com/gists/{GIST_ID}"
        resp = requests.get(url, headers=_gist_headers(), timeout=10)
        resp.raise_for_status()
        gist = resp.json()
        content = gist["files"][GIST_FILENAME]["content"]
        data = json.loads(content)

        loaded = data.get("db_trainings")
        if isinstance(loaded, dict):
            db_trainings = loaded

        # optional: restore selection state if present (not required)
        user_selections = data.get("user_selections", {})

        _ensure_loaded_structure()
        print("✔ Loaded data from Gist")
    except Exception as e:
        print(f"[WARN] Cannot load Gist: {e}")

def save_db():
    """Save db_trainings and user selections back to Gist."""
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
        resp = requests.patch(url, headers=_gist_headers(), json=payload, timeout=10)
        resp.raise_for_status()
        print("✔ Saved data to Gist")
    except Exception as e:
        print(f"[WARN] Cannot save to Gist: {e}")

if GIST_TOKEN and GIST_ID:
    load_db()
else:
    print("⚠ Persistence disabled (missing GIST_TOKEN/GIST_ID)")

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

def display_label(entry):
    """Return 'FirstName (@username)' if username exists, else 'FirstName'.
       Support legacy string entries gracefully."""
    if isinstance(entry, dict):
        first = entry.get("first_name") or ""
        uname = entry.get("username")
        if uname:
            return f"{first} (@{uname})"
        return first or "?"
    # legacy string
    return str(entry)

def user_matches_entry(entry, uid, first_name):
    """True if this booking entry belongs to the given user."""
    if isinstance(entry, dict):
        return entry.get("id") == uid
    # legacy: match by first_name only
    return str(entry) == (first_name or "")

def generate_summary():
    txt = "🦍 **RIEPILOGO ALLENAMENTI SETTIMANALI** 🦍\n\n"
    week = get_week_dates()
    empty = True
    for g in days:
        lines = []
        for h in hours:
            ppl = db_trainings[g][h]
            if ppl:
                names = ", ".join(display_label(p) for p in ppl)
                lines.append(f" {h}: {names}")
        if lines:
            day_num, month = week[g]
            txt += f"**{g} {day_num} {month}**\n" + "\n".join(lines) + "\n\n"
            empty = False
    if empty:
        txt += "_Nessuna prenotazione._"
    return txt

def keyboard_days(selected):
    markup = InlineKeyboardMarkup(row_width=2)
    for g in days:
        label = f"✅ {g}" if g in selected else g
        markup.add(InlineKeyboardButton(label, callback_data=f"selgiorno_{g}"))
    markup.add(InlineKeyboardButton("🗑️ Cancella", callback_data="cancella_tutto"))
    if selected:
        markup.add(InlineKeyboardButton("➡️ CONFERMA GIORNI", callback_data="conferma_giorni"))
    return markup

def keyboard_hours(day):
    markup = InlineKeyboardMarkup(row_width=3)
    for h in hours:
        markup.add(InlineKeyboardButton(h, callback_data=f"selora_{day}_{h}"))
    return markup

def get_user_bookings(uid, first_name):
    """Return a list of (day, hour) pairs where the user has at least one entry."""
    items = []
    for d in days:
        for h in hours:
            if any(user_matches_entry(e, uid, first_name) for e in db_trainings[d][h]):
                items.append((d, h))
    return items

def _booking_label(day, hour, checked):
    return f"{'✅ ' if checked else ''}{day} — {hour}"

def keyboard_delete(bookings, selected):
    """Inline keyboard for deletion selection."""
    markup = InlineKeyboardMarkup(row_width=1)
    for i, (d, h) in enumerate(bookings):
        label = _booking_label(d, h, i in selected)
        markup.add(InlineKeyboardButton(label, callback_data=f"delpick_{i}"))
    if bookings:
        markup.add(
            InlineKeyboardButton("✅ Conferma eliminazione", callback_data="delconfirm"),
            InlineKeyboardButton("↩️ Annulla", callback_data="delcancel")
        )
    else:
        markup.add(InlineKeyboardButton("↩️ Chiudi", callback_data="delcancel"))
    return markup

# ============================================================
#                HANDLERS
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
    uname = c.from_user.username  # may be None
    data = c.data
    chat = c.message.chat.id
    mid = c.message.message_id

    # ---------------- SMART DELETE FLOW (entry point) ----------------
    if data == "cancella_tutto":
        bookings = get_user_bookings(uid, first)
        delete_state[uid] = {"items": bookings, "selected": set()}
        text = "Seleziona le prenotazioni da cancellare:"
        try:
            bot.edit_message_text(
                text, chat, mid,
                reply_markup=keyboard_delete(bookings, delete_state[uid]["selected"]),
                parse_mode="Markdown"
            )
        except:
            bot.send_message(
                chat, text,
                reply_markup=keyboard_delete(bookings, delete_state[uid]["selected"]),
                parse_mode="Markdown"
            )
        if not bookings:
            bot.answer_callback_query(c.id, "Non hai prenotazioni da cancellare.")
        else:
            bot.answer_callback_query(c.id)
        return

    # toggle selection of a booking row
    if data.startswith("delpick_"):
        idx = int(data.split("_", 1)[1])
        state = delete_state.get(uid)
        if not state:
            bot.answer_callback_query(c.id, "Sessione di cancellazione non attiva.")
            return
        if idx in state["selected"]:
            state["selected"].remove(idx)
        else:
            state["selected"].add(idx)
        try:
            bot.edit_message_reply_markup(
                chat, mid,
                reply_markup=keyboard_delete(state["items"], state["selected"])
            )
        except:
            pass
        bot.answer_callback_query(c.id)
        return

    # confirm deletion of all selected bookings
    if data == "delconfirm":
        state = delete_state.get(uid)
        if not state:
            bot.answer_callback_query(c.id, "Nessuna selezione da confermare.")
            return
        items = state["items"]
        selected = sorted(state["selected"])
        if not selected:
            bot.answer_callback_query(c.id, "Seleziona almeno una prenotazione.")
            return

        for i in selected:
            try:
                d, h = items[i]
            except Exception:
                continue
            # remove only this user's entries at (d, h)
            new_list = []
            for e in db_trainings[d][h]:
                if not user_matches_entry(e, uid, first):
                    new_list.append(e)
            db_trainings[d][h] = new_list

        save_db()
        delete_state.pop(uid, None)

        try:
            bot.edit_message_text(
                generate_summary(),
                chat, mid,
                reply_markup=keyboard_days([]),
                parse_mode="Markdown"
            )
        except:
            bot.send_message(chat, generate_summary(), reply_markup=keyboard_days([]), parse_mode="Markdown")

        bot.answer_callback_query(c.id, "Prenotazioni selezionate cancellate.")
        return

    # cancel deletion mode
    if data == "delcancel":
        delete_state.pop(uid, None)
        try:
            bot.edit_message_text(
                generate_summary(),
                chat, mid,
                reply_markup=keyboard_days([]),
                parse_mode="Markdown"
            )
        except:
            bot.send_message(chat, generate_summary(), reply_markup=keyboard_days([]), parse_mode="Markdown")
        bot.answer_callback_query(c.id, "Annullato.")
        return

    # ---------------- GIORNI: SELEZIONE ----------------
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

    # ---------------- GIORNI: CONFERMA E PASSA AGLI ORARI ----------------
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

    # ---------------- ORARI: SELEZIONE ----------------
    if data.startswith("selora_"):
        _, day, hour = data.split("_", 2)

        # prepare user's booking entry (robust)
        entry = {"id": uid, "first_name": first, "username": uname}

        # avoid duplicates for the same user in the same slot
        if not any(user_matches_entry(e, uid, first) for e in db_trainings[day][hour]):
            db_trainings[day][hour].append(entry)
            save_db()

        # next day or finish
        sel = user_selections.get(uid, {}).get("days", [])
        user_selections[uid]["index"] = user_selections.get(uid, {}).get("index", 0) + 1
        idx = user_selections[uid]["index"]

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
                    generate_summary(),
                    chat, mid,
                    reply_markup=keyboard_days([]),
                    parse_mode="Markdown"
                )
            except:
                bot.send_message(
                    chat, generate_summary(),
                    reply_markup=keyboard_days([]),
                    parse_mode="Markdown"
                )

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
#                START (LOCAL ONLY)
# ============================================================

if __name__ == "__main__":
    print("🚀 Bot running with webhook...")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))