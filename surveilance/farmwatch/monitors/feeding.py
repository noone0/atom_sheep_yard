"""Phase 2: feeding and activity.

- trough zones: sheep count per trough per minute, visit durations
- feed level: one trough image per `feed_check_minutes` to the vision model
- low-activity alarm: no trough visits for `inactive_hours` during the day
- whole-pen movement: average displacement per minute as an activity index
"""
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from .. import vision as V
from ..detector import Track
from ..geometry import dist, point_in_polygon
from .base import Monitor

FEED_LEVEL = {"empty": 0.0, "low": 0.25, "half": 0.5, "full": 1.0}
FEED_QUESTION = V.choice(
    "Look at the feed trough / hay rack in `trough`. How much feed (hay, silage, grain) is "
    "available to the sheep right now?",
    {
        "empty": "No feed visible, the trough or rack is bare.",
        "low": "Only scraps or a thin layer of feed left.",
        "half": "About half of the trough or rack is filled.",
        "full": "Plenty of feed, the trough or rack is mostly or completely full.",
    },
)
WATER_QUESTION = V.noul("In `trough`, is there a water container visible that is empty, frozen, "
                        "or very dirty?")


@dataclass
class TroughState:
    name: str
    polygon: List[Tuple[float, float]]
    crop: Optional[List[int]]  # [x1,y1,x2,y2] for the feed-level image, default = polygon bbox
    in_zone: Dict[int, float] = field(default_factory=dict)  # track -> entered ts
    last_visit: float = 0.0
    last_level_check: float = 0.0
    level: Optional[str] = None

    def bbox(self) -> List[int]:
        if self.crop:
            return self.crop
        xs = [p[0] for p in self.polygon]
        ys = [p[1] for p in self.polygon]
        return [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]


class FeedingMonitor(Monitor):
    name = "feeding"
    classes = ("sheep",)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.troughs = [TroughState(t["name"], [tuple(p) for p in t["polygon"]], t.get("crop"))
                        for t in self.cfg.get("troughs", [])]
        self.feed_check = float(self.cfg.get("feed_check_minutes", 20)) * 60
        self.min_visit = float(self.cfg.get("min_visit_seconds", 10))
        self.inactive_hours = float(self.cfg.get("inactive_hours", 4))
        self.day_start, self.day_end = _hours(self.cfg.get("daytime", "06:00-20:00"))
        self.low_feed_cooldown = float(self.cfg.get("low_feed_cooldown_minutes", 120)) * 60
        self.last_pos: Dict[int, Tuple[float, float]] = {}
        self.moves: List[float] = []
        self.last_minute = 0.0
        self.started = 0.0

    def on_frame(self, ts: float, frame: np.ndarray, tracks: List[Track]) -> None:
        if not self.started:
            self.started = ts
            for tr in self.troughs:
                tr.last_visit = ts
        sheep = [t for t in tracks if t.cls == "sheep"]
        present = {t.track_id for t in sheep}

        # movement index
        for t in sheep:
            p = self.last_pos.get(t.track_id)
            if p is not None:
                self.moves.append(dist(p, t.foot) / max(t.w, 1.0))  # body-lengths moved
            self.last_pos[t.track_id] = t.foot
        for tid in [tid for tid in self.last_pos if tid not in present]:
            del self.last_pos[tid]

        # trough zones
        for tr in self.troughs:
            inside = {t.track_id for t in sheep if point_in_polygon(t.foot, tr.polygon)}
            for tid in inside:
                tr.in_zone.setdefault(tid, ts)
            for tid in [tid for tid in tr.in_zone if tid not in inside]:
                entered = tr.in_zone.pop(tid)
                dur = ts - entered
                if dur >= self.min_visit:
                    tr.last_visit = ts
                    self.storage.observe(self.camera, self.name, "visit_seconds:" + tr.name, dur, ts)
            if inside:
                tr.last_visit = ts
            if ts - tr.last_level_check >= self.feed_check:
                tr.last_level_check = ts
                self._check_feed(tr, frame, ts)

        # per-minute observations and inactivity alarm
        if ts - self.last_minute >= 60:
            self.last_minute = ts
            self.storage.observe(self.camera, self.name, "sheep_in_view", len(sheep), ts)
            if self.moves:
                self.storage.observe(self.camera, self.name, "activity_index",
                                     sum(self.moves) / len(self.moves), ts)
            self.moves = []
            for tr in self.troughs:
                self.storage.observe(self.camera, self.name, "at_trough:" + tr.name, len(tr.in_zone), ts)
                if self._is_daytime(ts) and ts - tr.last_visit >= self.inactive_hours * 3600:
                    if self.alarm.send("No sheep has visited trough '%s' (camera %s) for %.0f hours. "
                                       "Check feed and animals." % (tr.name, self.camera, self.inactive_hours),
                                       frame, self.key(tr.name, "inactive"), self.inactive_hours * 3600, "warning"):
                        self.event("warning", "no_visits", "trough %s: no visits" % tr.name, frame, None, None, ts)

    def _check_feed(self, tr: TroughState, frame: np.ndarray, ts: float) -> None:
        x1, y1, x2, y2 = tr.bbox()
        crop = frame[max(0, y1):y2, max(0, x1):x2]
        if crop.size == 0:
            crop = frame
        res = self.vision.ask({"trough": crop}, {"level": FEED_QUESTION, "water_problem": WATER_QUESTION},
                              state={"camera": self.camera, "trough": tr.name})
        if res.error:
            return
        level = str(res.get("level", "")).lower()
        if level in FEED_LEVEL:
            tr.level = level
            self.storage.observe(self.camera, self.name, "feed_level:" + tr.name, FEED_LEVEL[level], ts)
            if level in ("empty", "low"):
                if self.alarm.send("Feed %s at trough '%s' (camera %s)." % (level.upper(), tr.name, self.camera),
                                   crop, self.key(tr.name, "feed"), self.low_feed_cooldown, "warning"):
                    self.event("warning", "feed_low", "trough %s: %s" % (tr.name, level), crop, None,
                               {"answers": res.answers}, ts)
            else:
                self.alarm.clear(self.key(tr.name, "feed"))
        if res.yes("water_problem"):
            if self.alarm.send("Water problem at trough '%s' (camera %s): empty, frozen or dirty." %
                               (tr.name, self.camera), crop, self.key(tr.name, "water"),
                               self.low_feed_cooldown, "warning"):
                self.event("warning", "water_problem", "trough %s: water" % tr.name, crop, None, None, ts)

    def _is_daytime(self, ts: float) -> bool:
        h = time.localtime(ts).tm_hour + time.localtime(ts).tm_min / 60
        return self.day_start <= h < self.day_end


def _hours(spec: str) -> Tuple[float, float]:
    a, b = spec.split("-")
    def f(s):
        hh, mm = s.strip().split(":")
        return int(hh) + int(mm) / 60
    return f(a), f(b)
