import json
import time
import threading
import requests

from config import GIST_TOKEN, GIST_ID, GIST_FILENAME, HOURS, DAYS

SAVE_INTERVAL = 10  # seconds between lazy-saves


class GistDatabase:
    """
    Single responsibility: persist and retrieve the application state via GitHub Gist.

    Top-level DB structure:
        {
          "groups": {
              "<group_chat_id>": {
                  "db": { "<day>": { "<hour>": [...entries] } },
                  "main_message_id": int | null
              }
          },
          "sessions": {
              "<uid>": {
                  "state": "SELECT_DAYS" | "SELECT_HOURS" | "DELETING",
                  "original_chat_id": int,
                  "active_form_mid": int,
                  "days": [...],
                  "index": int,
                  "items": [...],    # DELETING only
                  "selected": [...]  # DELETING only
              }
          }
        }

    Sessions live at the top-level (not inside a group) so they are accessible
    from both group callbacks and private-chat callbacks without a cross-lookup.
    """

    def __init__(self):
        self._data: dict = {"groups": {}, "sessions": {}}
        self._last_save: float = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    #  Public properties                                                   #
    # ------------------------------------------------------------------ #

    @property
    def groups(self) -> dict:
        return self._data.setdefault("groups", {})

    @property
    def sessions(self) -> dict:
        return self._data.setdefault("sessions", {})

    # ------------------------------------------------------------------ #
    #  Gist I/O                                                            #
    # ------------------------------------------------------------------ #

    def load(self):
        try:
            resp = requests.get(
                f"https://api.github.com/gists/{GIST_ID}",
                headers=self._headers(), timeout=10
            )
            resp.raise_for_status()
            content = resp.json()["files"][GIST_FILENAME]["content"]
            data = json.loads(content)
            if isinstance(data, dict) and "groups" in data:
                self._data = data
                self._data.setdefault("sessions", {})  # migrate older DBs
                print("✔ Loaded multi-group DB")
            else:
                self._data = {"groups": {}, "sessions": {}}
        except Exception as e:
            print(f"[WARN] Cannot load Gist: {e}")
            self._data = {"groups": {}, "sessions": {}}

    def save(self):
        try:
            payload = {
                "files": {
                    GIST_FILENAME: {
                        "content": json.dumps(self._data, ensure_ascii=False, indent=2)
                    }
                }
            }
            requests.patch(
                f"https://api.github.com/gists/{GIST_ID}",
                headers=self._headers(), json=payload, timeout=10
            ).raise_for_status()
            print("✔ Saved multi-group DB")
        except Exception as e:
            print(f"[WARN] Cannot save Gist: {e}")

    def save_lazy(self):
        """Save only if enough time has passed since the last save (debounce)."""
        now = time.time()
        if now - self._last_save > SAVE_INTERVAL:
            with self._lock:
                self.save()
                self._last_save = now

    # ------------------------------------------------------------------ #
    #  Group helpers                                                       #
    # ------------------------------------------------------------------ #

    def ensure_group(self, chat_id: int) -> dict:
        cid = str(chat_id)
        if cid not in self._data["groups"]:
            self._data["groups"][cid] = {
                "db": {g: {h: [] for h in HOURS} for g in DAYS},
                "main_message_id": None,
            }
        return self._data["groups"][cid]

    # ------------------------------------------------------------------ #
    #  Session helpers                                                     #
    # ------------------------------------------------------------------ #

    def get_session(self, uid: int):
        return self._data["sessions"].get(str(uid))

    def set_session(self, uid: int, session: dict):
        self._data["sessions"][str(uid)] = session

    def delete_session(self, uid: int):
        self._data["sessions"].pop(str(uid), None)

    def clear_sessions_for_group(self, chat_id: int):
        """Remove all active sessions belonging to a given group (used on /allenamento reset)."""
        to_delete = [
            uid_str for uid_str, s in self._data["sessions"].items()
            if str(s.get("original_chat_id")) == str(chat_id)
        ]
        for uid_str in to_delete:
            del self._data["sessions"][uid_str]

    # ------------------------------------------------------------------ #
    #  Private                                                             #
    # ------------------------------------------------------------------ #

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {GIST_TOKEN}",
            "Accept": "application/vnd.github+json"
        }
