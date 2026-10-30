"""Vision-language confirmation via the typesafe.ai System One API (Jev).

Docs: https://docs.typesafe.ai/images
- POST https://api.typesafe.ai/v1/systemone, Bearer auth
- header TypeSafe-Danger-Zone-Images: true for any request with images
- images: PNG/JPEG, 280..1568 px per side, referenced from `state` via `assets`
- questions: choice (criteria = option -> description), noul (yes/no)

The feature is marked "Dreamer-ready" (not production); the client is kept
behind a small interface so another vision model can be swapped in.
"""
import base64
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import cv2
import numpy as np
import requests

log = logging.getLogger(__name__)

API_URL = "https://api.typesafe.ai/v1/systemone"
MIN_SIDE, MAX_SIDE = 280, 1568


# ---- question builders ----------------------------------------------------

def choice(instructions: str, options: Dict[str, str]) -> Dict[str, Any]:
    return {"type": "choice", "instructions": instructions, "criteria": dict(options)}


def noul(instructions: str) -> Dict[str, Any]:
    return {"type": "noul", "instructions": instructions}


# ---- image preparation ----------------------------------------------------

def prepare_image(img: np.ndarray) -> np.ndarray:
    """Resize/pad so both sides are within [MIN_SIDE, MAX_SIDE]."""
    h, w = img.shape[:2]
    scale = 1.0
    if max(h, w) > MAX_SIDE:
        scale = MAX_SIDE / max(h, w)
    if min(h, w) * scale < MIN_SIDE:
        scale = MIN_SIDE / min(h, w)
    if scale != 1.0:
        img = cv2.resize(img, (int(round(w * scale)), int(round(h * scale))),
                         interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
    h, w = img.shape[:2]
    if max(h, w) > MAX_SIDE:  # extreme aspect ratio: centre-crop the long side
        if w > MAX_SIDE:
            off = (w - MAX_SIDE) // 2
            img = img[:, off:off + MAX_SIDE]
        if h > MAX_SIDE:
            off = (h - MAX_SIDE) // 2
            img = img[off:off + MAX_SIDE, :]
    return img


def encode_jpeg_b64(img: np.ndarray, quality: int = 85) -> str:
    ok, buf = cv2.imencode(".jpg", prepare_image(img), [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("jpeg encode failed")
    return base64.b64encode(buf.tobytes()).decode("ascii")


# ---- result -----------------------------------------------------------------

@dataclass
class VisionResult:
    answers: Dict[str, Any] = field(default_factory=dict)
    input_tokens: int = 0
    raw: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def get(self, key: str, default: Any = None) -> Any:
        v = self.answers.get(key, default)
        # be tolerant to {"answer": ...} / {"value": ...} shaped answers
        if isinstance(v, dict):
            for k in ("answer", "value", "choice", "option", "result"):
                if k in v:
                    return v[k]
        return v

    def yes(self, key: str) -> bool:
        v = self.get(key)
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "yes", "y", "1")


# ---- client -----------------------------------------------------------------

class VisionClient:
    def __init__(self, api_key: str, model: str = "jev-latest", timeout: float = 60,
                 daily_budget: int = 2000, dry_run: bool = False):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.daily_budget = daily_budget
        self.dry_run = dry_run
        self._lock = threading.Lock()
        self._day = time.strftime("%Y-%m-%d")
        self._calls = 0
        self._tokens = 0

    # budget -------------------------------------------------------------
    def _roll_day(self) -> None:
        d = time.strftime("%Y-%m-%d")
        if d != self._day:
            log.info("vision usage %s: %d calls, %d input tokens", self._day, self._calls, self._tokens)
            self._day, self._calls, self._tokens = d, 0, 0

    def usage(self) -> Dict[str, int]:
        with self._lock:
            self._roll_day()
            return {"calls": self._calls, "input_tokens": self._tokens}

    # main call ----------------------------------------------------------
    def ask(self, images: Dict[str, np.ndarray], questions: Dict[str, Dict[str, Any]],
            state: Optional[Dict[str, Any]] = None, urgent: bool = False) -> VisionResult:
        """Ask structured questions about one or more images.

        images:    state key -> BGR frame. Refer to them in instructions with `key`.
        questions: question id -> question dict from choice()/noul().
        state:     extra plain values to put in `state` (e.g. camera name, time).
        urgent:    bypasses the daily budget (used for lambing confirmation).
        """
        with self._lock:
            self._roll_day()
            if not urgent and self._calls >= self.daily_budget:
                return VisionResult(error="daily vision budget exhausted")
            self._calls += 1

        if self.dry_run or not self.api_key:
            log.info("[vision dry-run] images=%s questions=%s", list(images), list(questions))
            return VisionResult(error="dry-run")

        body_state: Dict[str, Any] = dict(state or {})
        assets: Dict[str, Any] = {}
        for key, img in images.items():
            ref = "%s-%s" % (uuid.uuid4().hex[:8], key)
            body_state[key] = ref
            assets[ref] = {"type": "image", "format": "jpg", "data_base64": encode_jpeg_b64(img)}

        payload = {"model": self.model, "state": body_state, "assets": assets, "questions": questions}
        headers = {
            "Authorization": "Bearer " + self.api_key,
            "TypeSafe-Danger-Zone-Images": "true",
        }
        t0 = time.time()
        try:
            resp = requests.post(API_URL, json=payload, headers=headers, timeout=self.timeout)
        except requests.RequestException as e:
            log.error("vision request failed: %s", e)
            return VisionResult(error=str(e))
        if resp.status_code >= 400:
            log.error("vision HTTP %s: %s", resp.status_code, resp.text[:500])
            return VisionResult(error="http %d" % resp.status_code)
        data = resp.json()
        tokens = int((data.get("usage") or {}).get("input_tokens") or 0)
        with self._lock:
            self._tokens += tokens
        log.info("vision ok in %.1fs, %d input tokens, answers=%s",
                 time.time() - t0, tokens, data.get("answers"))
        return VisionResult(answers=data.get("answers") or {}, input_tokens=tokens, raw=data)
