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
#                DATABASE IN MEMORY + GIST PERSISTENCE
# ============================================================

days = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
hours = [f"dalle {h}:00" for h in range(9, 21)]
months = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]

db_trainings = {g: {o: [] for o in hours} for g in days}
user_selections = {}


def _gist_headers():
    return {
        "Authorization": f"Bearer {GIST_TOKEN}",
        "Accept": "application/vnd.github+json"
    }


def load_db():
    global db_trainings, user_selections
    try:
        url = f"https://api.github.com/gists/{GIST_ID}"
        resp = requests.get(url, headers=_gist_headers(), timeout=10)
        resp.raise_for_status()
        data = json.loads(resp.json()["files"][GIST_FILENAME]["content"])

        db_trainings = data.get("db_trainings", db_trainings)
        user_selections = data.get("user_selections", user_selections)

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
#                BOT LOGIC
# ============================================================

def is_owner(chat_id, user_id):
    try:
        admins = bot.get_chat_administrators(chat_id)
        return any(a.user.id == user_id and a.status == "creator" for a in admins)
    except:
        return False


def reset_trainings():
    global db_trainings, user_selections
    db_trainings = {g: {o: [] for o in hours} for g in days}
    user_selections = {}
    save_db()


def get_week_dates():
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    res = {}
    for i, g in enumerate(days):
        d = monday + timedelta(days=i)
        res[g] = (d.day, months[d.month - 1])
    return res


def generate_summary():
    summary = "🦍 **RIEPILOGO ALLENAMENTI SETTIMANALI** 🦍\n\n"
    week = get_week_dates()
    empty = True

    for g in days:
        lines = []
        for h in hours:
            people = db_trainings[g][h]
            if people:
                lines.append(f" {h}: {', '.join(people)}")
        if lines:
            day_num, month = week[g]
            summary += f"**{g} {day_num} {month}**\n" + "\n".join(lines) + "\n\n"
            empty = False

    if empty:
        summary += "_Nessuna prenotazione._"

    return summary


def keyboard_days(selected):
    markup = InlineKeyboardMarkup(row_width=2)
    for g in days:
        label = f"✅ {g}" if g in selected else g
        markup.add(InlineKeyboardButton(label, callback_data=f"selday_{g}"))
    markup.add(InlineKeyboardButton("🗑️ Cancella", callback_data="del_all"))
    if selected:
        markup.add(InlineKeyboardButton("➡️ CONFERMA", callback_data="confirm_days"))
    return markup


def keyboard_hours(day):
    markup = InlineKeyboardMarkup(row_width=3)
    for h in hours:
        markup.add(InlineKeyboardButton(h, callback_data=f"selhour_{day}_{h}"))
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
    name = c.from_user.first_name
    data = c.data
    chat = c.message.chat.id
    mid = c.message.message_id

    # ---------------- DELETE ALL ----------------
    if data == "del_all":
        for g in days:
            for h in hours:
                if name in db_trainings[g][h]:
                    db_trainings[g][h].remove(name)

        save_db()

        bot.edit_message_text(
            generate_summary(),
            chat, mid,
            reply_markup=keyboard_days([]),
            parse_mode="Markdown"
        )
        bot.answer_callback_query(c.id, "Prenotazioni cancellate.")
        return

    # ---------------- SELECT DAY ----------------
    if data.startswith("selday_"):
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

    # ---------------- CONFIRM DAYS ----------------
    if data == "confirm_days":
        if uid not in user_selections or not user_selections[uid]["days"]:
            bot.answer_callback_query(c.id, "Seleziona almeno un giorno!")
            return

        user_selections[uid]["index"] = 0
        first = user_selections[uid]["days"][0]

        bot.edit_message_text(
            f"Ottimo {name}! Per **{first}**, a che ora?",
            chat, mid,
            reply_markup=keyboard_hours(first),
            parse_mode="Markdown"
        )

        bot.answer_callback_query(c.id)
        return

    # ---------------- SELECT HOUR ----------------
    if data.startswith("selhour_"):
        _, day, hour = data.split("_", 2)

        if name not in db_trainings[day][hour]:
            db_trainings[day][hour].append(name)
            save_db()

        user_selections[uid]["index"] += 1
        idx = user_selections[uid]["index"]
        selected = user_selections[uid]["days"]

        if idx < len(selected):
            nxt = selected[idx]
            bot.edit_message_text(
                f"E per **{nxt}**?",
                chat, mid,
                reply_markup=keyboard_hours(nxt),
                parse_mode="Markdown"
            )
        else:
            del user_selections[uid]
            save_db()
            bot.edit_message_text(
                generate_summary(),
                chat, mid,
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
    return "Webhook set!", 200


@app.post(f"/webhook/{WEBHOOK_SECRET}")
def webhook():
    update = request.get_json()
    if update:
        bot.process_new_updates([telebot.types.Update.de_json(update)])
    return "OK", 200


# ============================================================
#                START SERVER
# ============================================================

if __name__ == "__main__":
    print("🚀 Bot running with webhook...")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))