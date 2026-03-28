from datetime import datetime, timedelta

from config import DAYS, HOURS, MONTHS


class BookingService:
    """
    Single responsibility: pure domain logic for gym bookings.
    No Telegram API calls, no direct DB writes — only reads group data
    and returns results to the caller.
    """

    def __init__(self, db):
        self._db = db

    # ------------------------------------------------------------------ #
    #  Admin check                                                         #
    # ------------------------------------------------------------------ #

    def is_owner(self, bot, chat_id: int, user_id: int) -> bool:
        try:
            admins = bot.get_chat_administrators(chat_id)
            return any(a.user.id == user_id and a.status == "creator" for a in admins)
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    #  Group state                                                         #
    # ------------------------------------------------------------------ #

    def reset_group(self, group: dict):
        """Wipe all bookings for a group (called by the admin on /allenamento)."""
        group["db"] = {g: {h: [] for h in HOURS} for g in DAYS}
        group["main_message_id"] = None

    # ------------------------------------------------------------------ #
    #  Booking queries                                                     #
    # ------------------------------------------------------------------ #

    def matches_user(self, entry, uid: int, name: str) -> bool:
        if isinstance(entry, dict):
            return entry.get("id") == uid
        return str(entry) == name

    def display_entry(self, entry) -> str:
        if isinstance(entry, dict):
            nm = entry.get("first_name") or "?"
            un = entry.get("username")
            return f"{nm} (@{un})" if un else nm
        return str(entry)

    def get_user_bookings(self, group: dict, uid: int, first_name: str) -> list:
        res = []
        for d in DAYS:
            for h in HOURS:
                if any(self.matches_user(e, uid, first_name) for e in group["db"][d][h]):
                    res.append((d, h))
        return res

    # ------------------------------------------------------------------ #
    #  Summary                                                             #
    # ------------------------------------------------------------------ #

    def generate_summary(self, group: dict) -> str:
        txt = "🦍 **RIEPILOGO ALLENAMENTI SETTIMANALI** 🦍\n\n"
        wd = self._get_week_dates()
        empty = True

        for d in DAYS:
            lines = []
            for h in HOURS:
                ppl = group["db"][d][h]
                if ppl:
                    names = ", ".join(self.display_entry(p) for p in ppl)
                    lines.append(f" {h}: {names}")
            if lines:
                dayn, m = wd[d]
                txt += f"**{d} {dayn} {m}**\n" + "\n".join(lines) + "\n\n"
                empty = False

        if empty:
            txt += "_Nessuna prenotazione._"
        return txt

    # ------------------------------------------------------------------ #
    #  Private                                                             #
    # ------------------------------------------------------------------ #

    def _get_week_dates(self) -> dict:
        today = datetime.now()
        monday = today - timedelta(days=today.weekday())
        out = {}
        for i, g in enumerate(DAYS):
            d = monday + timedelta(days=i)
            out[g] = (d.day, MONTHS[d.month - 1])
        return out
