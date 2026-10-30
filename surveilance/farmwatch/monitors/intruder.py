"""Phase 3: unusual people, vehicles, dogs and actions.

Triggers (after `min_frames` consecutive detections):
  - person outside `allowed_hours`, or inside a restricted zone at any time
  - vehicle outside allowed hours
  - dog close to sheep at any time
On trigger the vision model describes what is happening, then an alarm with photo is sent.
"""
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from .. import vision as V
from ..detector import Track
from ..geometry import dist, point_in_polygon
from .base import Monitor

VEHICLES = ("car", "truck", "bus", "motorcycle")

PERSON_ACTIVITY = V.choice(
    "Look at the person in `subject` (close-up) and `scene` (full view) on a sheep farm. "
    "What are they doing?",
    {
        "normal_farm_work": "Feeding, carrying hay or buckets, checking animals, walking normally, "
                            "cleaning, or routine work.",
        "carrying_animal": "Carrying, dragging or lifting a sheep or lamb.",
        "handling_gate_or_fence": "Opening a gate, climbing a fence or wall, cutting wire, or forcing a door.",
        "loading_vehicle": "Loading animals or equipment into a vehicle or trailer.",
        "unclear": "Cannot tell what the person is doing.",
    },
)
PERSON_THREAT = V.noul("In `subject` and `scene`, does the person appear to be stealing, breaking in, "
                       "damaging property, or harming animals?")
DOG_ATTACK = V.noul("In `scene`, is a dog chasing, biting or attacking sheep, or are sheep running "
                    "away from a dog?")
VEHICLE_Q = V.choice(
    "Describe the vehicle in `subject`.",
    {"car": "A car or SUV.", "pickup_or_truck": "A pickup, truck or lorry.",
     "trailer_or_livestock": "A vehicle with a trailer or a livestock transporter.",
     "tractor_or_farm": "A tractor or other farm machine.", "other": "Something else."},
)


@dataclass
class Seen:
    frames: int = 0
    first_ts: float = 0.0
    last_ts: float = 0.0
    confirmed: bool = False


class IntruderMonitor(Monitor):
    name = "intruder"
    classes = ("person", "dog", "car", "truck", "bus", "motorcycle", "sheep")

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.allowed = [_hours(s) for s in self.cfg.get("allowed_hours", ["06:00-20:00"])]
        self.restricted = [[tuple(p) for p in z["polygon"]] for z in self.cfg.get("restricted_zones", [])]
        self.restricted_names = [z.get("name", "zone %d" % i) for i, z in enumerate(self.cfg.get("restricted_zones", []))]
        self.min_frames = int(self.cfg.get("min_frames", 3))
        self.cooldown = float(self.cfg.get("cooldown_minutes", 10)) * 60
        self.dog_distance = float(self.cfg.get("dog_distance_bodies", 3.0))
        self.alarm_vehicles = bool(self.cfg.get("alarm_vehicles", True))
        self.seen: Dict[int, Seen] = {}

    def on_frame(self, ts: float, frame: np.ndarray, tracks: List[Track]) -> None:
        sheep = [t for t in tracks if t.cls == "sheep"]
        present = set()
        for t in tracks:
            if t.cls == "sheep":
                continue
            present.add(t.track_id)
            s = self.seen.setdefault(t.track_id, Seen(first_ts=ts))
            s.frames += 1
            s.last_ts = ts
            if s.confirmed or s.frames < self.min_frames:
                continue
            reason = self._reason(t, sheep, ts)
            if reason:
                s.confirmed = True
                self._handle(t, reason, frame, ts)
        for tid in [tid for tid, s in self.seen.items() if ts - s.last_ts > 30]:
            del self.seen[tid]

    def _reason(self, t: Track, sheep: List[Track], ts: float) -> Optional[str]:
        if t.cls == "person":
            for name, poly in zip(self.restricted_names, self.restricted):
                if point_in_polygon(t.foot, poly):
                    return "person in restricted zone '%s'" % name
            if not self._allowed_now(ts):
                return "person outside working hours"
            return None
        if t.cls == "dog":
            if sheep:
                near = min(dist(t.foot, s.foot) / max(s.w, 1.0) for s in sheep)
                if near <= self.dog_distance:
                    return "dog close to sheep"
            return "dog on the farm" if not self._allowed_now(ts) else None
        if t.cls in VEHICLES and self.alarm_vehicles and not self._allowed_now(ts):
            return "vehicle outside working hours"
        return None

    def _handle(self, t: Track, reason: str, frame: np.ndarray, ts: float) -> None:
        self.log.warning("trigger: %s (track %d, %s)", reason, t.track_id, t.cls)
        shown = frame.copy()
        import cv2
        cv2.rectangle(shown, (int(t.x1), int(t.y1)), (int(t.x2), int(t.y2)), (0, 0, 255), 3)
        images = {"subject": t.crop(frame), "scene": frame}
        level, text = "warning", reason
        answers = {}
        if t.cls == "person":
            res = self.vision.ask(images, {"activity": PERSON_ACTIVITY, "threat": PERSON_THREAT},
                                  state={"camera": self.camera, "time": time.strftime("%H:%M", time.localtime(ts))},
                                  urgent=True)
            if not res.error:
                answers = res.answers
                act = str(res.get("activity", "unclear"))
                if res.yes("threat") or act in ("carrying_animal", "handling_gate_or_fence", "loading_vehicle"):
                    level = "urgent"
                text = "%s: %s" % (reason, act.replace("_", " "))
        elif t.cls == "dog":
            res = self.vision.ask(images, {"attack": DOG_ATTACK}, state={"camera": self.camera}, urgent=True)
            if not res.error:
                answers = res.answers
                if res.yes("attack"):
                    level, text = "urgent", "DOG ATTACKING SHEEP"
        else:
            res = self.vision.ask(images, {"vehicle": VEHICLE_Q}, state={"camera": self.camera})
            if not res.error:
                answers = res.answers
                v = str(res.get("vehicle", "other"))
                text = "%s: %s" % (reason, v.replace("_", " "))
                if v == "trailer_or_livestock":
                    level = "urgent"
        key = self.key(t.cls, reason)
        if self.alarm.send("%s – camera %s" % (text, self.camera), shown, key, self.cooldown, level):
            self.event(level, "intruder_" + t.cls, text, shown, t.track_id, {"answers": answers}, ts)

    def _allowed_now(self, ts: float) -> bool:
        lt = time.localtime(ts)
        h = lt.tm_hour + lt.tm_min / 60
        return any(a <= h < b for a, b in self.allowed)


def _hours(spec: str) -> Tuple[float, float]:
    a, b = spec.split("-")
    def f(s):
        hh, mm = s.strip().split(":")
        return int(hh) + int(mm) / 60
    return f(a), f(b)
