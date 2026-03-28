# Gym Apes Bot — Multi-Group Booking

Bot Telegram per la prenotazione degli allenamenti settimanali in palestra.
Ogni gruppo ha il suo database indipendente. Tutto gratuito (Render Free Tier + GitHub Gist).

---

## 📁 Struttura del progetto

| File | Responsabilità |
|------|----------------|
| `bot.py` | Entry point: Flask, webhook routes |
| `config.py` | Variabili d'ambiente, costanti (giorni, orari, stati FSM) |
| `database.py` | `GistDatabase`: persistenza su GitHub Gist, gestione sessioni |
| `booking.py` | `BookingService`: logica di dominio (prenotazioni, riepilogo) |
| `keyboards.py` | `Keyboards`: costruzione dei bottoni inline di Telegram |
| `handlers.py` | `BotHandlers`: gestione comandi, FSM, anti-spam |

---

## 🚀 Flusso di utilizzo

### 1. Avvio settimanale (solo Admin)

Il **creatore del gruppo** lancia il comando `/allenamento`:

1. Il bot verifica che chi ha scritto sia il **creator** del gruppo
2. Cancella tutte le prenotazioni della settimana precedente
3. Invalida tutte le sessioni di prenotazione aperte
4. Invia un messaggio nel gruppo con il riepilogo vuoto e due bottoni:
   - **"📅 Prenota il tuo allenamento"**
   - **"🗑️ Gestisci mie prenotazioni"**
5. Questo messaggio diventa il **Tabellone** del gruppo (può essere fissato/pinnato)

> ⚠️ Solo il creatore del gruppo può lanciare `/allenamento`. Gli altri utenti ricevono un errore.

---

### 2. Prenotazione (qualsiasi membro del gruppo)

```
GRUPPO                                  CHAT PRIVATA COL BOT
  │                                          │
  │  Click "📅 Prenota"                      │
  │──────────────────────────────────────────▶│
  │                                          │  Bot manda: "Seleziona i giorni"
  │                                          │  con bottoni Lun, Mar, Mer...
  │                                          │
  │                                          │  Utente clicca Lun ✅
  │                                          │  Utente clicca Mer ✅
  │                                          │  Utente clicca Ven ✅
  │                                          │  Utente clicca "➡️ CONFERMA GIORNI"
  │                                          │
  │                                          │  Bot: "Per Lunedì, a che ora?"
  │                                          │  Utente: "dalle 10:00"
  │                                          │
  │                                          │  Bot: "Per Mercoledì, a che ora?"
  │                                          │  Utente: "dalle 15:00"
  │                                          │
  │                                          │  Bot: "Per Venerdì, a che ora?"
  │                                          │  Utente: "dalle 18:00"
  │                                          │
  │                                          │  "✅ Prenotazione completata!"
  │◀─────────────────────────────────────────│
  │  Tabellone aggiornato                    │
  │  con i dati dell'utente                  │
```

**Passo per passo:**

1. L'utente clicca **"📅 Prenota"** nel Tabellone del gruppo
2. Il bot gli scrive in **chat privata** (DM) con i bottoni dei 7 giorni
3. L'utente seleziona/deseleziona i giorni (toggle ✅/normale)
4. Clicca **"➡️ CONFERMA GIORNI"**
5. Il bot chiede l'orario per ogni giorno selezionato, uno alla volta
6. A procedura completata:
   - Il messaggio privato mostra "✅ Prenotazione completata!"
   - Il Tabellone nel **gruppo** si aggiorna automaticamente con i nuovi dati

> 💡 **Nota**: La selezione avviene tutta in chat privata. Nessun altro membro del gruppo vede cosa stai scegliendo.

> ⚠️ Se il bot non riesce a scriverti in privato, vedrai un avviso: "Avvia il bot in privato prima!". Vai nella chat col bot e premi **"Avvia"** (o `/start`), poi riprova.

---

### 3. Cancellazione prenotazioni

1. L'utente clicca **"🗑️ Gestisci mie prenotazioni"** nel Tabellone del gruppo
2. Il bot manda in **chat privata** la lista delle sue prenotazioni attive con checkbox
3. L'utente seleziona quelle da eliminare (✅)
4. Clicca **"✅ Conferma eliminazione"**
5. Le prenotazioni vengono rimosse e il Tabellone nel gruppo si aggiorna

> Se l'utente non ha prenotazioni, riceve un avviso: "Non hai prenotazioni da cancellare!"

---

### 4. Annullamento

In qualsiasi momento durante la selezione (giorni, orari, cancellazione), l'utente può premere **"❌ Annulla"** per uscire senza modificare nulla.

---

## 🛡️ Gestione delle interazioni critiche

### Anti-spam: click multipli

Se un utente clicca 20 volte in un secondo su un bottone:
- **Solo il primo click** viene elaborato
- Gli altri 19 ricevono un toast "⏳ Sto elaborando..."
- Il lock viene rilasciato appena il primo click è stato gestito

### Isolamento multi-utente

Ogni utente ha la **propria sessione** separata (identificata dal suo User ID):
- Utente A sceglie i giorni → lavora nel **suo** messaggio privato
- Utente B sceglie gli orari → lavora nel **suo** messaggio privato
- **Zero interferenze**: le sessioni non si toccano mai, i messaggi sono in chat private diverse

### Sessione stale (doppio "Prenota")

Se un utente clicca "Prenota" quando ha già una sessione aperta:
1. Il vecchio messaggio privato viene chiuso ("Sessione precedente annullata")
2. La vecchia sessione viene cancellata
3. Si apre una sessione nuova e pulita

### Click su form vecchi/scaduti

Ogni sessione salva l'ID del messaggio attivo. Se l'utente clicca su un messaggio che non è quello corrente, il click viene ignorato silenziosamente.

### FSM rigida (Macchina a Stati)

Il bot segue un flusso a stati rigido:

```
IDLE → SELECT_DAYS → SELECT_HOURS → completato
                                  ↘ annullato
IDLE → DELETING → completato
               ↘ annullato
```

- Nello stato `SELECT_DAYS`: accetta solo selezione giorni e conferma
- Nello stato `SELECT_HOURS`: accetta solo selezione orari
- Nello stato `DELETING`: accetta solo selezione/conferma cancellazione
- Click fuori dal flusso previsto → ignorati

### Lazy Save (Gist lento)

- Durante la selezione (giorni, checkbox): il salvataggio su Gist avviene **al massimo ogni 10 secondi** (debounce)
- Alla **conferma finale**: salvataggio **immediato** (i dati definitivi non possono andare persi)
- L'interfaccia è sempre reattiva perché i dati cambiano istantaneamente in memoria

---

## 🧮 Struttura dati (Gist)

Il Gist contiene un singolo file JSON con questa struttura:

```json
{
  "groups": {
    "-1001234567890": {
      "db": {
        "Lunedì": {
          "prima delle 9:00": [],
          "dalle 9:00": [
            { "id": 123456, "first_name": "Marco", "username": "marco92" }
          ],
          "dalle 10:00": []
        }
      },
      "main_message_id": 4567
    }
  },
  "sessions": {
    "123456": {
      "state": "SELECT_DAYS",
      "original_chat_id": -1001234567890,
      "active_form_mid": 789,
      "days": ["Lunedì", "Mercoledì"],
      "index": 0
    }
  }
}
```

- **`groups`**: dati di ogni gruppo (prenotazioni + ID del messaggio Tabellone)
- **`sessions`**: sessioni attive degli utenti (stato FSM, giorni scelti, ecc.)

Le sessioni vivono al livello top-level (non dentro un gruppo) perché devono essere accessibili sia dal gruppo che dalla chat privata.

---

## 🧠 Persistenza

Usa un **GitHub Gist** come database JSON leggero.

### Variabili d'ambiente richieste

| Variabile | Descrizione |
|-----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Token del bot da @BotFather |
| `APP_URL` | URL pubblico di Render (senza slash finale) |
| `WEBHOOK_SECRET` | Path segreto per il webhook |
| `GIST_TOKEN` | GitHub Fine-Grained Token con permesso "Gists: Read & Write" |
| `GIST_ID` | ID del Gist segreto |

---

## 🏗 Deploy su Render

1. Pusha il codice su GitHub
2. Su Render crea un **New Web Service**
3. Runtime: **Python**
4. Build command: `pip install -r requirements.txt`
5. Start command: `gunicorn -b 0.0.0.0:$PORT bot:app`
6. Aggiungi le variabili d'ambiente elencate sopra
7. Deploy

Dopo il primo deploy, apri nel browser:
```
https://TUOBOT.onrender.com/setwebhook
```
Il webhook è ora attivo.

---

## 💤 Mantenere il bot sveglio (Render Free Tier)

Render mette in pausa il servizio dopo ~15 minuti senza richieste HTTP.

Registra l'endpoint `/ping` su [https://hosting.aifordiscord.xyz](https://hosting.aifordiscord.xyz):
```
https://TUOBOT.onrender.com/ping
```
Questo pinga il bot ogni 5 minuti e lo tiene attivo.

---

## 🧪 Test rapido

1. Aggiungi il bot a un gruppo Telegram
2. Il **creatore** del gruppo lancia `/allenamento`
3. Appare il Tabellone con i due bottoni
4. Clicca "📅 Prenota" e segui il flusso in chat privata
5. Verifica che il Tabellone si aggiorni dopo la conferma

---

## 📄 Licenza

MIT (libero di usare, modificare, condividere)
