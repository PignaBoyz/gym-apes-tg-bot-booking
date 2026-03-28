import telebot

from config import STATE_SELECT_DAYS, STATE_SELECT_HOURS, STATE_DELETING


class BotHandlers:
    """
    Single responsibility: register Telegram handlers and orchestrate the FSM.

    The FSM has three states per user session:
      SELECT_DAYS  → user picks training days in private chat
      SELECT_HOURS → user picks the hour for each selected day
      DELETING     → user selects bookings to remove

    Sessions are stored at the top-level of GistDatabase (not inside a group),
    so they are accessible whether the callback comes from the group or from
    the user's private chat.

    Anti-spam: a per-user lock (self._processing) ensures that rapid clicks
    are discarded until the current action completes.
    """

    def __init__(self, bot: telebot.TeleBot, db, booking, keyboards):
        self._bot = bot
        self._db = db
        self._booking = booking
        self._kb = keyboards
        self._processing: set = set()
        self._register()

    # ------------------------------------------------------------------ #
    #  Handler registration                                                #
    # ------------------------------------------------------------------ #

    def _register(self):
        self._bot.message_handler(commands=["start", "allenamento"])(self._cmd_start)
        self._bot.callback_query_handler(func=lambda c: True)(self._callback)

    # ------------------------------------------------------------------ #
    #  Command: /allenamento (admin only)                                  #
    # ------------------------------------------------------------------ #

    def _cmd_start(self, message):
        chat_id = message.chat.id
        if message.chat.type == "private":
            self._bot.send_message(
                chat_id,
                "Usa questo bot nei gruppi per gestire le prenotazioni degli allenamenti!"
            )
            return

        group = self._db.ensure_group(chat_id)
        if not self._booking.is_owner(self._bot, chat_id, message.from_user.id):
            self._bot.send_message(chat_id, "❌ Solo il proprietario può usare questo comando.")
            return

        self._booking.reset_group(group)
        self._db.clear_sessions_for_group(chat_id)

        msg = self._bot.send_message(
            chat_id,
            self._booking.generate_summary(group),
            reply_markup=self._kb.main_group(),
            parse_mode="Markdown"
        )
        group["main_message_id"] = msg.message_id
        self._db.save()

    # ------------------------------------------------------------------ #
    #  Callback entry point with anti-spam lock                           #
    # ------------------------------------------------------------------ #

    def _callback(self, c):
        uid = c.from_user.id
        if uid in self._processing:
            self._bot.answer_callback_query(c.id, "⏳ Sto elaborando...")
            return

        self._processing.add(uid)
        try:
            self._dispatch(c)
        except Exception as e:
            print(f"[ERROR] callback uid={uid}: {e}")
        finally:
            self._processing.discard(uid)

    # ------------------------------------------------------------------ #
    #  Dispatcher                                                          #
    # ------------------------------------------------------------------ #

    def _dispatch(self, c):
        uid = c.from_user.id
        chat_id = c.message.chat.id
        mid = c.message.message_id
        data = c.data
        first = c.from_user.first_name or "Gym Ape"
        uname = c.from_user.username

        # Entry point: user clicks a button on the GROUP pinned message
        if data in ("start_booking", "start_delete"):
            self._handle_group_entry(c, uid, chat_id, first, data)
            return

        # All subsequent FSM steps happen in the user's PRIVATE chat
        session = self._db.get_session(uid)
        if not session:
            self._bot.answer_callback_query(c.id, "Sessione scaduta. Torna nel gruppo.")
            return

        # Ignore clicks on messages other than the current active form
        if session.get("active_form_mid") != mid:
            self._bot.answer_callback_query(c.id)
            return

        if data == "exit_private":
            self._bot.edit_message_text("Annullato.", chat_id, mid)
            self._db.delete_session(uid)
            self._db.save_lazy()
            self._bot.answer_callback_query(c.id)
            return

        state = session["state"]
        if state == STATE_SELECT_DAYS:
            self._handle_select_days(c, uid, chat_id, mid, data, session)
        elif state == STATE_SELECT_HOURS:
            self._handle_select_hours(c, uid, chat_id, mid, data, session, first, uname)
        elif state == STATE_DELETING:
            self._handle_deleting(c, uid, chat_id, mid, data, session, first)

    # ------------------------------------------------------------------ #
    #  Group entry: redirect user to private chat                         #
    # ------------------------------------------------------------------ #

    def _handle_group_entry(self, c, uid: int, chat_id: int, first: str, data: str):
        if c.message.chat.type == "private":
            self._bot.answer_callback_query(c.id)
            return

        group = self._db.ensure_group(chat_id)

        # Invalidate any stale session and clean up old private message
        old_session = self._db.get_session(uid)
        if old_session:
            old_mid = old_session.get("active_form_mid")
            if old_mid:
                try:
                    self._bot.edit_message_text("Sessione precedente annullata.", uid, old_mid)
                except Exception:
                    pass
            self._db.delete_session(uid)

        try:
            if data == "start_booking":
                session = {
                    "state": STATE_SELECT_DAYS,
                    "original_chat_id": chat_id,
                    "days": [],
                    "index": 0,
                }
                prompt = f"Ciao {first}! 🦍\nSeleziona i giorni in cui vuoi allenarti questa settimana:"
                markup = self._kb.days([])
            else:
                bookings = self._booking.get_user_bookings(group, uid, first)
                if not bookings:
                    self._bot.answer_callback_query(
                        c.id, "Non hai prenotazioni da cancellare! ❌", show_alert=True
                    )
                    return
                session = {
                    "state": STATE_DELETING,
                    "original_chat_id": chat_id,
                    "items": [list(b) for b in bookings],
                    "selected": [],
                }
                prompt = "Seleziona le prenotazioni da cancellare:"
                markup = self._kb.delete(bookings, [])

            new_msg = self._bot.send_message(uid, prompt, reply_markup=markup, parse_mode="Markdown")
            session["active_form_mid"] = new_msg.message_id
            self._db.set_session(uid, session)
            self._db.save_lazy()
            self._bot.answer_callback_query(c.id, "Ti ho scritto in privato! 📩")
        except Exception:
            self._bot.answer_callback_query(
                c.id, "❌ Avvia il bot in privato prima di prenotare!", show_alert=True
            )

    # ------------------------------------------------------------------ #
    #  FSM: SELECT_DAYS                                                    #
    # ------------------------------------------------------------------ #

    def _handle_select_days(self, c, uid: int, chat_id: int, mid: int, data: str, session: dict):
        if data.startswith("selgiorno_"):
            d = data.split("_", 1)[1]
            if d in session["days"]:
                session["days"].remove(d)
            else:
                session["days"].append(d)
            self._bot.edit_message_reply_markup(chat_id, mid, reply_markup=self._kb.days(session["days"]))
            self._db.set_session(uid, session)
            self._db.save_lazy()
            self._bot.answer_callback_query(c.id)

        elif data == "conferma_giorni":
            if not session["days"]:
                self._bot.answer_callback_query(c.id, "Seleziona almeno un giorno!")
                return
            session["state"] = STATE_SELECT_HOURS
            session["index"] = 0
            day = session["days"][0]
            self._bot.edit_message_text(
                f"Per **{day}**, a che ora ci sarai?", chat_id, mid,
                reply_markup=self._kb.hours(day), parse_mode="Markdown"
            )
            self._db.set_session(uid, session)
            self._db.save_lazy()
            self._bot.answer_callback_query(c.id)

        else:
            self._bot.answer_callback_query(c.id)

    # ------------------------------------------------------------------ #
    #  FSM: SELECT_HOURS                                                   #
    # ------------------------------------------------------------------ #

    def _handle_select_hours(
        self, c, uid: int, chat_id: int, mid: int,
        data: str, session: dict, first: str, uname: str
    ):
        if not data.startswith("selora_"):
            self._bot.answer_callback_query(c.id)
            return

        _, d, h = data.split("_", 2)
        orig_chat_id = session["original_chat_id"]
        group = self._db.ensure_group(orig_chat_id)

        entry = {"id": uid, "first_name": first, "username": uname}
        if not any(self._booking.matches_user(e, uid, first) for e in group["db"][d][h]):
            group["db"][d][h].append(entry)

        session["index"] += 1
        if session["index"] < len(session["days"]):
            next_day = session["days"][session["index"]]
            self._bot.edit_message_text(
                f"Registrato per **{d}**!\nOra per **{next_day}**, a che ora?",
                chat_id, mid, reply_markup=self._kb.hours(next_day), parse_mode="Markdown"
            )
            self._db.set_session(uid, session)
            self._db.save_lazy()
        else:
            self._bot.edit_message_text("✅ Prenotazione completata!", chat_id, mid)
            self._update_group_summary(orig_chat_id)
            self._db.delete_session(uid)
            self._db.save()

        self._bot.answer_callback_query(c.id)

    # ------------------------------------------------------------------ #
    #  FSM: DELETING                                                       #
    # ------------------------------------------------------------------ #

    def _handle_deleting(
        self, c, uid: int, chat_id: int, mid: int,
        data: str, session: dict, first: str
    ):
        if data.startswith("delpick_"):
            idx = int(data.split("_", 1)[1])
            if idx in session["selected"]:
                session["selected"].remove(idx)
            else:
                session["selected"].append(idx)
            self._bot.edit_message_reply_markup(
                chat_id, mid,
                reply_markup=self._kb.delete(session["items"], session["selected"])
            )
            self._db.set_session(uid, session)
            self._db.save_lazy()
            self._bot.answer_callback_query(c.id)

        elif data == "delconfirm":
            if not session["selected"]:
                self._bot.answer_callback_query(c.id, "Nessuna selezione.")
                return
            orig_chat_id = session["original_chat_id"]
            group = self._db.ensure_group(orig_chat_id)
            for idx in session["selected"]:
                d, h = session["items"][idx]
                group["db"][d][h] = [
                    e for e in group["db"][d][h]
                    if not self._booking.matches_user(e, uid, first)
                ]
            self._bot.edit_message_text("✅ Cancellato!", chat_id, mid)
            self._update_group_summary(orig_chat_id)
            self._db.delete_session(uid)
            self._db.save()
            self._bot.answer_callback_query(c.id)

    # ------------------------------------------------------------------ #
    #  Utility                                                             #
    # ------------------------------------------------------------------ #

    def _update_group_summary(self, chat_id: int):
        group = self._db.ensure_group(chat_id)
        mid = group.get("main_message_id")
        if mid:
            try:
                self._bot.edit_message_text(
                    self._booking.generate_summary(group),
                    chat_id, mid,
                    reply_markup=self._kb.main_group(),
                    parse_mode="Markdown"
                )
            except Exception:
                pass
