import os
import json
import requests
from flask import Flask, request
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta

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
#                MULTIGROUP DATABASE (PERSISTED)
# ============================================================

GLOBAL_DB = {"groups": {}}

def ensure_group(chat_id):
    cid = str(chat_id)
    if cid not in GLOBAL_DB["groups"]:
        GLOBAL_DB["groups"][cid] = {
            "db": {g: {h: [] for h in hours} for g in days},
            "user_selections": {},
            "active_forms": {}  # { uid: mid } - track which message_id is the active form
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
        resp = requests.get(url, headers=_gist_headers(), timeout=10)
        resp.raise_for_status()
        gist = resp.json()
        content = gist["files"][GIST_FILENAME]["content"]
        data = json.loads(content)

        if isinstance(data, dict) and "groups" in data:
            GLOBAL_DB = data
            print("✔ Loaded multi-group DB")
        else:
            GLOBAL_DB = {"groups": {}}
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
        resp = requests.patch(url, headers=_gist_headers(), json=payload, timeout=10)
        resp.raise_for_status()
        print("✔ Saved multi-group DB")
    except Exception as e:
        print(f"[WARN] Cannot save Gist: {e}")


if GIST_TOKEN and GIST_ID:
    load_db()

# ============================================================
#         RUNTIME-ONLY DELETE STATE (NOT PERSISTED)
# ============================================================

DELETE_STATE = {}   # { "<chat_id>": { uid: {"items": [(day,hour)], "selected": set() } } }

def _ensure_delete_state(chat_id, uid, first_name, group):
    """Rebuild delete state if absent (e.g. restart / redeploy)."""
    chat_key = str(chat_id)
    if chat_key not in DELETE_STATE:
        DELETE_STATE[chat_key] = {}

    state = DELETE_STATE[chat_key].get(uid)
    if not state:
        # Rebuild available bookings
        items = []
        for d in days:
            for h in hours:
                if any(matches_user(e, uid, first_name) for e in group["db"][d][h]):
                    items.append((d, h))
        state = {"items": items, "selected": set()}
        DELETE_STATE[chat_key][uid] = state

    return state

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
    group["db"] = {g: {h: [] for h in hours} for g in days}
    group["user_selections"] = {}
    group["active_forms"] = {}
    save_db()

def get_week_dates():
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    out = {}
    for i, g in enumerate(days):
        d = monday + timedelta(days=i)
        out[g] = (d.day, months[d.month - 1])
    return out

def matches_user(entry, uid, name):
    if isinstance(entry, dict):
        return entry.get("id") == uid
    return str(entry) == name

def display_entry(entry):
    if isinstance(entry, dict):
        nm = entry.get("first_name") or "?"
        un = entry.get("username")
        return f"{nm} (@{un})" if un else nm
    return str(entry)

def get_user_bookings(group, uid, first_name):
    res = []
    for d in days:
        for h in hours:
            if any(matches_user(e, uid, first_name) for e in group["db"][d][h]):
                res.append((d, h))
    return res

def generate_summary(group):
    txt = "🦍 **RIEPILOGO ALLENAMENTI SETTIMANALI** 🦍\n\n"
    wd = get_week_dates()
    empty = True

    for d in days:
        lines = []
        for h in hours:
            ppl = group["db"][d][h]
            if ppl:
                names = ", ".join(display_entry(p) for p in ppl)
                lines.append(f" {h}: {names}")
        if lines:
            dayn, m = wd[d]
            txt += f"**{d} {dayn} {m}**\n" + "\n".join(lines) + "\n\n"
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
    for d in days:
        label = f"✅ {d}" if d in selected else d
        btn = InlineKeyboardButton(label, callback_data=f"selgiorno_{d}")
        row.append(btn)
        if len(row) == 2:
            markup.row(*row)
            row = []
    if row:
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
#                HANDLERS
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

@bot.callback_query_handler(func=lambda c: True)
def callback(c):
    chat_id = c.message.chat.id
    group = ensure_group(chat_id)

    uid = c.from_user.id
    first = c.from_user.first_name or ""
    uname = c.from_user.username
    data = c.data
    mid = c.message.message_id

    # Verifica se questo messaggio è il form attivo di questo utente
    active_forms = group.get("active_forms", {})
    if str(uid) in active_forms and active_forms[str(uid)] != mid:
        # Ignora click su form non attivi
        bot.answer_callback_query(c.id)
        return

    # ============================================================
    #                DELETE MODE
    # ============================================================

    if data == "cancella_tutto":
        st = _ensure_delete_state(chat_id, uid, first, group)
        group.setdefault("active_forms", {})[str(uid)] = mid
        save_db()
        
        try:
            bot.edit_message_text(
                "Seleziona le prenotazioni da cancellare:",
                chat_id, mid,
                reply_markup=keyboard_delete(st["items"], st["selected"]),
                parse_mode="Markdown"
            )
        except:
            bot.send_message(
                chat_id, "Seleziona le prenotazioni da cancellare:",
                reply_markup=keyboard_delete(st["items"], st["selected"]),
                parse_mode="Markdown"
            )
        return

    if data.startswith("delpick_"):
        st = _ensure_delete_state(chat_id, uid, first, group)
        try:
            idx = int(data.split("_", 1)[1])
        except ValueError:
            bot.answer_callback_query(c.id, "Selezione non valida.")
            return

        if 0 <= idx < len(st["items"]):
            if idx in st["selected"]:
                st["selected"].remove(idx)
            else:
                st["selected"].add(idx)

        try:
            bot.edit_message_reply_markup(
                chat_id, mid,
                reply_markup=keyboard_delete(st["items"], st["selected"])
            )
        except:
            pass

        bot.answer_callback_query(c.id)
        return

    if data == "delconfirm":
        st = DELETE_STATE.get(str(chat_id), {}).get(uid)
        if not st or not st["selected"]:
            group.get("active_forms", {}).pop(str(uid), None)
            save_db()
            try:
                bot.edit_message_text(
                    generate_summary(group), chat_id, mid,
                    reply_markup=InlineKeyboardMarkup(), parse_mode="Markdown"
                )
            except:
                bot.send_message(chat_id, generate_summary(group), parse_mode="Markdown")
            bot.answer_callback_query(c.id, "Nessuna selezione da cancellare.")
            return

        for i in sorted(st["selected"]):
            d, h = st["items"][i]
            group["db"][d][h] = [
                e for e in group["db"][d][h]
                if not matches_user(e, uid, first)
            ]

        # cleanup RAM-only state
        DELETE_STATE[str(chat_id)].pop(uid, None)
        group.get("active_forms", {}).pop(str(uid), None)

        save_db()

        try:
            bot.edit_message_text(
                generate_summary(group), chat_id, mid,
                reply_markup=InlineKeyboardMarkup(), parse_mode="Markdown"
            )
        except:
            bot.send_message(chat_id, generate_summary(group), parse_mode="Markdown")

        bot.answer_callback_query(c.id, "Prenotazioni selezionate cancellate.")
        return

    if data == "delcancel":
        if str(chat_id) in DELETE_STATE:
            DELETE_STATE[str(chat_id)].pop(uid, None)
        
        group.get("active_forms", {}).pop(str(uid), None)
        save_db()

        try:
            bot.edit_message_text(
                generate_summary(group), chat_id, mid,
                reply_markup=InlineKeyboardMarkup(), parse_mode="Markdown"
            )
        except:
            bot.send_message(chat_id, generate_summary(group), parse_mode="Markdown")
        bot.answer_callback_query(c.id, "Annullato.")
        return

    # ============================================================
    #                DAY SELECTION
    # ============================================================

    if data.startswith("selgiorno_"):
        d = data.split("_", 1)[1]
        sel = group["user_selections"].setdefault(uid, {"days": [], "index": 0})
        group.setdefault("active_forms", {})[str(uid)] = mid
        save_db()

        if d in sel["days"]:
            sel["days"].remove(d)
        else:
            sel["days"].append(d)

        save_db()

        try:
            bot.edit_message_reply_markup(
                chat_id, mid, reply_markup=keyboard_days(sel["days"])
            )
        except:
            pass

        bot.answer_callback_query(c.id)
        return

    # ============================================================
    #                CONFIRM DAYS
    # ============================================================

    if data == "conferma_giorni":
        sel = group["user_selections"].get(uid)
        if not sel or not sel["days"]:
            bot.answer_callback_query(c.id, "Seleziona almeno un giorno!")
            return

        sel["index"] = 0
        d0 = sel["days"][0]
        group.setdefault("active_forms", {})[str(uid)] = mid
        save_db()

        try:
            bot.edit_message_text(
                f"Ottimo {first}! Per **{d0}**, a che ora ci sarai?",
                chat_id, mid,
                reply_markup=keyboard_hours(d0),
                parse_mode="Markdown"
            )
        except:
            bot.send_message(
                chat_id,
                f"Ottimo {first}! Per **{d0}**, a che ora ci sarai?",
                reply_markup=keyboard_hours(d0),
                parse_mode="Markdown"
            )
        bot.answer_callback_query(c.id)
        return

    # ============================================================
    #                HOUR SELECTION
    # ============================================================

    if data.startswith("selora_"):
        _, d, h = data.split("_", 2)
        sel = group["user_selections"][uid]

        entry = {"id": uid, "first_name": first, "username": uname}

        # avoid duplicates
        if not any(matches_user(e, uid, first) for e in group["db"][d][h]):
            group["db"][d][h].append(entry)
            save_db()

        sel["index"] += 1
        if sel["index"] < len(sel["days"]):
            nxt = sel["days"][sel["index"]]
            try:
                bot.edit_message_text(
                    f"E per **{nxt}**?",
                    chat_id, mid,
                    reply_markup=keyboard_hours(nxt),
                    parse_mode="Markdown"
                )
            except:
                bot.send_message(
                    chat_id,
                    f"E per **{nxt}**?",
                    reply_markup=keyboard_hours(nxt),
                    parse_mode="Markdown"
                )
        else:
            # ✅ COMPLETED - Rimozione dello stato e chiusura del form
            group["user_selections"].pop(uid, None)
            group.get("active_forms", {}).pop(str(uid), None)
            save_db()

            try:
                bot.edit_message_text(
                    generate_summary(group), chat_id, mid,
                    reply_markup=InlineKeyboardMarkup(), parse_mode="Markdown"
                )
            except:
                bot.send_message(chat_id, generate_summary(group), parse_mode="Markdown")

        bot.answer_callback_query(c.id, "Registrato!")
        return

# ============================================================
#                WEBHOOK ENDPOINTS
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

# ============================================================
#                START
# ============================================================

if __name__ == "__main__":
    print("🚀 Bot running with webhook…")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))