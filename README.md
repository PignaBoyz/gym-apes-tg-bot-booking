
# Gym Apes Bot — Multi-Group Version

This is the **multi-group upgrade** of the Gym Apes Telegram bot.

✔ Works in **any number of groups**  
✔ Each group has **its own independent database**  
✔ No data conflicts  
✔ Fully free (Render Free Tier + GitHub Gist)  
✔ Webhook-based (no polling)  
✔ Persistent storage via GitHub Gist  
✔ Perfect for training booking workflows

---

## 🚀 Features

### 🦍 Multi-group logic

Each Telegram group gets its **own storage**, kept inside a single GitHub Gist:

```json
{
"groups": {
"-1001234567890": { ... },
"-1009876543210": { ... }
}
}
```

Groups never interfere with each other.

---

### 🧮 Booking Flow

- Only the **group creator** can start `/start`
- Users select:
  - **days** (2-column layout)
  - **hours** (2-column layout, including “before 9:00” and “after 20:00”)
- Bookings stored as:
  - first name
  - @username (if available)
  - Telegram user ID

---

### 🗑 Smart Delete (1-column UI)

A user can open *Cancellazione*, see **only their bookings**, select which ones to delete, and confirm.

---

### 🧠 Persistence

Uses a **GitHub Gist** as a lightweight JSON database.

Environment variables:

| Key | Description |
|-----|-------------|
| `GIST_TOKEN` | GitHub Fine-Grained Token with “Gists: Read & Write” |
| `GIST_ID` | ID of the secret Gist |
| `TELEGRAM_BOT_TOKEN` | Bot API Token |
| `APP_URL` | Render public URL (without trailing slash) |
| `WEBHOOK_SECRET` | Secret path for the webhook |

---

## 🏗 Deployment (Render)

1. Push code to GitHub
2. Create **New Web Service** on Render
3. Runtime: **Python**
4. Build command: `pip install -r requirements.txt`
5. Start command: `gunicorn -b 0.0.0.0:$PORT bot:app`
6. Add environment variables:

- `TELEGRAM_BOT_TOKEN`
- `APP_URL`
- `GIST_TOKEN`
- `GIST_ID`
- `WEBHOOK_SECRET`

1. Deploy

After first deploy, open:
`https://YOURAPP.onrender.com/setwebhook`

Webhook is now active.

---

## 💤 Keep the bot awake (Render Free Tier)

Render sleeps after ~15 minutes with no HTTP requests.  
Use:
`https://hosting.aifordiscord.xyz`
Register:
`https://YOURAPP.onrender.com/ping`
This hits the bot every 5 minutes and keeps it awake.

---

## 🧪 Test in Telegram

1. Add the bot to a group  
2. The **creator** of the group runs:
/start

3. The booking UI appears
4. Everything is saved automatically to the Gist

---

## 📄 License

MIT (free to use, modify, share)
