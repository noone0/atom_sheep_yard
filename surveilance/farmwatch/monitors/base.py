"""Common plumbing for monitors."""
import logging
from typing import Any, Dict, List, Sequence

import numpy as np

from ..alarm import Alarm
from ..detector import Track
from ..storage import Storage
from ..vision import VisionClient


class Monitor:
    """A monitor receives tracked detections for one camera and raises alarms."""
    name = "monitor"
    #: YOLO classes this monitor needs the detector to produce
    classes: Sequence[str] = ("sheep",)

    def __init__(self, camera: str, cfg: Dict[str, Any], vision: VisionClient,
                 alarm: Alarm, storage: Storage):
        self.camera = camera
        self.cfg = cfg
        self.vision = vision
        self.alarm = alarm
        self.storage = storage
        self.log = logging.getLogger("%s.%s" % (self.name, camera))

    def on_frame(self, ts: float, frame: np.ndarray, tracks: List[Track]) -> None:
        raise NotImplementedError

    # helpers --------------------------------------------------------------
    def event(self, level: str, kind: str, message: str, frame: np.ndarray = None,
              track_id: int = None, extra: Dict[str, Any] = None, ts: float = None) -> str:
        snap = self.storage.snapshot(self.camera, frame, kind) if frame is not None else None
        self.storage.event(self.camera, self.name, level, kind, message, track_id, snap, extra, ts)
        return snap

    def key(self, *parts: Any) -> str:
        return ":".join([self.camera, self.name] + [str(p) for p in parts])
