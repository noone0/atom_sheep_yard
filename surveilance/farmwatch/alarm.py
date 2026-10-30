"""Alarm delivery over Telegram with per-key cooldowns and /ack acknowledgement."""
import logging
import threading
import time
from typing import Dict, Optional, Set

import cv2
import numpy as np
import requests

log = logging.getLogger(__name__)

LEVEL_ICON = {"info": "ℹ️", "warning": "⚠️", "urgent": "🚨"}


class Alarm:
    def __init__(self, bot_token: str, chat_id: str, dry_run: bool = False):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.dry_run = dry_run or not (bot_token and chat_id)
        self._last_sent: Dict[str, float] = {}
        self._acked: Set[str] = set()
        self._lock = threading.Lock()
        self._update_offset = 0
        if not self.dry_run:
            threading.Thread(target=self._poll_commands, daemon=True, name="telegram-poll").start()

    # ---- public API -------------------------------------------------------
    def send(self, text: str, image: Optional[np.ndarray] = None, key: Optional[str] = None,
             cooldown_s: float = 0, level: str = "info") -> bool:
        """Send a message (+photo). Returns True if actually sent.

        key + cooldown_s suppress repeats of the same alarm. An acknowledged key
        stays silent until clear() is called for it.
        """
        now = time.time()
        with self._lock:
            if key is not None:
                if key in self._acked:
                    return False
                last = self._last_sent.get(key)
                if last is not None and now - last < cooldown_s:
                    return False
                self._last_sent[key] = now
        text = "%s %s" % (LEVEL_ICON.get(level, ""), text)
        if self.dry_run:
            log.warning("[alarm dry-run] %s (image=%s)", text, image is not None)
            return True
        try:
            if image is not None:
                ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
                r = requests.post(self._url("sendPhoto"),
                                  data={"chat_id": self.chat_id, "caption": text[:1024]},
                                  files={"photo": ("snap.jpg", buf.tobytes(), "image/jpeg")},
                                  timeout=30)
            else:
                r = requests.post(self._url("sendMessage"),
                                  data={"chat_id": self.chat_id, "text": text[:4096]}, timeout=30)
            if r.status_code >= 400:
                log.error("telegram HTTP %s: %s", r.status_code, r.text[:300])
                return False
            return True
        except requests.RequestException as e:
            log.error("telegram send failed: %s", e)
            return False

    def clear(self, key: str) -> None:
        """Forget cooldown and acknowledgement for a key (e.g. stage changed)."""
        with self._lock:
            self._last_sent.pop(key, None)
            self._acked.discard(key)

    def is_acked(self, key: str) -> bool:
        with self._lock:
            return key in self._acked

    # ---- Telegram plumbing --------------------------------------------------
    def _url(self, method: str) -> str:
        return "https://api.telegram.org/bot%s/%s" % (self.bot_token, method)

    def _poll_commands(self) -> None:
        """Long-poll for '/ack' (acknowledge all) or '/ack <key>' messages."""
        while True:
            try:
                r = requests.get(self._url("getUpdates"),
                                 params={"offset": self._update_offset, "timeout": 50}, timeout=60)
                for upd in r.json().get("result", []):
                    self._update_offset = upd["update_id"] + 1
                    msg = upd.get("message") or {}
                    text = (msg.get("text") or "").strip()
                    if str(msg.get("chat", {}).get("id")) != str(self.chat_id):
                        continue
                    if text.startswith("/ack"):
                        parts = text.split(maxsplit=1)
                        with self._lock:
                            if len(parts) == 1:
                                self._acked.update(self._last_sent.keys())
                                what = "all active alarms"
                            else:
                                self._acked.add(parts[1].strip())
                                what = parts[1].strip()
                        self.send("Acknowledged: %s" % what)
                    elif text.startswith("/status"):
                        with self._lock:
                            active = [k for k in self._last_sent if k not in self._acked]
                        self.send("Active alarms: %s" % (", ".join(active) or "none"))
            except Exception as e:  # keep polling no matter what
                log.debug("telegram poll error: %s", e)
                time.sleep(5)
