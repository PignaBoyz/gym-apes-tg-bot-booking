from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import DAYS, HOURS


class Keyboards:
    """
    Single responsibility: build all InlineKeyboardMarkup objects for the bot UI.
    All methods are static — no state, no side effects.
    """

    @staticmethod
    def main_group() -> InlineKeyboardMarkup:
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("📅 Prenota il tuo allenamento", callback_data="start_booking"))
        markup.row(InlineKeyboardButton("🗑️ Gestisci mie prenotazioni", callback_data="start_delete"))
        return markup

    @staticmethod
    def days(selected: list) -> InlineKeyboardMarkup:
        markup = InlineKeyboardMarkup()
        row = []
        for d in DAYS:
            label = f"✅ {d}" if d in selected else d
            row.append(InlineKeyboardButton(label, callback_data=f"selgiorno_{d}"))
            if len(row) == 2:
                markup.row(*row)
                row = []
        if row:
            markup.row(row[0])
        if selected:
            markup.row(InlineKeyboardButton("➡️ CONFERMA GIORNI", callback_data="conferma_giorni"))
        markup.row(InlineKeyboardButton("❌ Annulla", callback_data="exit_private"))
        return markup

    @staticmethod
    def hours(day: str) -> InlineKeyboardMarkup:
        markup = InlineKeyboardMarkup()
        row = []
        for h in HOURS:
            row.append(InlineKeyboardButton(h, callback_data=f"selora_{day}_{h}"))
            if len(row) == 2:
                markup.row(*row)
                row = []
        if row:
            markup.row(row[0])
        markup.row(InlineKeyboardButton("❌ Annulla", callback_data="exit_private"))
        return markup

    @staticmethod
    def delete(bookings: list, selected: list) -> InlineKeyboardMarkup:
        markup = InlineKeyboardMarkup()
        for i, (d, h) in enumerate(bookings):
            label = f"{'✅ ' if i in selected else ''}{d} — {h}"
            markup.row(InlineKeyboardButton(label, callback_data=f"delpick_{i}"))
        if bookings:
            markup.row(
                InlineKeyboardButton("✅ Conferma eliminazione", callback_data="delconfirm"),
                InlineKeyboardButton("❌ Annulla", callback_data="exit_private")
            )
        else:
            markup.row(InlineKeyboardButton("↩️ Chiudi", callback_data="exit_private"))
        return markup
