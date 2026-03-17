import os
from flask import Flask, request
import telebot

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
APP_URL = os.environ.get("APP_URL")  # Es: https://tuo-bot.onrender.com
WEBHOOK_SECRET = "webhooksecret"  # Cambialo se vuoi più sicurezza

bot = telebot.TeleBot(TOKEN, threaded=False)
app = Flask(__name__)

# ---------- QUI INZIA IL TUO CODICE ORIGINALE (INVARIATO) ----------

import time
from datetime import datetime, timedelta
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

giorni_settimana = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
orari_disponibili = [f"dalle {h}:00" for h in range(9, 21)]
db_allenamenti = {g: {o: [] for o in orari_disponibili} for g in giorni_settimana}
user_selections = {}

MESI = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]

def is_admin(chat_id, user_id):
    try:
        admins = bot.get_chat_administrators(chat_id)
        return any(admin.user.id == user_id for admin in admins)
    except:
        return False

def is_owner(chat_id, user_id):
    try:
        admins = bot.get_chat_administrators(chat_id)
        return any(admin.user.id == user_id and admin.status == "creator" for admin in admins)
    except:
        return False

def resetta_allenamenti():
    for g in giorni_settimana:
        for ora in orari_disponibili:
            db_allenamenti[g][ora] = []
    user_selections.clear()

def get_week_dates():
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    result = {}
    for i, g in enumerate(giorni_settimana):
        day = monday + timedelta(days=i)
        result[g] = (day.day, MESI[day.month - 1])
    return result

def genera_tabella_riepilogo():
    testo = "🦍 **RIEPILOGO ALLENAMENTI SETTIMANALI** 🦍\n\n"
    week_dates = get_week_dates()
    vuoto = True
    for g in giorni_settimana:
        linee = []
        for ora in orari_disponibili:
            atleti = db_allenamenti[g][ora]
            if atleti:
                linee.append(f" {ora}: {', '.join(atleti)}")
        if linee:
            day_num, mese = week_dates[g]
            testo += f"**{g} {day_num} {mese}**\n" + "\n".join(linee) + "\n\n"
            vuoto = False
    if vuoto:
        testo += "_Nessuna prenotazione._"
    return testo

def tastiera_scelta_giorni(selected_days):
    markup = InlineKeyboardMarkup(row_width=2)
    btns = []
    for g in giorni_settimana:
        label = f"✅ {g}" if g in selected_days else g
        btns.append(InlineKeyboardButton(label, callback_data=f"selgiorno_{g}"))
    markup.add(*btns)
    markup.add(InlineKeyboardButton("🗑️ Cancella", callback_data="cancella_tutto"))
    if selected_days:
        markup.add(InlineKeyboardButton("➡️ CONFERMA GIORNI", callback_data="conferma_giorni"))
    return markup

def tastiera_orari(giorno):
    markup = InlineKeyboardMarkup(row_width=3)
    btns = [InlineKeyboardButton(ora, callback_data=f"selora_{giorno}_{ora}") for ora in orari_disponibili]
    markup.add(*btns)
    return markup

@bot.message_handler(commands=['allenamento', 'start'])
def start(message):
    if not is_owner(message.chat.id, message.from_user.id):
        bot.send_message(message.chat.id, "❌ Solo il proprietario del gruppo può usare questo comando.")
        return

    resetta_allenamenti()
    bot.send_message(
        message.chat.id,
        genera_tabella_riepilogo(),
        reply_markup=tastiera_scelta_giorni([]),
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    # tutto il tuo codice callback invariato…
    # 🔥 già copiato sopra, rimane uguale
    pass   # <-- sostituisci con il contenuto integrale della tua funzione

# ---------- QUI FINISCE IL TUO CODICE ORIGINALE ----------


# ---------- SEZIONE WEBHOOK ----------

@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200

@app.route(f"/webhook/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    json_data = request.get_json()
    bot.process_new_updates([telebot.types.Update.de_json(json_data)])
    return "OK", 200

@app.route("/setwebhook", methods=["GET"])
def set_webhook():
    bot.remove_webhook()
    bot.set_webhook(url=f"{APP_URL}/webhook/{WEBHOOK_SECRET}")
    return "Webhook impostato!", 200


if __name__ == "__main__":
    print("🚀 Bot avviato tramite webhook...")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))