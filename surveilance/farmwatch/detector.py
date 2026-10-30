"""YOLO detection + ByteTrack tracking of sheep, people, dogs and vehicles."""
import logging
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

import numpy as np

log = logging.getLogger(__name__)

# COCO class ids used by the stock YOLO models
COCO = {"person": 0, "car": 2, "motorcycle": 3, "bus": 5, "truck": 7, "dog": 16, "sheep": 18}
COCO_NAMES = {v: k for k, v in COCO.items()}


@dataclass
class Track:
    track_id: int
    cls: str
    x1: float
    y1: float
    x2: float
    y2: float
    conf: float

    @property
    def w(self) -> float:
        return self.x2 - self.x1

    @property
    def h(self) -> float:
        return self.y2 - self.y1

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2

    @property
    def foot(self) -> Tuple[float, float]:
        """Bottom-centre point: where the animal touches the ground."""
        return (self.cx, self.y2)

    def crop(self, frame: np.ndarray, margin: float = 0.6, min_side: int = 320) -> np.ndarray:
        """Crop the frame around the box with a margin, at least min_side pixels."""
        H, W = frame.shape[:2]
        w = max(self.w * (1 + margin), min_side)
        h = max(self.h * (1 + margin), min_side)
        x1 = int(max(0, self.cx - w / 2))
        y1 = int(max(0, self.cy - h / 2))
        x2 = int(min(W, self.cx + w / 2))
        y2 = int(min(H, self.cy + h / 2))
        return frame[y1:y2, x1:x2]


class Detector:
    def __init__(self, model: str = "yolo11n.pt", conf: float = 0.35,
                 tracker: str = "bytetrack.yaml", classes: Sequence[str] = ("sheep",),
                 device: str = ""):
        from ultralytics import YOLO  # heavy import, keep it lazy
        self.model = YOLO(model)
        self.conf = conf
        self.tracker = tracker
        self.class_ids = sorted({COCO[c] for c in classes})
        self.device = device or None

    def track(self, frame: np.ndarray) -> List[Track]:
        results = self.model.track(
            frame, persist=True, conf=self.conf, classes=self.class_ids,
            tracker=self.tracker, verbose=False, device=self.device,
        )
        out: List[Track] = []
        if not results:
            return out
        r = results[0]
        if r.boxes is None or r.boxes.id is None:
            return out
        xyxy = r.boxes.xyxy.cpu().numpy()
        ids = r.boxes.id.cpu().numpy().astype(int)
        confs = r.boxes.conf.cpu().numpy()
        clss = r.boxes.cls.cpu().numpy().astype(int)
        for (x1, y1, x2, y2), tid, c, k in zip(xyxy, ids, confs, clss):
            out.append(Track(int(tid), COCO_NAMES.get(int(k), str(k)),
                             float(x1), float(y1), float(x2), float(y2), float(c)))
        return out


def by_class(tracks: Sequence[Track]) -> Dict[str, List[Track]]:
    groups: Dict[str, List[Track]] = {}
    for t in tracks:
        groups.setdefault(t.cls, []).append(t)
    return groups
