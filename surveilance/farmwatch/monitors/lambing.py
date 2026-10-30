"""Phase 1: detect the start of lambing and alarm.

Pipeline per ewe track:
  posture (standing / lying / lying on side) from box geometry
  -> restlessness (lie/stand transitions), isolation, side-lying duration
  -> suspect score
  -> suspect ewes are confirmed by the vision model every `interval_seconds`
  -> consecutive positive answers raise pre-alarm / urgent alarm / dystocia alarm
A pen-wide safety-net check runs every `safety_net_minutes` regardless.
"""
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

from .. import vision as V
from ..detector import Track
from ..geometry import dist
from .base import Monitor

STANDING, LYING, SIDE = "standing", "lying", "side"
STAGES = ("none", "early_labour", "active_labour", "lamb_delivered")

STAGE_QUESTION = V.choice(
    "Look at the sheep in `ewe` (close-up) and `pen` (full view). Which stage of lambing "
    "(giving birth) does this ewe show? Judge only from what is visible.",
    {
        "none": "Normal behaviour: standing, eating, walking, or resting calmly with head up.",
        "early_labour": "Restless or uncomfortable: pawing the bedding, standing apart from the "
                        "others, turning the head to look at her flank, repeatedly lying down and "
                        "getting up, but no straining and nothing visible at the rear.",
        "active_labour": "Lying flat on her side with neck stretched out and straining or pushing, "
                         "or a water bag, fluid, hooves or a lamb's nose visible at her rear.",
        "lamb_delivered": "A newborn lamb (small, wet, often still lying down) is on the ground "
                          "next to the ewe, or the ewe is licking a newborn lamb.",
    },
)
LAMB_QUESTION = V.noul("Is a newborn lamb (small, wet, newly born) visible in `pen` or `ewe`?")
SIGNS_QUESTION = V.noul("In `ewe`, is a water bag, birth fluid, lamb hooves or a lamb's nose "
                        "visible at the rear end of the sheep?")

PEN_QUESTION = V.choice(
    "Look at the whole pen in `pen`. Is any sheep giving birth or about to?",
    {
        "none": "No sheep shows signs of labour.",
        "early_labour": "A sheep looks restless, is pawing, or stands apart looking at her flank.",
        "active_labour": "A sheep is lying flat on her side straining, or something is visible at "
                         "her rear (water bag, fluid, hooves, nose).",
        "lamb_delivered": "A newborn lamb is visible on the ground or being licked by a ewe.",
    },
)


@dataclass
class EweState:
    track_id: int
    hist: Deque[Tuple[float, float, float, float, float]] = field(default_factory=lambda: deque(maxlen=4000))
    posture: str = STANDING
    posture_candidate: str = STANDING
    candidate_count: int = 0
    transitions: Deque[float] = field(default_factory=deque)
    side_since: Optional[float] = None
    isolated_since: Optional[float] = None
    last_seen: float = 0.0
    score: float = 0.0
    last_confirm: float = 0.0
    stage_hist: Deque[str] = field(default_factory=lambda: deque(maxlen=6))
    stage: str = "none"
    active_since: Optional[float] = None
    last_box: Optional[Track] = None

    def standing_height(self, now: float, window: float) -> float:
        hs = [h for (t, h, w, cx, cy) in self.hist if now - t <= window]
        if len(hs) < 5:
            return max(hs) if hs else 0.0
        hs.sort()
        return hs[int(len(hs) * 0.9)]  # 90th percentile = typical standing height


class LambingMonitor(Monitor):
    name = "lambing"
    classes = ("sheep",)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        b = self.cfg.get("behavior", {})
        self.window = float(b.get("window_minutes", 15)) * 60
        self.lying_ratio = float(b.get("lying_height_ratio", 0.72))
        self.side_aspect = float(b.get("side_aspect_ratio", 2.1))
        self.min_transitions = int(b.get("min_transitions", 4))
        self.isolation_factor = float(b.get("isolation_factor", 2.0))
        self.isolation_minutes = float(b.get("isolation_minutes", 5)) * 60
        self.side_minutes = float(b.get("side_lying_minutes", 2.0)) * 60
        self.suspect_score = float(b.get("suspect_score", 2.0))
        self.stable_samples = int(b.get("posture_stable_samples", 3))
        c = self.cfg.get("confirm", {})
        self.interval = float(c.get("interval_seconds", 45))
        self.safety_net = float(c.get("safety_net_minutes", 10)) * 60
        self.consecutive = int(c.get("consecutive_positive", 2))
        a = self.cfg.get("alarm", {})
        self.cooldown = float(a.get("cooldown_minutes", 30)) * 60
        self.repeat = float(a.get("repeat_minutes", 5)) * 60
        self.pre_alarm = bool(a.get("pre_alarm_on_early_labour", True))
        self.dystocia_minutes = float(a.get("dystocia_minutes", 60)) * 60
        self.ewes: Dict[int, EweState] = {}
        self.last_safety_net = 0.0
        self.last_obs = 0.0

    # ------------------------------------------------------------------ frame
    def on_frame(self, ts: float, frame: np.ndarray, tracks: List[Track]) -> None:
        sheep = [t for t in tracks if t.cls == "sheep"]
        self._update_geometry(ts, sheep)
        self._update_isolation(ts, sheep)
        self._expire(ts)

        for t in sheep:
            e = self.ewes[t.track_id]
            e.score = self._score(e, ts)
            if e.score >= self.suspect_score and ts - e.last_confirm >= self.interval:
                self._confirm(e, t, frame, ts)
            self._check_dystocia(e, frame, ts)

        if ts - self.last_safety_net >= self.safety_net:
            self.last_safety_net = ts
            self._safety_net(frame, ts)

        if ts - self.last_obs >= 60:
            self.last_obs = ts
            self.storage.observe(self.camera, self.name, "sheep_count", len(sheep), ts)
            lying = sum(1 for t in sheep if self.ewes[t.track_id].posture != STANDING)
            self.storage.observe(self.camera, self.name, "sheep_lying", lying, ts)
            top = max((e.score for e in self.ewes.values()), default=0.0)
            self.storage.observe(self.camera, self.name, "max_suspect_score", top, ts)

    # -------------------------------------------------------------- behaviour
    def _update_geometry(self, ts: float, sheep: List[Track]) -> None:
        for t in sheep:
            e = self.ewes.get(t.track_id)
            if e is None:
                e = self.ewes[t.track_id] = EweState(t.track_id)
            e.hist.append((ts, t.h, t.w, t.cx, t.cy))
            e.last_seen = ts
            e.last_box = t
            stand_h = e.standing_height(ts, self.window)
            aspect = t.w / max(t.h, 1.0)
            if stand_h > 0 and t.h < self.lying_ratio * stand_h:
                cand = SIDE if aspect >= self.side_aspect else LYING
            elif aspect >= self.side_aspect:
                cand = SIDE
            else:
                cand = STANDING
            # debounce: posture must be seen `stable_samples` times in a row
            if cand == e.posture_candidate:
                e.candidate_count += 1
            else:
                e.posture_candidate, e.candidate_count = cand, 1
            if e.candidate_count >= self.stable_samples and cand != e.posture:
                was_up = e.posture == STANDING
                now_up = cand == STANDING
                if was_up != now_up:
                    e.transitions.append(ts)
                e.posture = cand
            if e.posture == SIDE:
                e.side_since = e.side_since or ts
            else:
                e.side_since = None
            while e.transitions and ts - e.transitions[0] > self.window:
                e.transitions.popleft()

    def _update_isolation(self, ts: float, sheep: List[Track]) -> None:
        if len(sheep) < 3:
            for t in sheep:
                self.ewes[t.track_id].isolated_since = None
            return
        pts = {t.track_id: t.foot for t in sheep}
        nn: Dict[int, float] = {}
        for tid, p in pts.items():
            nn[tid] = min(dist(p, q) for oid, q in pts.items() if oid != tid)
        med = statistics.median(nn.values()) or 1.0
        for tid, d in nn.items():
            e = self.ewes[tid]
            if d > self.isolation_factor * med:
                e.isolated_since = e.isolated_since or ts
            else:
                e.isolated_since = None

    def _score(self, e: EweState, ts: float) -> float:
        s = 0.0
        n = len(e.transitions)
        if n >= self.min_transitions:
            s += 1.5
        elif n >= max(2, self.min_transitions // 2):
            s += 0.5
        if e.isolated_since is not None and ts - e.isolated_since >= self.isolation_minutes:
            s += 1.0
        if e.side_since is not None and ts - e.side_since >= self.side_minutes:
            s += 2.0  # lying flat on the side for minutes is itself enough to ask the vision model
        if e.stage in ("early_labour", "active_labour"):
            s += 1.0  # once the model has seen labour signs, keep watching her
        return s

    def _expire(self, ts: float) -> None:
        for tid in [tid for tid, e in self.ewes.items() if ts - e.last_seen > 180]:
            del self.ewes[tid]

    # ----------------------------------------------------------- confirmation
    def _confirm(self, e: EweState, t: Track, frame: np.ndarray, ts: float) -> None:
        e.last_confirm = ts
        self.log.info("ewe %d suspect (score %.1f, transitions %d, posture %s) -> asking vision",
                      e.track_id, e.score, len(e.transitions), e.posture)
        res = self.vision.ask(
            {"ewe": t.crop(frame), "pen": frame},
            {"stage": STAGE_QUESTION, "lamb_visible": LAMB_QUESTION, "birth_signs": SIGNS_QUESTION},
            state={"camera": self.camera, "note": "sheep farm lambing pen camera"},
            urgent=True,
        )
        if res.error:
            return
        stage = str(res.get("stage", "none")).lower()
        if stage not in STAGES:
            stage = "none"
        if res.yes("lamb_visible"):
            stage = "lamb_delivered"
        elif res.yes("birth_signs") and stage in ("none", "early_labour"):
            stage = "active_labour"
        e.stage_hist.append(stage)
        self.event("info", "vision_check", "ewe %d: %s" % (e.track_id, stage), None, e.track_id,
                   {"answers": res.answers, "score": e.score}, ts)
        self._decide(e, frame, ts)

    def _decide(self, e: EweState, frame: np.ndarray, ts: float) -> None:
        hist = list(e.stage_hist)
        last = hist[-self.consecutive:]
        new_stage = e.stage
        if hist and hist[-1] == "lamb_delivered":
            new_stage = "lamb_delivered"
        elif len(last) >= self.consecutive and all(s == "active_labour" for s in last):
            new_stage = "active_labour"
        elif len(last) >= self.consecutive and all(s in ("early_labour", "active_labour") for s in last):
            new_stage = "early_labour" if e.stage == "none" else e.stage
        elif len(last) >= self.consecutive and all(s == "none" for s in last):
            new_stage = "none"
        self._apply_stage(e, new_stage, frame, ts, "ewe %d" % e.track_id, e.last_box)

    def _apply_stage(self, e: Optional[EweState], stage: str, frame: np.ndarray, ts: float,
                     who: str, box: Optional[Track]) -> None:
        prev = e.stage if e else "none"
        key = self.key(e.track_id if e else "pen")
        if stage != prev:
            self.alarm.clear(key)
            if e:
                e.stage = stage
                e.active_since = ts if stage == "active_labour" else (e.active_since if stage == "lamb_delivered" else None)
        shown = _draw_box(frame, box) if box is not None else frame
        if stage == "lamb_delivered":
            snap = self.event("urgent", "lamb_delivered", "%s: lamb delivered" % who, shown,
                              e.track_id if e else None, None, ts)
            self.alarm.send("LAMB BORN – %s, camera %s. Check ewe and lamb now." % (who, self.camera),
                            shown, key, self.repeat, "urgent")
        elif stage == "active_labour":
            self.event("urgent", "active_labour", "%s: active labour" % who, shown,
                       e.track_id if e else None, None, ts)
            self.alarm.send("LAMBING STARTED – %s, camera %s is in active labour (lying on side, "
                            "straining). Go to the pen." % (who, self.camera),
                            shown, key, self.repeat, "urgent")
        elif stage == "early_labour" and prev == "none":
            self.event("warning", "early_labour", "%s: early labour signs" % who, shown,
                       e.track_id if e else None, None, ts)
            if self.pre_alarm:
                self.alarm.send("Early labour signs – %s, camera %s is restless and apart from the "
                                "flock. Birth likely within hours." % (who, self.camera),
                                shown, key, self.cooldown, "warning")
        elif stage == "none" and prev != "none":
            self.event("info", "labour_cleared", "%s: no labour signs any more" % who, None,
                       e.track_id if e else None, None, ts)

    def _check_dystocia(self, e: EweState, frame: np.ndarray, ts: float) -> None:
        if e.stage == "active_labour" and e.active_since and ts - e.active_since >= self.dystocia_minutes:
            key = self.key(e.track_id, "dystocia")
            shown = _draw_box(frame, e.last_box)
            if self.alarm.send("PROBLEM BIRTH – ewe %d, camera %s has been in active labour for more "
                               "than %d minutes with no lamb. Possible dystocia, check her now." %
                               (e.track_id, self.camera, self.dystocia_minutes / 60),
                               shown, key, self.repeat, "urgent"):
                self.event("urgent", "dystocia", "ewe %d: prolonged labour" % e.track_id, shown,
                           e.track_id, None, ts)

    def _safety_net(self, frame: np.ndarray, ts: float) -> None:
        res = self.vision.ask({"pen": frame}, {"stage": PEN_QUESTION, "lamb_visible": LAMB_QUESTION},
                              state={"camera": self.camera}, urgent=False)
        if res.error:
            return
        stage = str(res.get("stage", "none")).lower()
        if res.yes("lamb_visible"):
            stage = "lamb_delivered"
        self.event("info", "safety_net", "pen check: %s" % stage, None, None, {"answers": res.answers}, ts)
        if stage in ("active_labour", "lamb_delivered"):
            # pen-level alarm, not tied to a track
            self._apply_stage(None, stage, frame, ts, "a ewe in the pen", None)
        elif stage == "early_labour":
            # make every ewe a suspect so per-ewe confirmation kicks in quickly
            for e in self.ewes.values():
                e.last_confirm = min(e.last_confirm, ts - self.interval)
                e.stage_hist.append("early_labour")


def _draw_box(frame: np.ndarray, box: Optional[Track]) -> np.ndarray:
    if box is None:
        return frame
    import cv2
    out = frame.copy()
    cv2.rectangle(out, (int(box.x1), int(box.y1)), (int(box.x2), int(box.y2)), (0, 0, 255), 3)
    return out
