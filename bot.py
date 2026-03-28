import os
import telebot
from flask import Flask, request as flask_request

from config import TOKEN, APP_URL, WEBHOOK_SECRET, GIST_TOKEN, GIST_ID
from database import GistDatabase
from booking import BookingService
from keyboards import Keyboards
from handlers import BotHandlers

# ---- Core instances ----
bot = telebot.TeleBot(TOKEN, threaded=False)
app = Flask(__name__)

db = GistDatabase()
if GIST_TOKEN and GIST_ID:
    db.load()

booking = BookingService(db)
keyboards = Keyboards()
BotHandlers(bot, db, booking, keyboards)

# ---- Webhook routes ----

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
    update = flask_request.get_json()
    if update:
        bot.process_new_updates([telebot.types.Update.de_json(update)])
    return "OK", 200

if __name__ == "__main__":
    print("🚀 Bot running with webhook…")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
