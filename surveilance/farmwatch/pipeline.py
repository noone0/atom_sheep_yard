"""One pipeline per camera: frames -> detector -> monitors."""
import logging
import threading
import time
from typing import Any, Dict, List

from .alarm import Alarm
from .camera import Camera
from .detector import Detector
from .monitors.base import Monitor
from .monitors.feeding import FeedingMonitor
from .monitors.intruder import IntruderMonitor
from .monitors.lambing import LambingMonitor
from .storage import Storage
from .vision import VisionClient

log = logging.getLogger(__name__)

MONITORS = {"lambing": LambingMonitor, "feeding": FeedingMonitor, "intruder": IntruderMonitor}


class CameraPipeline(threading.Thread):
    def __init__(self, cam_cfg: Dict[str, Any], global_cfg: Dict[str, Any],
                 vision: VisionClient, alarm: Alarm, storage: Storage, speed: float = 1.0,
                 max_frames: int = 0):
        super().__init__(daemon=True, name="cam-" + cam_cfg["name"])
        self.name_ = cam_cfg["name"]
        det = dict(global_cfg.get("detector", {}))
        det.update(cam_cfg.get("detector", {}))
        self.camera = Camera(self.name_, cam_cfg["source"], float(det.get("sample_fps", 2)), speed)
        self.monitors: List[Monitor] = []
        for mname in cam_cfg.get("monitors", ["lambing"]):
            cls = MONITORS[mname]
            mcfg = dict(global_cfg.get(mname, {}))
            mcfg.update(cam_cfg.get(mname, {}))  # per-camera overrides (troughs, zones, hours)
            self.monitors.append(cls(self.name_, mcfg, vision, alarm, storage))
        classes = sorted({c for m in self.monitors for c in m.classes})
        self.detector = Detector(det.get("model", "yolo11n.pt"), float(det.get("conf", 0.35)),
                                 det.get("tracker", "bytetrack.yaml"), classes, det.get("device", ""))
        self.max_frames = max_frames
        self.frames = 0
        self.stopped = False
        log.info("[%s] monitors=%s classes=%s", self.name_, [m.name for m in self.monitors], classes)

    def run(self) -> None:
        t_last_log = time.time()
        for ts, frame in self.camera.frames():
            if self.stopped:
                break
            try:
                tracks = self.detector.track(frame)
                for m in self.monitors:
                    m.on_frame(ts, frame, tracks)
            except Exception:
                log.exception("[%s] frame processing failed", self.name_)
            self.frames += 1
            if time.time() - t_last_log > 60:
                t_last_log = time.time()
                log.info("[%s] %d frames processed, %d tracks in last frame", self.name_, self.frames, len(tracks))
            if self.max_frames and self.frames >= self.max_frames:
                break
        self.camera.close()
        log.info("[%s] pipeline finished after %d frames", self.name_, self.frames)
